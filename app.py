"""World Pulse / نبض العالم
A small Flask news portal with expanded RSS ingestion, deep editorial Gemini analysis,
PostgreSQL persistence, and external AI fallback links.
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import logging
import smtplib
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, quote
import sys
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import feedparser
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("world_pulse")

SITE_NAME_AR = "نبض العالم"
SITE_NAME_EN = "World Pulse"
TIMEZONE = ZoneInfo(os.getenv("SITE_TIMEZONE", "Asia/Amman"))
NEWS_REFRESH_MINUTES = max(5, int(os.getenv("NEWS_REFRESH_MINUTES", "15")))
NEWS_RETRY_MINUTES = max(1, int(os.getenv("NEWS_RETRY_MINUTES", "3")))
NEWS_AUTO_FETCH = os.getenv("NEWS_AUTO_FETCH", "true").lower() not in {"0", "false", "no"}
RSS_TIMEOUT_SECONDS = max(2, int(os.getenv("RSS_TIMEOUT_SECONDS", "6")))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = max(10, min(60, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "35"))))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyBAKaPD4UVAb6x-gg2YnOOkIq_WWHxCXHs").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "syfsywf86@gmail.com").strip() or "syfsywf86@gmail.com"
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = max(1, min(65535, int(os.getenv("SMTP_PORT", "587"))))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
MAX_ARTICLES_PER_REFRESH = max(4, min(24, int(os.getenv("MAX_ARTICLES_PER_REFRESH", "12"))))
MAX_ARTICLES_PER_CATEGORY = max(1, min(8, int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "4"))))
IMAGE_SEARCH_TIMEOUT_SECONDS = max(3, min(12, int(os.getenv("IMAGE_SEARCH_TIMEOUT_SECONDS", "5"))))
AI_QUESTIONS_ENABLED = os.getenv("AI_QUESTIONS_ENABLED", "true").lower() not in {"0", "false", "no"}
AI_QUESTIONS_PER_HOUR = max(1, min(25, int(os.getenv("AI_QUESTIONS_PER_HOUR", "8"))))

CATEGORY_NAMES = {
    "politics": {"ar": "سياسة", "en": "Politics"},
    "economy": {"ar": "اقتصاد", "en": "Economy"},
    "technology": {"ar": "تكنولوجيا", "en": "Technology"},
    "gaming": {"ar": "جيمنج", "en": "Gaming"},
    "sports": {"ar": "رياضة", "en": "Sports"},
    "science": {"ar": "علوم", "en": "Science"},
    "culture": {"ar": "ثقافة", "en": "Culture"},
    "world": {"ar": "أخبار العالم", "en": "World"},
}

UI_TEXT = {
    "ar": {
        "tagline": "العالم، في نبض واحد.",
        "all_news": "كل الأخبار",
        "latest": "أحدث الأخبار",
        "breaking": "عاجل",
        "read_full": "قراءة الخبر كاملاً وتفاصيل التحليل",
        "read_time": "دقائق قراءة",
        "source": "المصدر الأصلي",
        "back_home": "العودة إلى الأخبار",
        "sample_source": "نبض العالم · محتوى تحليلي توضيحي",
        "footer": "التغطية بوضوح. والسياق والتحليل قبل الضجيج.",
        "empty": "لا توجد أخبار في هذا القسم حالياً. جرّب قسماً آخر.",
        "live": "تغطية الأخبار",
        "hero_title": "العالم يتغيّر. ابقَ على نبضه وتحليلاته.",
        "hero_text": "تغطية عميقة وموسعة لأبرز مستجدات السياسة والاقتصاد والتكنولوجيا والرياضة والثقافة والجيمنج.",
        "published": "نُشر",
        "open_source": "متابعة الخبر لدى المصدر الأصلي",
        "theme_toggle": "تغيير المظهر",
        "refresh_news": "تحديث الأخبار",
        "article_details": "التحليل والتفاصيل الشاملة للخبر",
        "ai_ask_title": "اسأل الذكاء الاصطناعي عن تفاصيل الخبر",
        "ai_ask_desc": "استفسر عن الخلفية، الدلالات، أو الأبعاد المستقبلية لهذا الحدث مدعوماً بنظام الذكاء الاصطناعي.",
        "ai_question_placeholder": "مثلاً: ما هي التداعيات الإقتصادية المترتبة على هذا القرار؟",
        "ai_ask_button": "اسأل نبض العالم الذكي",
        "ai_thinking": "جاري صياغة التحليل والإجابة...",
        "ai_disclaimer": "إجابة تحليلية آلية، ويُفضل مراجعة المصدر الأصلي للتأكد من التفاصيل الدقيقة.",
        "ask_chatgpt": "اسأل عبر ChatGPT ↗",
        "ask_gemini": "اسأل عبر Google Gemini ↗",
        "question_required": "يرجى كتابة سؤالك أولاً.",
    },
    "en": {
        "tagline": "The world, in one pulse.",
        "all_news": "All news",
        "latest": "Latest stories",
        "breaking": "BREAKING",
        "read_full": "Read full story & analysis",
        "read_time": "min read",
        "source": "Original source",
        "back_home": "Back to news",
        "sample_source": "World Pulse · Analytical sample",
        "footer": "Clarity in coverage. Context and analysis before noise.",
        "empty": "There are no stories in this section right now.",
        "live": "News coverage",
        "hero_title": "The world moves. Stay in its pulse and analysis.",
        "hero_text": "Deep and expanded coverage across politics, business, tech, gaming, sports and culture.",
        "published": "Published",
        "open_source": "Continue at the original source",
        "theme_toggle": "Toggle theme",
        "refresh_news": "Refresh news",
        "article_details": "Story details & deep analysis",
        "ai_ask_title": "Ask AI about this story",
        "ai_ask_desc": "Ask about background, context or implications.",
        "ai_question_placeholder": "For example: Why does this matter?",
        "ai_ask_button": "Ask World Pulse AI",
        "ai_thinking": "Preparing analysis...",
        "ai_disclaimer": "AI-generated analysis.",
        "ask_chatgpt": "Ask with ChatGPT ↗",
        "ask_gemini": "Ask with Gemini ↗",
        "question_required": "Enter a question first.",
    },
}

CATEGORY_QUERIES = {
    "politics": {"ar": "أخبار السياسة الدولية الحكومات الانتخابات الدبلوماسية الصراعات", "en": "international politics governments elections diplomacy conflicts"},
    "economy": {"ar": "أخبار الاقتصاد الأسواق البنوك المركزية الشركات المال والأعمال التضخم", "en": "global economy markets central banks business companies finance inflation"},
    "technology": {"ar": "أخبار التكنولوجيا الذكاء الاصطناعي الأجهزة والأمن السيبراني والبرمجيات", "en": "technology artificial intelligence cybersecurity software gadgets"},
    "gaming": {"ar": "أخبار ألعاب الفيديو بلايستيشن إكس بوكس نينتندو ألعاب البีسي والبطولات", "en": "video games playstation xbox nintendo pc gaming esports releases"},
    "sports": {"ar": "أخبار الرياضة كرة القدم دوري أبطال أوروبا السلة التنس الرياضات العالمية", "en": "sports football soccer champions league basketball tennis motorsport"},
    "science": {"ar": "أخبار العلوم الفضاء الفلك الطب البيئة الاكتشافات الحديثة", "en": "science space astronomy medical environment discoveries"},
    "culture": {"ar": "أخبار الثقافة الفنون السينما الكتب والموسيقى والمهرجانات", "en": "culture arts cinema books music festivals entertainment"},
    "world": {"ar": "أخبار العالم الإنسانية المجتمعات الكوارث الكبرى التطورات الدولية", "en": "world international news society humanitarian global events"},
}

DIRECT_RSS_FEEDS = {
    "politics": [
        ("BBC News Politics", "https://feeds.bbci.co.uk/news/politics/rss.xml", "en"),
        ("Al Jazeera English", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
        ("France 24 Arabic", "https://www.france24.com/ar/rss", "ar"),
        ("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "ar"),
        ("CNN Arabic", "https://arabic.cnn.com/rss", "ar"),
    ],
    "economy": [
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "en"),
        ("CNBC Arabia", "https://www.cnbcarabia.com/rss", "ar"),
        ("Financial Times", "https://www.ft.com/?format=rss", "en"),
    ],
    "technology": [
        ("TechCrunch", "https://techcrunch.com/feed/", "en"),
        ("The Verge", "https://www.theverge.com/rss/index.xml", "en"),
        ("AIT News", "https://aitnews.com/feed/", "ar"),
        ("عالم التقنية", "https://www.tech-wd.com/wd/feed/", "ar"),
    ],
    "gaming": [
        ("IGN", "https://www.ign.com/rss/v2/articles/feed", "en"),
        ("GameSpot", "https://www.gamespot.com/feeds/mashup/", "en"),
        ("Arab Hardware", "https://arabhardware.net/feed", "ar"),
        ("Saudi Gamer", "https://saudigamer.com/feed/", "ar"),
    ],
    "sports": [
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml", "en"),
        ("ESPN", "https://www.espn.com/espn/rss/news", "en"),
        ("FilGoal", "https://www.filgoal.com/rss/news", "ar"),
    ],
    "science": [
        ("NASA", "https://www.nasa.gov/feed/", "en"),
        ("Space.com", "https://www.space.com/feeds/all", "en"),
        ("Scientific American", "https://www.scientificamerican.com/feed/", "en"),
    ],
    "culture": [
        ("Literary Hub", "https://lithub.com/feed/", "en"),
        ("Al Jazeera Culture", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "en"),
        ("Euronews", "https://www.euronews.com/rss?level=theme&name=news", "en"),
    ],
}

PUBLISHER_SEARCH_FEEDS = {
    "politics": [("Global News Agencies", "site:reuters.com OR site:apnews.com", "en")],
    "economy": [("Financial Outlets", "site:bloomberg.com OR site:wsj.com", "en")],
    "technology": [("Tech Publishers", "site:theverge.com OR site:techcrunch.com", "en")],
    "gaming": [("Gaming Media", "site:ign.com OR site:gamespot.com", "en")],
    "sports": [("Sports Networks", "site:espn.com OR site:skysports.com", "en")],
    "science": [("Science News", "https://news.google.com/rss/search?q=science", "en")],
    "culture": [("Culture Outlets", "site:artsy.net", "en")],
    "world": [("World News Feed", "site:bbc.com OR site:cnn.com", "en")],
}

CATEGORY_IMAGES = {key: "" for key in CATEGORY_NAMES}

SAMPLE_STORIES = [
    {
        "category": "politics", "slug": "sample-politics", "source_url": "",
        "title_ar": "كيف تؤثر التحولات الجيوسياسية على استقرار الأسواق العالمية؟",
        "title_en": "How geopolitical shifts impact global market stability",
        "summary_ar": "تحليل شامل لأبعاد القرارات السياسية الدولية وكيف تتشابك خيوط الدبلوماسية مع الاقتصاد الحديث.",
        "summary_en": "Comprehensive analysis of international political decisions.",
        "content_ar": "تتطلب قراءة الأحداث السياسية المعاصرة تجاوز مجرد نقل العناوين إلى تفكيك المصالح المتبادلة للأطراف الفاعلة.\n\n### الخلفية والسياق التاريخي\nتشير التقارير الدبلوماسية إلى أن التحالفات الدولية تمر بمرحلة إعادة صياغة جذرية.\n\n### الأبعاد والتداعيات المتوقعة\n1. إعادة توجيه الاستثمارات.\n2. تنشيط اتفاقيات التجارة الثنائية.\n3. تصاعد أهمية الأمن السيبراني.",
        "content_en": "Understanding contemporary political events requires looking beyond quick headlines.",
    },
]

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_DB_RETRY_AFTER = 0.0
_DB_LOCK = threading.Lock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS world_pulse_articles (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    image_source TEXT NOT NULL DEFAULT '',
    image_credit TEXT NOT NULL DEFAULT '',
    image_credit_url TEXT NOT NULL DEFAULT '',
    image_license_url TEXT NOT NULL DEFAULT '',
    image_license_name TEXT NOT NULL DEFAULT '',
    image_checked_at TIMESTAMPTZ NULL,
    title_ar TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    summary_ar TEXT NOT NULL DEFAULT '',
    summary_en TEXT NOT NULL DEFAULT '',
    content_ar TEXT NOT NULL DEFAULT '',
    content_en TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_minutes INTEGER NOT NULL DEFAULT 1,
    original_language TEXT NOT NULL DEFAULT 'en',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);
"""

