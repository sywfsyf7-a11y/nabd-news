# -*- coding: utf-8 -*-
"""
World Pulse / نبض العالم
منصة إخبارية ثنائية اللغة: Flask + Supabase (PostgreSQL) + Gemini

متغيرات البيئة على Render:
  DATABASE_URL      (مطلوب)  رابط الاتصال من Supabase. الأفضل رابط الـ Pooler (IPv4).
  GEMINI_API_KEY    (اختياري) لتنقيح وصياغة الأخبار وترجمتها وحساب وقت القراءة.
  GEMINI_MODEL      (اختياري) الافتراضي: gemini-2.5-flash
  REFRESH_MINUTES   (اختياري) فترة جلب الأخبار، الافتراضي 30
  MAX_NEW_PER_CYCLE (اختياري) أقصى عدد أخبار جديدة في كل دورة، الافتراضي 16
  ADMIN_TOKEN       (اختياري) لتشغيل التحديث يدوياً عبر POST /api/refresh
  PYTHON_VERSION    يُفضّل 3.12.7

أمر التشغيل على Render:
  gunicorn app:app --workers 1 --threads 4 --timeout 120
"""

import hashlib
import html
import json
import logging
import math
import os
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlparse

import psycopg2
import psycopg2.extras
import requests
from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("worldpulse")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
try:
    app.json.ensure_ascii = False  # Flask >= 2.2
except Exception:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


REFRESH_MINUTES = max(5, _int_env("REFRESH_MINUTES", 30))
MAX_NEW_PER_CYCLE = max(1, _int_env("MAX_NEW_PER_CYCLE", 16))
PER_CATEGORY = 3          # أقصى عدد أخبار جديدة لكل قسم في الدورة
KEEP_DAYS = 14            # مدة الاحتفاظ بالأخبار
ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "1") != "0"

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WorldPulseBot/1.0)"}

# الأقسام الثمانية + مصادر RSS لكل قسم
CATEGORIES = {
    "politics": {
        "ar": "سياسة", "en": "Politics",
        "feeds": ["https://feeds.bbci.co.uk/news/politics/rss.xml",
                  "https://www.theguardian.com/politics/rss"],
    },
    "economy": {
        "ar": "اقتصاد", "en": "Economy",
        "feeds": ["https://feeds.bbci.co.uk/news/business/rss.xml",
                  "https://www.theguardian.com/uk/business/rss"],
    },
    "technology": {
        "ar": "تكنولوجيا", "en": "Technology",
        "feeds": ["https://feeds.bbci.co.uk/news/technology/rss.xml",
                  "https://www.theguardian.com/technology/rss"],
    },
    "gaming": {
        "ar": "جيمنج", "en": "Gaming",
        "feeds": ["https://www.gamespot.com/feeds/news/",
                  "https://www.theguardian.com/games/rss"],
    },
    "sports": {
        "ar": "رياضة", "en": "Sports",
        "feeds": ["https://feeds.bbci.co.uk/sport/rss.xml",
                  "https://www.theguardian.com/sport/rss"],
    },
    "science": {
        "ar": "علوم", "en": "Science",
        "feeds": ["https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
                  "https://www.theguardian.com/science/rss"],
    },
    "culture": {
        "ar": "ثقافة", "en": "Culture",
        "feeds": ["https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
                  "https://www.theguardian.com/culture/rss"],
    },
    "world": {
        "ar": "أخبار العالم", "en": "World",
        "feeds": ["https://feeds.bbci.co.uk/news/world/rss.xml",
                  "https://www.theguardian.com/world/rss"],
    },
}
LANGS = ("ar", "en")


def norm_lang(value):
    return value if value in LANGS else "ar"


# ---------------------------------------------------------------------------
# الاتصال بقاعدة البيانات (مع حل مشكلة IPv4 على Render)
# ---------------------------------------------------------------------------
_ip_cache = {}