def _database_url() -> str:
    return (os.getenv("SUPABASE_POOLER_URL") or os.getenv("DATABASE_URL") or "").strip()

def _connect_db():
    global _DB_RETRY_AFTER
    dsn = _database_url()
    if not dsn:
        return None
    if time.monotonic() < _DB_RETRY_AFTER:
        return None
    try:
        connection = psycopg2.connect(dsn, connect_timeout=4, sslmode="require", application_name="world-pulse")
        with _DB_LOCK:
            _DB_RETRY_AFTER = 0.0
        return connection
    except Exception:
        with _DB_LOCK:
            _DB_RETRY_AFTER = time.monotonic() + 60
        return None

def _ensure_schema() -> bool:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        conn = _connect_db()
        if conn is None:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
            _SCHEMA_READY = True
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

def _db_fetch_all() -> list[dict[str, Any]]:
    if not _ensure_schema():
        return []
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM world_pulse_articles WHERE is_demo = FALSE ORDER BY published_at DESC NULLS LAST LIMIT 200")
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _db_search_articles(query: str, limit: int = 50) -> list[dict[str, Any]] | None:
    terms = [t.casefold() for t in re.findall(r"[\w\u0600-\u06ff]+", query) if len(t) > 1][:6]
    if not terms or not _ensure_schema():
        return []
    conn = _connect_db()
    if conn is None:
        return None
    fields = ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en", "source_name")
    where_parts, params = [], []
    for term in terms:
        pattern = f"%{term}%"
        where_parts.append("(" + " OR ".join(f"{f} ILIKE %s" for f in fields) + ")")
        params.extend([pattern] * len(fields))
    params.append(limit)
    sql = f"SELECT * FROM world_pulse_articles WHERE is_demo = FALSE AND {' AND '.join(where_parts)} ORDER BY published_at DESC NULLS LAST LIMIT %s"
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _db_upsert_many(articles: list[dict[str, Any]]) -> bool:
    if not articles or not _ensure_schema():
        return False
    conn = _connect_db()
    if conn is None:
        return False
    sql = """
        INSERT INTO world_pulse_articles (
            slug, source_url, category, source_name, image_url, image_source,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo
        ) VALUES (
            %(slug)s, %(source_url)s, %(category)s, %(source_name)s, %(image_url)s, %(image_source)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s, %(content_ar)s, %(content_en)s,
            %(published_at)s, NOW(), %(read_minutes)s, %(original_language)s, FALSE
        )
        ON CONFLICT (source_url) DO UPDATE SET
            title_ar = EXCLUDED.title_ar, title_en = EXCLUDED.title_en,
            summary_ar = EXCLUDED.summary_ar, summary_en = EXCLUDED.summary_en,
            content_ar = EXCLUDED.content_ar, content_en = EXCLUDED.content_en
    """
    try:
        with conn.cursor() as cur:
            for art in articles:
                cur.execute(sql, art)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