def resolve_ipv4(host):
    """يحوّل اسم المضيف إلى عنوان IPv4 فقط، لأن Render لا يدعم IPv6 للخارج."""
    if not host:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return host
    cached = _ip_cache.get(host)
    if cached and time.time() - cached[1] < 300:
        return cached[0]
    ip = None
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ip = infos[0][4][0]
    except socket.gaierror:
        log.warning("لا يوجد عنوان IPv4 للمضيف %s. استخدم رابط Supabase Pooler (IPv4).", host)
    _ip_cache[host] = (ip, time.time())
    return ip


def connect_kwargs():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL غير مضبوط")
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    p = urlparse(url)
    host = p.hostname
    kwargs = dict(
        host=host,
        port=p.port or 5432,
        dbname=(p.path or "/postgres").lstrip("/") or "postgres",
        user=unquote(p.username or ""),
        password=unquote(p.password or ""),
        sslmode="require",
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    ip = resolve_ipv4(host)
    if ip:
        kwargs["hostaddr"] = ip  # الاتصال عبر IPv4 مع بقاء host للتحقق
    return kwargs


@contextmanager
def get_conn():
    conn = None
    last_err = None
    for attempt in range(3):
        try:
            conn = psycopg2.connect(**connect_kwargs())
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            _ip_cache.clear()
            time.sleep(0.6 * (attempt + 1))
    if conn is None:
        raise last_err
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql, params=(), fetch=True):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall() if fetch else None


_db_ready = False
_db_lock = threading.Lock()