_REFRESH_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_REFRESHING = False
_MEMORY_ARTICLES: dict[str, dict[str, Any]] = {}
_LAST_REFRESH_AT: datetime | None = None
_LAST_REFRESH_STATE = "idle"

def _clean_text(val: Any, limit: int = 3000) -> str:
    text = html.unescape(str(val or ""))
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]

def _parse_published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
        except Exception:
            pass
    return None

def _parse_any_rss(feed_url: str, category: str, lang: str, default_source: str) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        req = Request(feed_url, headers={"User-Agent": "WorldPulse/2.1"})
        with urlopen(req, timeout=5) as resp:
            feed = feedparser.parse(resp.read(1_500_000))
        items = []
        for entry in feed.entries[:10]:
            title = _clean_text(entry.get("title", ""), 300)
            url = str(entry.get("link", "")).strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            src = entry.get("source")
            publisher = _clean_text(src.get("title", ""), 100) if src else default_source
            summary = _clean_text(entry.get("summary", "") or entry.get("description", ""), 1000)
            items.append({
                "category": category, "source_url": url, "source_name": publisher,
                "image_url": "", "image_source": "none", "original_title": title,
                "original_summary": summary, "published_at": _parse_published(entry),
                "original_language": lang,
            })
        return category, lang, items
    except Exception:
        return category, lang, []