def init_db():
    global _db_ready
    if _db_ready or not DATABASE_URL:
        return _db_ready
    with _db_lock:
        if _db_ready:
            return True
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS articles (
                        id           SERIAL PRIMARY KEY,
                        story_key    TEXT NOT NULL,
                        lang         TEXT NOT NULL,
                        category     TEXT NOT NULL,
                        title        TEXT NOT NULL,
                        summary      TEXT NOT NULL,
                        content      TEXT NOT NULL,
                        image_url    TEXT,
                        source_name  TEXT,
                        source_url   TEXT,
                        read_time    INT NOT NULL DEFAULT 3,
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (story_key, lang)
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_articles_lang_cat_pub
                    ON articles (lang, category, published_at DESC);
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS refresh_state (
                        id INT PRIMARY KEY,
                        last_run TIMESTAMPTZ NOT NULL DEFAULT 'epoch'
                    );
                """)
                cur.execute("INSERT INTO refresh_state (id) VALUES (1) ON CONFLICT DO NOTHING;")
            _db_ready = True
            log.info("قاعدة البيانات جاهزة")
        except Exception as exc:  # noqa: BLE001
            log.error("فشل تهيئة قاعدة البيانات: %s", exc)
    return _db_ready


# ---------------------------------------------------------------------------
# جلب الأخبار من RSS
# ---------------------------------------------------------------------------
NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


def clean_text(raw):
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def hd_image(url):
    if not url or not url.startswith("http"):
        return None
    # صور BBC: رفع الدقة من 240 إلى 976
    url = re.sub(r"/(\d{2,3})/cpsprodpb/", "/976/cpsprodpb/", url)
    # صور Guardian: رفع العرض
    if "i.guim.co.uk" in url:
        url = re.sub(r"width=\d+", "width=1200", url)
    return url


def parse_date(value):
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def fetch_feed(url, limit=8):
    r = requests.get(url, headers=HTTP_HEADERS, timeout=12)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    source = clean_text(root.findtext("./channel/title")) or urlparse(url).netloc
    items = []
    for it in root.iter("item"):
        title = clean_text(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        desc_raw = it.findtext("description") or ""
        body_raw = it.findtext("content:encoded", namespaces=NS) or ""
        text = max(clean_text(desc_raw), clean_text(body_raw), key=len)[:2000]

        # الصورة
        image = None
        for tag in ("media:content", "media:thumbnail"):
            best = None
            for el in it.findall(tag, NS):
                u = el.get("url")
                if not u:
                    continue
                w = int(el.get("width") or 0) if str(el.get("width") or "0").isdigit() else 0
                if best is None or w > best[0]:
                    best = (w, u)
            if best:
                image = best[1]
                break
        if not image:
            enc = it.find("enclosure")
            if enc is not None and (enc.get("type") or "").startswith("image"):
                image = enc.get("url")
        if not image:
            m = IMG_RE.search(desc_raw + body_raw)
            if m:
                image = m.group(1)

        items.append({
            "title": title,
            "link": link,
            "text": text,
            "image": hd_image(image),
            "source": re.sub(r"\s*[-|–].*$", "", source) or source,
            "published": parse_date(it.findtext("pubDate")),
        })
        if len(items) >= limit:
            break
    return items


# ---------------------------------------------------------------------------
# Gemini: تنقيح وصياغة وترجمة وحساب وقت القراءة
# ---------------------------------------------------------------------------
def calc_read_time(text):
    words = len((text or "").split())
    return max(1, min(15, math.ceil(words / 200)))


def gemini_rewrite(item, category_key):
    """يعيد dict بالحقول ثنائية اللغة، أو None عند الفشل."""
    if not GEMINI_API_KEY:
        return None
    prompt = (
        "You are a professional news editor at an international news agency.\n"
        "Using ONLY the facts in the source below (do not add or invent any facts, "
        "names, numbers or quotes), produce a neutral, clear news piece in BOTH "
        "Arabic (Modern Standard) and English.\n"
        "Return strict JSON with exactly these keys:\n"
        '{"title_ar","title_en","summary_ar","summary_en","body_ar","body_en","read_time"}\n'
        "- title: concise headline, max 110 characters.\n"
        "- summary: executive summary, 1-2 sentences, max 280 characters.\n"
        "- body: 2-4 short paragraphs separated by a blank line (\\n\\n), based only on the source. "
        "If the source is thin, keep the body short rather than inventing details.\n"
        "- read_time: integer minutes needed to read the body (1-15).\n\n"
        f"Category: {category_key}\n"
        f"Source headline: {item['title']}\n"
        f"Source text: {item['text'] or '(no text, headline only)'}\n"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        r = requests.post(
            url, json=payload, timeout=60,
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        )
        if r.status_code == 429:
            log.warning("Gemini: تجاوز حد الطلبات (429)")
            return {"_rate_limited": True}
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        data = json.loads(text)
        out = {k: str(data.get(k, "")).strip() for k in
               ("title_ar", "title_en", "summary_ar", "summary_en", "body_ar", "body_en")}
        if not all(out[k] for k in ("title_ar", "title_en", "summary_ar", "summary_en", "body_ar", "body_en")):
            return None
        try:
            rt = int(data.get("read_time"))
        except (TypeError, ValueError):
            rt = 0
        out["read_time"] = rt if 1 <= rt <= 15 else None
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("Gemini فشل: %s", exc)
        return None


def short_summary(text, fallback_title):
    text = text or fallback_title
    if len(text) <= 280:
        return text
    cut = text[:280].rsplit(" ", 1)[0]
    return cut + "…"


# ---------------------------------------------------------------------------
# دورة التحديث
# ---------------------------------------------------------------------------
_refresh_lock = threading.Lock()


def claim_refresh(force=False):
    """يحجز دورة التحديث عبر جدول refresh_state (آمن مع Supabase Pooler)."""
    min_age = 0 if force else max(1, REFRESH_MINUTES // 2)
    rows = query(
        "UPDATE refresh_state SET last_run = NOW() "
        "WHERE id = 1 AND last_run < NOW() - make_interval(mins => %s) RETURNING id",
        (min_age,),
    )
    return bool(rows)


def refresh_news(force=False):
    if not DATABASE_URL or not init_db():
        return 0
    if not _refresh_lock.acquire(blocking=False):
        return 0
    added = 0
    try:
        if not claim_refresh(force):
            return 0
        log.info("بدء جلب الأخبار...")
        rate_limited = False
        for cat_key, cat in CATEGORIES.items():
            if added >= MAX_NEW_PER_CYCLE or rate_limited:
                break
            candidates = []
            for feed in cat["feeds"]:
                try:
                    candidates.extend(fetch_feed(feed))
                except Exception as exc:  # noqa: BLE001
                    log.warning("فشل جلب %s: %s", feed, exc)
            if not candidates:
                continue
            candidates.sort(key=lambda x: x["published"], reverse=True)
            seen, unique = set(), []
            for c in candidates:
                key = hashlib.sha1(c["link"].encode("utf-8")).hexdigest()[:16]
                if key not in seen:
                    seen.add(key)
                    c["key"] = key
                    unique.append(c)
            existing = {r["story_key"] for r in query(
                "SELECT DISTINCT story_key FROM articles WHERE story_key = ANY(%s)",
                ([c["key"] for c in unique],))}
            fresh = [c for c in unique if c["key"] not in existing][:PER_CATEGORY]

            for c in fresh:
                if added >= MAX_NEW_PER_CYCLE:
                    break
                ai = gemini_rewrite(c, cat_key) if GEMINI_API_KEY else None
                if ai and ai.get("_rate_limited"):
                    rate_limited = True
                    break
                rows = []
                if ai:
                    rt = ai["read_time"] or calc_read_time(ai["body_en"])
                    rows.append(("ar", ai["title_ar"], ai["summary_ar"], ai["body_ar"], rt))
                    rows.append(("en", ai["title_en"], ai["summary_en"], ai["body_en"], rt))
                    time.sleep(4)  # احتراماً لحدود الطبقة المجانية
                else:
                    body = c["text"] or c["title"]
                    rows.append(("en", c["title"], short_summary(c["text"], c["title"]),
                                 body, calc_read_time(body)))
                with get_conn() as conn, conn.cursor() as cur:
                    for lang, title, summary, body, rt in rows:
                        cur.execute(
                            """INSERT INTO articles
                               (story_key, lang, category, title, summary, content,
                                image_url, source_name, source_url, read_time, published_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (story_key, lang) DO NOTHING""",
                            (c["key"], lang, cat_key, title, summary, body,
                             c["image"], c["source"], c["link"], rt, c["published"]),
                        )
                added += 1
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM articles WHERE published_at < NOW() - make_interval(days => %s)",
                        (KEEP_DAYS,))
        log.info("انتهى الجلب: %d خبر جديد", added)
    except Exception as exc:  # noqa: BLE001
        log.error("فشل التحديث: %s", exc)
    finally:
        _refresh_lock.release()
    return added


_scheduler_started = False


def scheduler_loop():
    time.sleep(5)
    while True:
        try:
            refresh_news()
        except Exception as exc:  # noqa: BLE001
            log.error("خطأ في المجدول: %s", exc)
        time.sleep(REFRESH_MINUTES * 60)


def start_scheduler():
    global _scheduler_started
    if _scheduler_started or not ENABLE_SCHEDULER or not DATABASE_URL:
        return
    _scheduler_started = True
    threading.Thread(target=scheduler_loop, name="news-scheduler", daemon=True).start()


# ---------------------------------------------------------------------------
# محتوى احتياطي (Fallback) يضمن عدم ظهور الموقع فارغاً
# ---------------------------------------------------------------------------
def _seed():
    now = datetime.now(timezone.utc)
    data = [
        ("politics", "كيف تُصنع القرارات في المنظمات الدولية؟", "How Do International Organizations Make Decisions?",
         "نظرة مبسطة على آليات التصويت والتوافق داخل الهيئات الدولية الكبرى.",
         "A simple look at voting and consensus mechanisms inside major international bodies.",
         "تعتمد المنظمات الدولية على مزيج من التصويت والتوافق وفق ميثاق كل منظمة.\n\nتختلف القواعد بين هيئة وأخرى، فبعضها يشترط الأغلبية وبعضها يمنح حق النقض لدول بعينها.",
         "International organizations rely on a mix of voting and consensus, depending on each charter.\n\nRules differ from one body to another: some require a majority, while others grant veto power to specific members."),
        ("economy", "ما هو التضخم ولماذا يهمّك؟", "What Is Inflation and Why Does It Matter?",
         "شرح مختصر لمفهوم التضخم وأثره على الأسعار والمدخرات.",
         "A short explainer on inflation and its effect on prices and savings.",
         "التضخم هو الارتفاع العام والمستمر في أسعار السلع والخدمات مع مرور الوقت.\n\nعندما يرتفع التضخم تنخفض القوة الشرائية للنقود، ولهذا تتابع البنوك المركزية مؤشراته عن كثب.",
         "Inflation is the general, sustained rise in the prices of goods and services over time.\n\nWhen inflation rises, the purchasing power of money falls, which is why central banks watch it closely."),
        ("technology", "الذكاء الاصطناعي التوليدي في دقائق", "Generative AI in a Few Minutes",
         "ما الذي يميّز نماذج الذكاء الاصطناعي التوليدي وكيف تُستخدم اليوم؟",
         "What sets generative AI models apart, and how are they used today?",
         "تتعلم نماذج الذكاء الاصطناعي التوليدي من كميات ضخمة من البيانات لتنتج نصوصاً وصوراً وشيفرات جديدة.\n\nتُستخدم هذه النماذج في الكتابة والبرمجة والتصميم والبحث، مع ضرورة مراجعة مخرجاتها بشرياً.",
         "Generative AI models learn from vast amounts of data to produce new text, images and code.\n\nThey are used in writing, programming, design and research, though their output should always be reviewed by people."),
        ("gaming", "لماذا تنجح الألعاب المستقلة؟", "Why Indie Games Keep Succeeding",
         "الإبداع والتكلفة المنخفضة يمنحان الألعاب المستقلة مكانة متنامية.",
         "Creativity and low budgets are giving indie games a growing place in the market.",
         "تعتمد الألعاب المستقلة على أفكار جديدة وفرق صغيرة وتكاليف أقل.\n\nساعدت منصات التوزيع الرقمي هذه الألعاب على الوصول مباشرة إلى اللاعبين حول العالم.",
         "Indie games rely on fresh ideas, small teams and lower costs.\n\nDigital storefronts have helped them reach players around the world directly."),
        ("sports", "كيف يحافظ الرياضيون على لياقتهم طوال الموسم؟", "How Athletes Stay Fit Through a Long Season",
         "التغذية والنوم وإدارة الحِمل التدريبي أسرار الاستمرارية.",
         "Nutrition, sleep and training-load management are the keys to consistency.",
         "يوازن الرياضيون المحترفون بين التدريب والراحة لتجنب الإصابات.\n\nيلعب النوم الكافي والتغذية المتوازنة دوراً أساسياً في التعافي بين المباريات.",
         "Professional athletes balance training and rest to avoid injuries.\n\nEnough sleep and balanced nutrition play a central role in recovery between matches."),
        ("science", "لماذا يتغيّر لون السماء؟", "Why Does the Sky Change Color?",
         "تشتت الضوء في الغلاف الجوي يفسّر ألوان النهار والغروب.",
         "Light scattering in the atmosphere explains daytime blue and sunset reds.",
         "يتشتت الضوء الأزرق في الغلاف الجوي أكثر من غيره، ولهذا تبدو السماء زرقاء نهاراً.\n\nعند الغروب يقطع الضوء مسافة أطول فتبقى الألوان الحمراء والبرتقالية.",
         "Blue light scatters more in the atmosphere, which is why the sky looks blue by day.\n\nAt sunset the light travels farther, leaving the reds and oranges."),
        ("culture", "رحلة الأدب العالمي عبر الترجمة", "World Literature's Journey Through Translation",
         "الترجمة جسر يربط الثقافات ويمنح الأعمال الأدبية حياة جديدة.",
         "Translation is a bridge between cultures that gives literary works a new life.",
         "تتيح الترجمة للقراء الوصول إلى أعمال أدبية كُتبت بلغات أخرى.\n\nوتسهم في تبادل الأفكار وتعزيز الفهم المتبادل بين الشعوب.",
         "Translation lets readers reach works written in other languages.\n\nIt helps exchange ideas and builds mutual understanding between peoples."),
        ("world", "نبض العالم: ملخصك الإخباري قيد التحديث", "World Pulse: Your News Briefing Is Updating",
         "نعمل على جلب أحدث الأخبار من مصادر موثوقة، عُد بعد قليل.",
         "We are gathering the latest stories from trusted sources. Please check back shortly.",
         "تُحدَّث الأخبار تلقائياً على مدار اليوم من مصادر عالمية موثوقة.\n\nإلى حين اكتمال التحديث نعرض لك مواد تعريفية متنوعة.",
         "News is refreshed automatically throughout the day from trusted global sources.\n\nUntil the update completes, here are a few explainers."),
    ]
    out = {"ar": [], "en": []}
    for i, (cat, t_ar, t_en, s_ar, s_en, b_ar, b_en) in enumerate(data):
        ts = (now - timedelta(minutes=i * 7)).isoformat()
        base = {"id": f"seed-{i + 1}", "category": cat, "image": None, "source": "World Pulse",
                "source_url": None, "read_time": 2, "published_at": ts, "fallback": True}
        out["ar"].append({**base, "lang": "ar", "title": t_ar, "summary": s_ar, "content": b_ar})
        out["en"].append({**base, "lang": "en", "title": t_en, "summary": s_en, "content": b_en})
    return out


SEED = _seed()


def seed_items(lang, category=None):
    items = SEED[lang]
    if category:
        items = [i for i in items if i["category"] == category]
    return [dict(i, category_label=CATEGORIES[i["category"]][lang]) for i in items]


# ---------------------------------------------------------------------------
# تحويل الصفوف إلى JSON
# ---------------------------------------------------------------------------
def row_to_item(row, lang, full=False):
    item = {
        "id": row["story_key"],
        "lang": row["lang"],
        "category": row["category"],
        "category_label": CATEGORIES.get(row["category"], CATEGORIES["world"])[lang],
        "title": row["title"],
        "summary": row["summary"],
        "image": row["image_url"],
        "source": row["source_name"],
        "source_url": row["source_url"],
        "read_time": row["read_time"],
        "published_at": row["published_at"].isoformat(),
        "translated": row["lang"] == lang,
    }
    if full:
        item["content"] = row["content"]
    return item


COLS = ("story_key, lang, category, title, summary, content, image_url, "
        "source_name, source_url, read_time, published_at")


def get_news(lang, category=None, limit=24, offset=0):
    """يُرجع (items, has_more). يبدأ بلغة المستخدم، ثم أي لغة، ثم المحتوى الاحتياطي."""
    try:
        if DATABASE_URL and init_db():
            where, params = ["lang = %s"], [lang]
            if category:
                where.append("category = %s")
                params.append(category)
            rows = query(
                f"SELECT {COLS} FROM articles WHERE {' AND '.join(where)} "
                "ORDER BY published_at DESC LIMIT %s OFFSET %s",
                params + [limit + 1, offset])
            if not rows and offset == 0:
                # لا توجد ترجمة بعد: اعرض أي لغة متاحة بدلاً من صفحة فارغة
                where2, params2 = [], []
                if category:
                    where2.append("category = %s")
                    params2.append(category)
                clause = f"WHERE {' AND '.join(where2)}" if where2 else ""
                rows = query(
                    f"SELECT DISTINCT ON (story_key) {COLS} FROM articles {clause} "
                    "ORDER BY story_key, (lang = 'en') DESC",
                    params2)
                rows.sort(key=lambda r: r["published_at"], reverse=True)
                rows = rows[: limit + 1]
            if rows:
                has_more = len(rows) > limit
                return [row_to_item(r, lang) for r in rows[:limit]], has_more
    except Exception as exc:  # noqa: BLE001
        log.error("get_news فشل: %s", exc)
    if offset == 0:
        return seed_items(lang, category), False
    return [], False


def get_article(key, lang):
    try:
        if DATABASE_URL and init_db() and not key.startswith("seed-"):
            rows = query(
                f"SELECT {COLS} FROM articles WHERE story_key = %s "
                "ORDER BY (lang = %s) DESC LIMIT 1", (key, lang))
            if rows:
                return row_to_item(rows[0], lang, full=True)
    except Exception as exc:  # noqa: BLE001
        log.error("get_article فشل: %s", exc)
    for it in SEED[lang]:
        if it["id"] == key:
            return dict(it, category_label=CATEGORIES[it["category"]][lang])
    return None


def get_related(article, lang, limit=4):
    try:
        if DATABASE_URL and init_db() and not article["id"].startswith("seed-"):
            rows = query(
                f"""(SELECT {COLS} FROM articles WHERE lang = %s AND category = %s AND story_key <> %s
                     ORDER BY published_at DESC LIMIT %s)""",
                (lang, article["category"], article["id"], limit))
            if len(rows) < limit:
                have = [r["story_key"] for r in rows] + [article["id"]]
                more = query(
                    f"SELECT {COLS} FROM articles WHERE lang = %s AND story_key <> ALL(%s) "
                    "ORDER BY published_at DESC LIMIT %s", (lang, have, limit - len(rows)))
                rows = list(rows) + list(more)
            if rows:
                return [row_to_item(r, lang) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.error("get_related فشل: %s", exc)
    return [i for i in seed_items(lang) if i["id"] != article["id"]][:limit]


def get_breaking(lang):
    try:
        if DATABASE_URL and init_db():
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            for sql, params in (
                (f"SELECT {COLS} FROM articles WHERE lang = %s AND published_at >= %s "
                 "ORDER BY published_at DESC LIMIT 1", (lang, since)),
                (f"SELECT {COLS} FROM articles WHERE lang = %s ORDER BY published_at DESC LIMIT 1", (lang,)),
            ):
                rows = query(sql, params)
                if rows:
                    return row_to_item(rows[0], lang)
    except Exception as exc:  # noqa: BLE001
        log.error("get_breaking فشل: %s", exc)
    return seed_items(lang)[0]


# ---------------------------------------------------------------------------
# المسارات
# ---------------------------------------------------------------------------
def json_response(payload, cache=60, status=200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = f"public, max-age={cache}" if cache else "no-store"
    return resp


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/news")
def api_news():
    lang = norm_lang(request.args.get("lang"))
    category = request.args.get("category")
    if category not in CATEGORIES:
        category = None
    try:
        limit = min(max(int(request.args.get("limit", 24)), 1), 60)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit, offset = 24, 0
    items, has_more = get_news(lang, category, limit, offset)
    return json_response({"lang": lang, "category": category, "items": items, "has_more": has_more})


@app.route("/api/breaking")
def api_breaking():
    lang = norm_lang(request.args.get("lang"))
    return json_response({"lang": lang, "item": get_breaking(lang)}, cache=30)


@app.route("/api/article/<key>")
def api_article(key):
    lang = norm_lang(request.args.get("lang"))
    key = re.sub(r"[^A-Za-z0-9_-]", "", key)[:40]
    article = get_article(key, lang)
    if not article:
        return json_response({"error": "not_found"}, cache=0, status=404)
    return json_response({"lang": lang, "item": article, "related": get_related(article, lang)})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if not ADMIN_TOKEN or request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        return json_response({"error": "forbidden"}, cache=0, status=403)
    threading.Thread(target=refresh_news, kwargs={"force": True}, daemon=True).start()
    return json_response({"status": "started"}, cache=0, status=202)


@app.route("/health")
def health():
    db_ok = False
    if DATABASE_URL:
        try:
            query("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
    return json_response({"status": "ok", "database": db_ok, "gemini": bool(GEMINI_API_KEY)}, cache=0)


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return json_response({"error": "not_found"}, cache=0, status=404)
    return render_template("index.html"), 200


# تهيئة عند الاستيراد (يعمل مع gunicorn)
if DATABASE_URL:
    try:
        init_db()
    except Exception as _exc:  # noqa: BLE001
        log.error("تهيئة أولية فشلت: %s", _exc)
    start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