def _collect_rss_articles() -> list[dict[str, Any]]:
    tasks = []
    for cat in CATEGORY_NAMES:
        for lng in ("ar", "en"):
            tasks.append(("google", cat, lng, f"https://news.google.com/rss/search?q={quote(CATEGORY_QUERIES[cat][lng])}&hl={'ar' if lng=='ar' else 'en'}"))
    for cat, feeds in DIRECT_RSS_FEEDS.items():
        for name, url, lng in feeds:
            tasks.append(("direct", cat, lng, url))

    by_cat = {c: [] for c in CATEGORY_NAMES}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_parse_any_rss, url, cat, lng, "NewsFeed") for _, cat, lng, url in tasks]
        for f in as_completed(futures):
            try:
                cat, _, items = f.result()
                if cat in by_cat:
                    by_cat[cat].extend(items)
            except Exception:
                pass

    selected, seen = [], set()
    for cat in CATEGORY_NAMES:
        items = sorted(by_cat[cat], key=lambda x: x.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
        cnt = 0
        for item in items:
            if item["source_url"] in seen:
                continue
            seen.add(item["source_url"])
            item["slug"] = "story-" + hashlib.sha256(item["source_url"].encode("utf-8")).hexdigest()[:18]
            selected.append(item)
            cnt += 1
            if cnt >= MAX_ARTICLES_PER_CATEGORY:
                break
    return selected[:MAX_ARTICLES_PER_REFRESH]

def _translate_batch(raws: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    if not raws or not GEMINI_API_KEY or genai is None or types is None:
        return {}
    res = {}
    for i, raw in enumerate(raws):
        payload = {
            "category": raw["category"],
            "title": raw.get("original_title", "")[:300],
            "source": raw.get("source_name", "")[:100],
            "excerpt": raw.get("original_summary", "")[:800],
        }
        prompt = f"""Provide deep analytical journalism in Arabic and English based on this story. Return valid JSON with keys: title_ar, title_en, summary_ar, summary_en, content_ar, content_en. Plain text only, no markdown inside fields. Input: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=25000))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3, max_output_tokens=3000),
            )
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (response.text or "").strip(), flags=re.I)
            parsed = json.loads(text)
            if parsed and isinstance(parsed, dict):
                res[i] = {k: _clean_text(parsed.get(k, ""), 4000) for k in ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en")}
        except Exception:
            continue
    return res

def _refresh_news_job() -> None:
    global _REFRESHING, _LAST_REFRESH_AT, _LAST_REFRESH_STATE
    try:
        raws = _collect_rss_articles()
        if not raws:
            return
        translations = _translate_batch(raws)
        ready = []
        for i, raw in enumerate(raws):
            if i in translations:
                art = {
                    "slug": raw["slug"], "source_url": raw["source_url"], "category": raw["category"],
                    "source_name": raw["source_name"], "image_url": "", "image_source": "none",
                    "published_at": raw.get("published_at"), "read_minutes": 2, "original_language": raw["original_language"],
                    **translations[i]
                }
                ready.append(art)
                _MEMORY_ARTICLES[art["source_url"]] = art
        _db_upsert_many(ready)
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "success"
    except Exception:
        _LAST_REFRESH_STATE = "error"
    finally:
        with _STATE_LOCK:
            _REFRESHING = False

@app.before_request
def remember_language() -> None:
    req_lang = request.args.get("lang", "").lower()
    if req_lang in ("ar", "en"):
        session["lang"] = req_lang

def current_language() -> str:
    val = session.get("lang", "ar")
    return val if val in ("ar", "en") else "ar"

@app.context_processor
def inject_shared_template_data() -> dict[str, Any]:
    lang = current_language()
    return {
        "lang": lang,
        "ui": UI_TEXT[lang],
        "site_name": SITE_NAME_AR if lang == "ar" else SITE_NAME_EN,
        "categories": [{"key": k, "label": v[lang]} for k, v in CATEGORY_NAMES.items()],
        "category_names": CATEGORY_NAMES,
        "ai_ask_enabled": AI_QUESTIONS_ENABLED and bool(GEMINI_API_KEY) and genai is not None,
        "now_year": datetime.now(TIMEZONE).year,
        "contact_email": CONTACT_EMAIL,
        "quote": quote,  # تم إصلاح تمرير الدالة هنا لتجنب أي خطأ في القالب
    }

def _normalise_story(row: dict[str, Any], lang: str) -> dict[str, Any]:
    story = dict(row)
    story.setdefault("source_name", "")
    story["title"] = story.get(f"title_{lang}") or ""
    story["summary"] = story.get(f"summary_{lang}") or ""
    story["content"] = story.get(f"content_{lang}") or ""
    story["category_label"] = CATEGORY_NAMES.get(story.get("category", "world"), CATEGORY_NAMES["world"])[lang]
    story["published_label"] = "محتوى تحليلي" if not story.get("published_at") else str(story.get("published_at"))[:16]
    return story

def _get_display_stories(lang: str) -> list[dict[str, Any]]:
    rows = _db_fetch_all()
    by_url = {r["source_url"]: r for r in rows}
    for k, v in _MEMORY_ARTICLES.items():
        by_url[k] = v
    combined = list(by_url.values())
    if not combined:
        for t in SAMPLE_STORIES:
            combined.append({**t, "is_demo": True})
    return [_normalise_story(r, lang) for r in combined if r.get(f"title_{lang}")]

@app.get("/")
def index():
    lang = current_language()
    cat = request.args.get("category", "all").lower()
    stories = _get_display_stories(lang)
    if cat in CATEGORY_NAMES:
        stories = [s for s in stories if s["category"] == cat]
    return render_template("index.html", page="home", stories=stories, active_category=cat, article=None)

@app.get("/search")
def search():
    lang = current_language()
    q = _clean_text(request.args.get("q", ""), 150)
    rows = _db_search_articles(q) if q else []
    results = [_normalise_story(r, lang) for r in (rows or []) if r.get(f"title_{lang}")]
    return render_template("index.html", page="search", stories=results, search_query=q, active_category="all", article=None)

@app.get("/article/<slug>")
def article(slug: str):
    lang = current_language()
    pool = _get_display_stories(lang)
    selected = next((s for s in pool if s.get("slug") == slug), None)
    if not selected:
        abort(404)
    related = [s for s in pool if s.get("slug") != slug and s.get("category") == selected.get("category")][:3]
    return render_template("index.html", page="article", stories=[], active_category="all", related_stories=related, article=selected)

@app.post("/api/ask")
def ask_article_ai():
    if not AI_QUESTIONS_ENABLED or not GEMINI_API_KEY or genai is None:
        return jsonify({"error": "disabled"}), 503
    payload = request.get_json(silent=True) or {}
    slug = str(payload.get("slug", ""))[:100]
    lang = str(payload.get("lang", "ar")).lower()
    question = _clean_text(payload.get("question", ""), 500)
    if not slug or not question:
        return jsonify({"error": "invalid"}), 400
    pool = _get_display_stories(lang)
    story = next((s for s in pool if s.get("slug") == slug), None)
    if not story:
        return jsonify({"error": "not_found"}), 404
    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=20000))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Title: {story.get('title')}\nSummary: {story.get('summary')}\nQuestion: {question}",
            config=types.GenerateContentConfig(system_instruction="Answer clearly in 3-4 sentences.", temperature=0.2, max_output_tokens=300),
        )
        answer = html.unescape(str(response.text or "")).strip()
        return jsonify({"answer": answer})
    except Exception:
        return jsonify({"error": "upstream_error"}), 502

@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200

@app.errorhandler(404)
def not_found(_):
    return render_template("index.html", page="404", stories=[], active_category="all", article=None), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
