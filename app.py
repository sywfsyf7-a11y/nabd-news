"""World Pulse / نبض العالم
A small Flask news portal with RSS ingestion, optional Gemini bilingual editing,
PostgreSQL persistence, and bilingual sample content as a last-resort fallback.

Render start command:
    gunicorn --workers 2 --threads 4 --timeout 90 app:app
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import feedparser
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, abort, redirect, render_template, request, session, url_for

try:
    from google import genai
    from google.genai import types
except ImportError:  # The site still starts if Gemini's optional SDK is unavailable.
    genai = None
    types = None

# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MAX_ARTICLES_PER_REFRESH = max(1, min(48, int(os.getenv("MAX_ARTICLES_PER_REFRESH", "24"))))

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
        "no_breaking": "لا تتوفر أخبار عاجلة مباشرة الآن.",
        "read_full": "قراءة الخبر كاملاً",
        "read_time": "دقائق قراءة",
        "recommended": "مقالات مقترحة",
        "source": "المصدر الأصلي",
        "back_home": "العودة إلى الأخبار",
        "sample_badge": "محتوى توضيحي — ليس خبراً حياً",
        "sample_source": "نبض العالم · محتوى توضيحي",
        "footer": "التغطية بوضوح. والسياق قبل الضجيج.",
        "empty": "لا توجد أخبار في هذا القسم حالياً. جرّب قسماً آخر.",
        "ai_note": "صياغة تحريرية بمساعدة الذكاء الاصطناعي اعتماداً على الملخص المتاح من المصدر.",
        "live": "تغطية الأخبار",
        "hero_title": "العالم يتغيّر. ابقَ على نبضه.",
        "hero_text": "أخبار من السياسة والاقتصاد والتكنولوجيا والرياضة والثقافة، في تجربة تحريرية واحدة.",
        "search_hint": "استكشف الأخبار حسب القسم",
        "published": "نُشر",
        "open_source": "متابعة الخبر لدى المصدر",
        "theme_toggle": "تبديل المظهر",
        "refresh_news": "تحديث الأخبار",
        "refreshing": "جاري تحديث الأخبار…",
        "auto_refresh": "تتحدّث الأخبار كل {minutes} دقيقة",
        "last_updated": "آخر تحديث",
        "refresh_cooldown": "تم طلب التحديث مؤخراً، انتظر قليلاً ثم جرّب مجدداً.",
        "refresh_error": "تعذّر التحديث الآن. تحقق من سجلات Render ومصادر الأخبار.",
        "image_unavailable": "صورة غير متاحة",
    },
    "en": {
        "tagline": "The world, in one pulse.",
        "all_news": "All news",
        "latest": "Latest stories",
        "breaking": "BREAKING",
        "no_breaking": "No live breaking news is available right now.",
        "read_full": "Read full story",
        "read_time": "min read",
        "recommended": "Recommended stories",
        "source": "Original source",
        "back_home": "Back to news",
        "sample_badge": "EXPLANATORY SAMPLE — NOT LIVE NEWS",
        "sample_source": "World Pulse · Explanatory sample",
        "footer": "Clarity in coverage. Context before noise.",
        "empty": "There are no stories in this section right now. Try another section.",
        "ai_note": "Editorial copy assisted by AI, based on the source material available.",
        "live": "News coverage",
        "hero_title": "The world moves. Stay in its pulse.",
        "hero_text": "Politics, business, technology, sport and culture in one editorial experience.",
        "search_hint": "Explore stories by section",
        "published": "Published",
        "open_source": "Continue at the original source",
        "theme_toggle": "Toggle appearance",
        "refresh_news": "Refresh news",
        "refreshing": "Refreshing news…",
        "auto_refresh": "News refresh every {minutes} minutes",
        "last_updated": "Last update",
        "refresh_cooldown": "A refresh was requested recently. Please wait a moment and try again.",
        "refresh_error": "Refresh failed. Check Render logs and news sources.",
        "image_unavailable": "Image unavailable",
    },
}

CATEGORY_QUERIES = {
    "politics": {"ar": "أخبار السياسة الدولية", "en": "international politics news"},
    "economy": {"ar": "أخبار الاقتصاد والأسواق", "en": "economy markets business news"},
    "technology": {"ar": "أخبار التكنولوجيا والذكاء الاصطناعي", "en": "technology artificial intelligence news"},
    "gaming": {"ar": "أخبار ألعاب الفيديو والألعاب الإلكترونية", "en": "video games gaming industry news"},
    "sports": {"ar": "أخبار الرياضة العالمية", "en": "international sports news"},
    "science": {"ar": "أخبار العلوم والاكتشافات", "en": "science research discovery news"},
    "culture": {"ar": "أخبار الثقافة والفنون والسينما", "en": "culture arts film news"},
    "world": {"ar": "أخبار العالم اليوم", "en": "world news today"},
}

CATEGORY_IMAGES = {
    "politics": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1400&q=82",
    "economy": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1400&q=82",
    "technology": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=82",
    "gaming": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1400&q=82",
    "sports": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1400&q=82",
    "science": "https://images.unsplash.com/photo-1532094349884-543bc11b234d?auto=format&fit=crop&w=1400&q=82",
    "culture": "https://images.unsplash.com/photo-1513364776144-60967b0f800f?auto=format&fit=crop&w=1400&q=82",
    "world": "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1400&q=82",
}

# Clearly labelled educational sample stories used only if live articles are absent.
SAMPLE_STORIES = [
    {
        "category": "politics", "slug": "sample-politics", "source_url": "",
        "title_ar": "كيف تساعد قراءة السياق على فهم القرارات السياسية؟",
        "title_en": "Why context matters when reading political decisions",
        "summary_ar": "فهم القرار السياسي لا يتوقف عند الإعلان عنه؛ بل يحتاج إلى النظر في الأطراف المعنية والخلفية والتصريحات الرسمية ومصادر مستقلة متعددة.",
        "summary_en": "Understanding a political decision means looking beyond the announcement to the stakeholders, background, official statements and multiple independent sources.",
        "content_ar": "تتأثر القرارات السياسية بعوامل داخلية وخارجية، ولذلك فإن قراءة العنوان وحده قد تختزل الصورة.\n\nيساعد الرجوع إلى الوثائق والتصريحات الأصلية، ومقارنة التغطيات المستقلة، على تكوين فهم أكثر توازناً. ينبغي كذلك التمييز بين الوقائع المؤكدة والتحليلات والتوقعات.",
        "content_en": "Political decisions are shaped by domestic and international factors, so a headline alone rarely tells the whole story.\n\nReading original documents, comparing independent coverage and separating confirmed facts from analysis can lead to a more balanced understanding.",
    },
    {
        "category": "economy", "slug": "sample-economy", "source_url": "",
        "title_ar": "ما المؤشرات التي تساعد على قراءة اتجاه الاقتصاد؟",
        "title_en": "Which indicators help explain where an economy is heading?",
        "summary_ar": "لا يقدّم مؤشر واحد صورة كاملة عن الاقتصاد؛ فالتضخم والتوظيف والنمو والإنفاق تتكامل لرسم صورة أوسع عن النشاط الاقتصادي.",
        "summary_en": "No single indicator tells the full economic story. Inflation, employment, growth and spending together provide a broader view of economic activity.",
        "content_ar": "تعكس المؤشرات الاقتصادية جوانب مختلفة من حياة الأفراد والشركات. فالتضخم يقيس تغير الأسعار، بينما يوضح التوظيف جانباً من سوق العمل، ويقدّر الناتج المحلي حجم النشاط الاقتصادي.\n\nالأفضل قراءة هذه الأرقام عبر الزمن ومقارنتها بمصادر موثوقة، مع الانتباه إلى أن البيانات الأولية قد تخضع للمراجعة.",
        "content_en": "Economic indicators describe different parts of life for households and businesses. Inflation tracks price changes, employment sheds light on the labour market, and GDP estimates the scale of economic activity.\n\nThese figures are most useful when compared over time and checked against reliable sources. Preliminary data may later be revised.",
    },
    {
        "category": "technology", "slug": "sample-technology", "source_url": "",
        "title_ar": "كيف يتغيّر العمل مع تطور أدوات الذكاء الاصطناعي؟",
        "title_en": "How are AI tools changing the way people work?",
        "summary_ar": "تساعد الأدوات الذكية في بعض مهام البحث والكتابة والتحليل، لكن التحقق البشري وحماية البيانات وفهم حدود النماذج تبقى ضرورية.",
        "summary_en": "AI tools can assist with research, writing and analysis, while human review, data protection and awareness of model limitations remain essential.",
        "content_ar": "يمكن للأنظمة الذكية تسريع مهام متكررة أو المساعدة في تنظيم المعلومات، لكنها قد تنتج أخطاء أو معلومات غير مكتملة.\n\nلذلك من المهم التحقق من المخرجات بالرجوع إلى المصادر الأصلية، وعدم إدخال بيانات حساسة في خدمات لا تسمح سياساتها بذلك، ومراجعة النتائج قبل استخدامها في القرارات المهمة.",
        "content_en": "AI systems can speed up repetitive tasks and help organise information, but they can also produce errors or incomplete answers.\n\nCheck outputs against original sources, avoid entering sensitive data into services whose policies do not permit it, and review results before using them in consequential decisions.",
    },
    {
        "category": "gaming", "slug": "sample-gaming", "source_url": "",
        "title_ar": "ما الذي يصنع تجربة لعب جيدة إلى جانب الرسومات؟",
        "title_en": "What makes a great game beyond its graphics?",
        "summary_ar": "تتشكّل تجربة اللعب من تصميم المراحل والاستجابة والتحكم والإيقاع وإمكانية الوصول، وليس من جودة الصورة وحدها.",
        "summary_en": "A game's experience depends on level design, responsiveness, controls, pacing and accessibility—not graphics alone.",
        "content_ar": "قد تجذب الرسومات الانتباه أولاً، لكن تفاعل اللاعب مع الأنظمة والتحديات هو ما يحدد استمرار المتعة. كما تؤثر الاستجابة السريعة والتحكم الواضح ومستويات الصعوبة المتوازنة في جودة التجربة.\n\nوتساعد خيارات الوصول، مثل تخصيص الأزرار والترجمة النصية، على جعل الألعاب مناسبة لمزيد من اللاعبين.",
        "content_en": "Graphics may attract attention, but the way players interact with systems and challenges often determines whether a game stays enjoyable. Responsive controls, clear feedback and balanced difficulty matter too.\n\nAccessibility options, including remappable controls and subtitles, can make games work for a wider range of players.",
    },
    {
        "category": "sports", "slug": "sample-sports", "source_url": "",
        "title_ar": "كيف تضيف الأرقام بُعداً جديداً لتحليل الرياضة؟",
        "title_en": "How statistics add another layer to sports analysis",
        "summary_ar": "تساعد البيانات على فهم الأداء والأنماط، لكنها تصبح أكثر فائدة عند جمعها مع مشاهدة المباراة ومعرفة ظروف المنافسة.",
        "summary_en": "Data can reveal performance patterns, but it is most useful when combined with watching the game and understanding the context of competition.",
        "content_ar": "تتيح الإحصاءات مقارنة الأداء عبر المباريات واكتشاف أنماط قد لا تظهر من الانطباع الأول. ومع ذلك، لا تفسر الأرقام كل شيء؛ فقد تتغير دلالتها بحسب المنافس وقوة الفريق والظروف المحيطة.\n\nالتحليل الجيد يجمع بين البيانات والمشاهدة المباشرة، ويتجنب تحويل الارتباط الإحصائي وحده إلى استنتاج سببي.",
        "content_en": "Statistics help compare performances across matches and reveal patterns that may not be obvious at first glance. Their meaning still depends on the opponent, team strength and surrounding circumstances.\n\nGood analysis combines data with watching the game and avoids treating statistical correlation alone as proof of cause.",
    },
    {
        "category": "science", "slug": "sample-science", "source_url": "",
        "title_ar": "لماذا تحتاج الاكتشافات العلمية إلى مراجعة وتكرار؟",
        "title_en": "Why scientific findings need review and replication",
        "summary_ar": "تُختبر قوة النتيجة العلمية عبر المنهجية الواضحة ومراجعة الأقران وإمكان تكرار التجربة، لا عبر عنوان مثير فقط.",
        "summary_en": "Scientific findings gain strength through transparent methods, peer review and replication—not simply through a striking headline.",
        "content_ar": "تبدأ المعرفة العلمية بسؤال ومنهج لاختبار فرضية، ثم تُعرض النتائج لتقييم باحثين آخرين. وقد تكشف الدراسات اللاحقة حدود النتيجة أو تؤكدها أو تعدّلها.\n\nعند قراءة خبر علمي، ابحث عن الدراسة الأصلية وحجم العينة والقيود التي ذكرها الباحثون، وانتبه إلى الفرق بين نتيجة أولية وإجماع علمي راسخ.",
        "content_en": "Scientific knowledge starts with a question and a method for testing a hypothesis. Results are then examined by other researchers, and later studies may confirm, refine or limit the original finding.\n\nWhen reading science news, look for the original study, sample size and stated limitations, and distinguish preliminary results from established scientific consensus.",
    },
    {
        "category": "culture", "slug": "sample-culture", "source_url": "",
        "title_ar": "كيف تعيد المنصات الرقمية تشكيل الوصول إلى الثقافة؟",
        "title_en": "How digital platforms are reshaping access to culture",
        "summary_ar": "توسّع المنصات فرص اكتشاف الأعمال الفنية والمعرفية، لكنها تطرح أيضاً أسئلة عن حقوق المبدعين والخوارزميات وتنوع المحتوى.",
        "summary_en": "Digital platforms make creative and educational work easier to discover, while raising questions about creator rights, algorithms and diversity.",
        "content_ar": "أتاحت المنصات للجمهور الوصول إلى الموسيقى والكتب والأفلام والفنون من أماكن متعددة، ووفرت للمبدعين قنوات جديدة للنشر.\n\nفي المقابل، تؤثر آليات التوصية في ما يراه الجمهور، وتظل حقوق الاستخدام والتعويض عن العمل الإبداعي قضايا أساسية في الاقتصاد الثقافي الرقمي.",
        "content_en": "Digital platforms let audiences discover music, books, films and art from many places while giving creators new distribution channels.\n\nRecommendation systems also shape what people see, and licensing and fair compensation remain important questions in the digital cultural economy.",
    },
    {
        "category": "world", "slug": "sample-world", "source_url": "",
        "title_ar": "خطوات بسيطة للتحقق من الأخبار المتداولة عالمياً",
        "title_en": "Practical steps for checking widely shared world news",
        "summary_ar": "تحقق من تاريخ النشر والمصدر الأصلي والصور والسياق، وقارن الخبر بتغطيات مستقلة قبل مشاركته.",
        "summary_en": "Check publication dates, original sources, images and context, then compare independent coverage before sharing a story.",
        "content_ar": "قد تعود صورة متداولة إلى حدث قديم، أو يُقتطع تصريح من سياقه، أو يُعاد نشر مادة من دون تاريخ واضح.\n\nللتثبت، افتح الرابط الأصلي، وتحقق من التاريخ والمكان والأسماء، وابحث عن تأكيد مستقل. وإذا بقيت معلومة غير مؤكدة، فمن الأفضل وصفها كذلك بدلاً من تقديمها كحقيقة.",
        "content_en": "A widely shared image may come from an older event, a quote may be taken out of context, or a post may omit its original date.\n\nOpen the original link, check dates, places and names, and seek independent confirmation. When information remains unverified, describe it as such rather than presenting it as established fact.",
    },
]

# ---------------------------------------------------------------------------
# PostgreSQL: Supabase shared pooler is preferred for Render's IPv4 network.
# ---------------------------------------------------------------------------

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_DB_RETRY_AFTER = 0.0
_DB_LOCK = threading.Lock()
_META_CACHE_LOCK = threading.Lock()
_META_CACHE: dict[str, str] = {}
_META_CACHE_AT = 0.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS world_pulse_articles (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_world_pulse_published
    ON world_pulse_articles (published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_world_pulse_category
    ON world_pulse_articles (category);
CREATE TABLE IF NOT EXISTS world_pulse_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _database_url() -> str:
    """SUPABASE_POOLER_URL should contain the Dashboard's Session Pooler URL."""
    return (os.getenv("SUPABASE_POOLER_URL") or os.getenv("DATABASE_URL") or "").strip()


def _connect_db():
    global _DB_RETRY_AFTER
    dsn = _database_url()
    if not dsn:
        return None
    if time.monotonic() < _DB_RETRY_AFTER:
        return None
    try:
        connection = psycopg2.connect(
            dsn,
            connect_timeout=max(3, int(os.getenv("DB_CONNECT_TIMEOUT", "5"))),
            sslmode=os.getenv("PGSSLMODE", "require"),
            application_name="world-pulse",
        )
        with _DB_LOCK:
            _DB_RETRY_AFTER = 0.0
        return connection
    except Exception as exc:  # Database failures must not take down the website.
        with _DB_LOCK:
            _DB_RETRY_AFTER = time.monotonic() + 60
        logger.warning("Database connection unavailable; serving fallback content. Details: %s", exc)
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
            logger.exception("Could not initialise the news table")
            return False
        finally:
            conn.close()



def _write_refresh_meta(status: str, count: int, finished_at: str, error: str = "") -> bool:
    """Persist refresh status so web workers and Render Cron jobs share one state."""
    if not _ensure_schema():
        return False
    conn = _connect_db()
    if conn is None:
        return False
    values = {
        "last_refresh_at": finished_at,
        "last_refresh_status": status,
        "last_refresh_count": str(count),
        "last_refresh_error": (error or "")[:500],
    }
    try:
        with conn.cursor() as cur:
            for key, value in values.items():
                cur.execute(
                    """INSERT INTO world_pulse_meta (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE SET
                         value = EXCLUDED.value, updated_at = NOW()""",
                    (key, value),
                )
        conn.commit()
        global _META_CACHE, _META_CACHE_AT
        with _META_CACHE_LOCK:
            _META_CACHE.update(values)
            _META_CACHE_AT = time.monotonic()
        return True
    except Exception:
        conn.rollback()
        logger.exception("Could not save news refresh status")
        return False
    finally:
        conn.close()


def _read_refresh_meta() -> dict[str, str]:
    global _META_CACHE, _META_CACHE_AT
    now = time.monotonic()
    with _META_CACHE_LOCK:
        if now - _META_CACHE_AT < 10:
            return dict(_META_CACHE)
    if not _ensure_schema():
        return {}
    conn = _connect_db()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM world_pulse_meta WHERE key LIKE 'last_refresh_%'")
            result = {str(key): str(value) for key, value in cur.fetchall()}
        with _META_CACHE_LOCK:
            _META_CACHE = result
            _META_CACHE_AT = time.monotonic()
        return result
    except Exception:
        logger.debug("Could not read news refresh status", exc_info=True)
        return {}
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
            cur.execute("""
                SELECT slug, source_url, category, source_name, image_url,
                       title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at,
                       read_minutes, original_language, is_demo
                FROM world_pulse_articles
                WHERE is_demo = FALSE
                ORDER BY published_at DESC NULLS LAST, fetched_at DESC
                LIMIT 120
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Could not read news from PostgreSQL")
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
            slug, source_url, category, source_name, image_url,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo
        ) VALUES (
            %(slug)s, %(source_url)s, %(category)s, %(source_name)s, %(image_url)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s,
            %(content_ar)s, %(content_en)s, %(published_at)s, NOW(),
            %(read_minutes)s, %(original_language)s, FALSE
        )
        ON CONFLICT (source_url) DO UPDATE SET
            category = EXCLUDED.category,
            source_name = EXCLUDED.source_name,
            image_url = CASE
                WHEN EXCLUDED.image_url <> '' THEN EXCLUDED.image_url
                ELSE world_pulse_articles.image_url
            END,
            title_ar = CASE WHEN EXCLUDED.title_ar <> '' THEN EXCLUDED.title_ar ELSE world_pulse_articles.title_ar END,
            title_en = CASE WHEN EXCLUDED.title_en <> '' THEN EXCLUDED.title_en ELSE world_pulse_articles.title_en END,
            summary_ar = CASE WHEN EXCLUDED.summary_ar <> '' THEN EXCLUDED.summary_ar ELSE world_pulse_articles.summary_ar END,
            summary_en = CASE WHEN EXCLUDED.summary_en <> '' THEN EXCLUDED.summary_en ELSE world_pulse_articles.summary_en END,
            content_ar = CASE WHEN EXCLUDED.content_ar <> '' THEN EXCLUDED.content_ar ELSE world_pulse_articles.content_ar END,
            content_en = CASE WHEN EXCLUDED.content_en <> '' THEN EXCLUDED.content_en ELSE world_pulse_articles.content_en END,
            published_at = COALESCE(EXCLUDED.published_at, world_pulse_articles.published_at),
            fetched_at = NOW(),
            read_minutes = GREATEST(EXCLUDED.read_minutes, 1),
            original_language = EXCLUDED.original_language
    """
    try:
        with conn.cursor() as cur:
            for article in articles:
                cur.execute(sql, article)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logger.exception("Could not save fetched articles")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RSS ingestion and Gemini editorial processing
# ---------------------------------------------------------------------------

_REFRESH_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_REFRESHING = False
_LAST_REFRESH_ATTEMPT = 0.0
_LAST_REFRESH_SUCCESS = 0.0
_LAST_MANUAL_REFRESH = 0.0
_LAST_REFRESH_AT = ""
_LAST_REFRESH_COUNT = 0
_REFRESH_STATE = "idle"
_REFRESH_ERROR = ""
_MEMORY_ARTICLES: dict[str, dict[str, Any]] = {}


def _clean_text(value: Any, limit: int = 2500) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
        except (ValueError, OverflowError, TypeError):
            pass
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                result = parsedate_to_datetime(value)
                return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _image_from_entry(entry: Any, category: str) -> str:
    """Use publisher-provided imagery when present; never invent a repeated photo.

    An empty URL is intentional: the template renders a designed category placeholder.
    Image availability never decides whether an article is imported.
    """
    for key in ("media_thumbnail", "media_content"):
        values = entry.get(key) or []
        for item in values:
            url = str(item.get("url", "")).strip()
            if url.startswith(("https://", "http://")):
                return url
    for item in entry.get("links", []) or []:
        href = str(item.get("href", "")).strip()
        if href.startswith(("https://", "http://")) and (
            "image" in str(item.get("type", "")).lower()
            or re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", href, re.I)
        ):
            return href
    for item in entry.get("enclosures", []) or []:
        href = str(item.get("href") or item.get("url") or "").strip()
        if href.startswith(("https://", "http://")) and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", href, re.I):
            return href
    # Some RSS entries embed a thumbnail directly in their summary/content HTML.
    html_chunks = [str(entry.get("summary", "") or "")]
    html_chunks.extend(str(part.get("value", "") or "") for part in (entry.get("content") or []))
    for chunk in html_chunks:
        match = re.search(r"<img\b[^>]*?src=[\"'](https?://[^\"']+)[\"']", chunk, re.I)
        if match:
            return html.unescape(match.group(1))
    return ""


def _parse_feed_task(category: str, lang: str) -> tuple[str, str, list[dict[str, Any]]]:
    query = CATEGORY_QUERIES[category][lang]
    if lang == "ar":
        locale = {"hl": "ar", "gl": "JO", "ceid": "JO:ar"}
    else:
        locale = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    params = {"q": f"{query} when:7d", **locale}
    feed_url = "https://news.google.com/rss/search?" + urlencode(params)
    request_obj = Request(feed_url, headers={"User-Agent": "WorldPulseNews/1.0 (+RSS reader)"})
    try:
        with urlopen(request_obj, timeout=RSS_TIMEOUT_SECONDS) as response:
            raw = response.read(2_000_000)
        feed = feedparser.parse(raw)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:20]:
            title = _clean_text(entry.get("title", ""), 350)
            url = str(entry.get("link", "")).strip()
            if not title or not url.startswith(("https://", "http://")):
                continue
            publisher = ""
            source_info = entry.get("source")
            if source_info:
                publisher = _clean_text(source_info.get("title", ""), 120)
            if not publisher and " - " in title:
                title, publisher = title.rsplit(" - ", 1)
                title = title.strip()
            items.append({
                "category": category,
                "source_url": url,
                "source_name": publisher or "Google News RSS",
                "image_url": _image_from_entry(entry, category),
                "original_title": title,
                "original_summary": _clean_text(entry.get("summary", ""), 1800),
                "published_at": _parse_published(entry),
                "original_language": lang,
            })
        return category, lang, items
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("RSS feed unavailable for %s/%s: %s", category, lang, exc)
        return category, lang, []
    except Exception:
        logger.exception("Unexpected RSS parsing error for %s/%s", category, lang)
        return category, lang, []


def _slug_for_url(url: str) -> str:
    return "story-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:18]


def _collect_rss_articles() -> list[dict[str, Any]]:
    """Collect several recent stories per category; duplicate images never filter stories."""
    tasks = [(category, lang) for category in CATEGORY_NAMES for lang in ("ar", "en")]
    by_category: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_NAMES}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(_parse_feed_task, category, lang) for category, lang in tasks]
        for future in as_completed(futures):
            try:
                category, _lang, items = future.result()
                by_category[category].extend(items)
            except Exception:
                logger.exception("RSS collection worker failed")

    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    per_category = max(1, int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "4")))
    for category in CATEGORY_NAMES:
        candidates = sorted(
            by_category[category],
            key=lambda item: item.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
            reverse=True,
        )
        category_count = 0
        for item in candidates:
            url = item["source_url"].split("#", 1)[0]
            title_key = (
                str(item.get("original_language", "")),
                re.sub(r"[^\w]", "", item.get("original_title", "").lower()),
            )
            if not url or url in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(url)
            seen_titles.add(title_key)
            item["source_url"] = url
            item["slug"] = _slug_for_url(url)
            selected.append(item)
            category_count += 1
            if category_count >= per_category:
                break
    selected.sort(key=lambda item: item.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return selected[:MAX_ARTICLES_PER_REFRESH]


def _looks_arabic(value: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", value or ""))


def _base_article(raw: dict[str, Any]) -> dict[str, Any]:
    title = raw.get("original_title", "").strip()
    summary = raw.get("original_summary", "").strip()
    original_lang = raw.get("original_language", "ar" if _looks_arabic(title) else "en")
    if not summary:
        summary = title
    return {
        "slug": raw["slug"],
        "source_url": raw["source_url"],
        "category": raw["category"],
        "source_name": raw.get("source_name") or "",
        "image_url": raw.get("image_url") or "",
        "title_ar": title if original_lang == "ar" else "",
        "title_en": title if original_lang == "en" else "",
        "summary_ar": summary if original_lang == "ar" else "",
        "summary_en": summary if original_lang == "en" else "",
        "content_ar": summary if original_lang == "ar" else "",
        "content_en": summary if original_lang == "en" else "",
        "published_at": raw.get("published_at"),
        "read_minutes": 1,
        "original_language": original_lang,
        "is_demo": False,
        "fetched_at": datetime.now(timezone.utc),
    }


def _translate_batch(raw_articles: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """Return both language versions. Failure is non-fatal; source-language RSS remains usable."""
    if not raw_articles or not GEMINI_API_KEY or genai is None or types is None:
        return {}
    payload = [
        {
            "index": i,
            "category": article["category"],
            "title": article.get("original_title", "")[:350],
            "source": article.get("source_name", "")[:120],
            "excerpt": article.get("original_summary", "")[:1200],
        }
        for i, article in enumerate(raw_articles)
    ]
    prompt = f"""You are the bilingual desk editor for World Pulse, a news summarisation website.
For every item below, return an object in a JSON object with one key named stories.
Each story must preserve the provided index and include exactly these text fields:
index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en.
Write concise, clear Modern Standard Arabic and neutral international English.
Write a factual headline, a 1-2 sentence executive summary, and 2 short paragraphs of article-style summary in each language.
Use only information explicitly supported by the supplied title and excerpt. Do not invent names, numbers, quotes, dates, causes, outcomes, or details. If the excerpt is thin, keep the article brief and make the uncertainty clear. Do not claim to reproduce the full original article. Do not include markdown, source commentary, extra keys, or text outside valid JSON.
Input JSON: {json.dumps(payload, ensure_ascii=False)}"""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
        )
        response_text = (response.text or "").strip()
        response_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.I)
        parsed = json.loads(response_text)
        stories = parsed.get("stories", []) if isinstance(parsed, dict) else parsed
        result: dict[int, dict[str, str]] = {}
        for story in stories:
            try:
                index = int(story.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(raw_articles):
                continue
            fields = {}
            for key in ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"):
                fields[key] = _clean_text(story.get(key, ""), 6000) if key.startswith("title_") or key.startswith("summary_") else html.unescape(str(story.get(key, "") or "")).strip()[:12000]
            if fields.get("title_ar") and fields.get("title_en"):
                result[index] = fields
        return result
    except Exception as exc:
        logger.warning("Gemini editorial processing failed; RSS source language will be retained: %s", exc)
        return {}


def _reading_minutes(article: dict[str, Any]) -> int:
    text = " ".join(str(article.get(key, "")) for key in (
        "title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"
    ))
    words = len(text.split())
    return max(1, min(20, (words // 400) + 1))


def _record_refresh_result(status: str, count: int, error: str = "") -> bool:
    global _LAST_REFRESH_AT, _LAST_REFRESH_COUNT, _REFRESH_STATE, _REFRESH_ERROR
    finished_at = datetime.now(timezone.utc).isoformat()
    with _STATE_LOCK:
        _LAST_REFRESH_AT = finished_at
        _LAST_REFRESH_COUNT = count
        _REFRESH_STATE = status
        _REFRESH_ERROR = (error or "")[:500]
    return _write_refresh_meta(status, count, finished_at, error)


def _refresh_news_job() -> bool:
    """Fetch and store stories. Returns whether the result was persisted."""
    global _REFRESHING, _LAST_REFRESH_SUCCESS, _REFRESH_STATE
    with _STATE_LOCK:
        _REFRESHING = True
        _REFRESH_STATE = "running"
    try:
        raw_articles = _collect_rss_articles()
        if not raw_articles:
            _LAST_REFRESH_SUCCESS = time.monotonic()
            meta_saved = _record_refresh_result("no_stories", 0)
            logger.info("RSS refresh returned no stories; existing stories remain available")
            return meta_saved

        translations = _translate_batch(raw_articles)
        ready: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_articles):
            article = _base_article(raw)
            if index in translations:
                article.update(translations[index])
            article["read_minutes"] = _reading_minutes(article)
            ready.append(article)
            _MEMORY_ARTICLES[article["source_url"]] = article

        persisted = _db_upsert_many(ready)
        _LAST_REFRESH_SUCCESS = time.monotonic()
        status = "success" if persisted else "memory_only"
        metadata_saved = _record_refresh_result(
            status, len(ready), "" if persisted else "Database unavailable; stories remain in this worker's memory only"
        )
        logger.info("News refresh complete: %s stories processed; persisted=%s", len(ready), persisted)
        return persisted and metadata_saved
    except Exception as exc:
        logger.exception("Unexpected failure while refreshing news")
        _record_refresh_result("error", 0, str(exc))
        return False
    finally:
        with _STATE_LOCK:
            _REFRESHING = False
            if _REFRESH_STATE == "running":
                _REFRESH_STATE = "idle"


def _maybe_start_refresh(force: bool = False) -> str:
    """Start a background refresh without blocking page rendering.

    Normal refreshes are opportunistic on visits; Render Cron Jobs provide the reliable
    schedule even when the web service has no traffic or is sleeping.
    """
    global _REFRESHING, _LAST_REFRESH_ATTEMPT, _LAST_MANUAL_REFRESH, _REFRESH_STATE
    if not NEWS_AUTO_FETCH:
        return "disabled"
    now = time.monotonic()
    with _STATE_LOCK:
        if _REFRESHING:
            return "running"
        if force and now - _LAST_MANUAL_REFRESH < 45:
            return "cooldown"
        interval = NEWS_REFRESH_MINUTES * 60 if _LAST_REFRESH_SUCCESS else NEWS_RETRY_MINUTES * 60
        if not force:
            if _LAST_REFRESH_ATTEMPT and now - _LAST_REFRESH_ATTEMPT < min(interval, NEWS_RETRY_MINUTES * 60):
                return "cooldown"
            if _LAST_REFRESH_SUCCESS and now - _LAST_REFRESH_SUCCESS < interval:
                return "fresh"
        _LAST_REFRESH_ATTEMPT = now
        if force:
            _LAST_MANUAL_REFRESH = now
        _REFRESHING = True
        _REFRESH_STATE = "running"
    thread = threading.Thread(target=_refresh_news_job, name="world-pulse-rss-refresh", daemon=True)
    thread.start()
    return "started"


# ---------------------------------------------------------------------------
# Display helpers, fallback and routes
# ---------------------------------------------------------------------------


def _sample_articles() -> list[dict[str, Any]]:
    result = []
    for template in SAMPLE_STORIES:
        story = dict(template)
        story.update({
            "source_name": "نبض العالم · محتوى توضيحي" if story["category"] else "World Pulse · Explanatory sample",
            "image_url": CATEGORY_IMAGES[story["category"]],
            "published_at": None,
            "fetched_at": None,
            "read_minutes": max(1, (len((story.get("content_ar", "") + story.get("content_en", "")).split()) // 400) + 1),
            "original_language": "both",
            "is_demo": True,
        })
        result.append(story)
    return result


def _normalise_story(row: dict[str, Any], lang: str) -> dict[str, Any]:
    story = dict(row)
    story.setdefault("source_name", "")
    story.setdefault("image_url", "")
    # Older builds stored one generic image per category. Stop repeating those old photos.
    category = story.get("category", "world")
    if story.get("image_url") == CATEGORY_IMAGES.get(category):
        story["image_url"] = ""
    story.setdefault("is_demo", False)
    if story.get("is_demo"):
        story["source_name"] = UI_TEXT[lang]["sample_source"]
    story["title"] = story.get(f"title_{lang}") or ""
    story["summary"] = story.get(f"summary_{lang}") or ""
    story["content"] = story.get(f"content_{lang}") or story["summary"] or story["title"]
    story["category_label"] = CATEGORY_NAMES.get(story.get("category", "world"), CATEGORY_NAMES["world"])[lang]
    story["published_label"] = _format_date(story.get("published_at"), lang)
    story["read_minutes"] = max(1, int(story.get("read_minutes") or 1))
    if not story.get("slug"):
        story["slug"] = _slug_for_url(story.get("source_url", "world-pulse"))
    return story


def _all_live_articles() -> list[dict[str, Any]]:
    # Database is the durable source; memory also covers a DB outage during this worker's life.
    rows = _db_fetch_all()
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("source_url") or row.get("slug") or "")
        if key:
            by_url[key] = row
    for key, row in _MEMORY_ARTICLES.items():
        by_url[key] = row
    result = list(by_url.values())
    result.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result


def _get_display_stories(lang: str) -> list[dict[str, Any]]:
    live = [row for row in _all_live_articles() if row.get(f"title_{lang}") and row.get("category") in CATEGORY_NAMES]
    # Cover categories with explicitly labelled samples if the chosen language lacks live news.
    live_categories = {row.get("category") for row in live}
    supplements = [row for row in _sample_articles() if row.get("category") not in live_categories]
    combined = live + supplements
    combined.sort(
        key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    output = [_normalise_story(row, lang) for row in combined]
    # If publishers syndicate the same image across many stories, show it only once on
    # this page. We retain every story and render a category illustration in its place.
    seen_images: set[str] = set()
    for story in output:
        image_url = str(story.get("image_url") or "").strip()
        if not image_url:
            continue
        key = image_url.split("?", 1)[0].rstrip("/").lower()
        if key in seen_images:
            story["image_url"] = ""
        else:
            seen_images.add(key)
    return output


def _find_article(slug: str, lang: str) -> dict[str, Any] | None:
    for row in _all_live_articles():
        if row.get("slug") == slug and row.get(f"title_{lang}"):
            return _normalise_story(row, lang)
    for row in _sample_articles():
        if row.get("slug") == slug:
            return _normalise_story(row, lang)
    return None


def _format_date(value: Any, lang: str) -> str:
    if not value:
        return "محتوى توضيحي" if lang == "ar" else "Explanatory sample"
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(TIMEZONE)
        if lang == "en":
            return parsed.strftime("%b %d, %Y · %H:%M")
        months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
        return f"{parsed.day} {months[parsed.month - 1]} {parsed.year} · {parsed.strftime('%H:%M')}"
    except (ValueError, TypeError, OverflowError):
        return ""


def _today_breaking(stories: list[dict[str, Any]], lang: str) -> dict[str, Any] | None:
    today = datetime.now(TIMEZONE).date()
    for story in stories:
        published = story.get("published_at")
        if not published or story.get("is_demo"):
            continue
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue
        if isinstance(published, datetime):
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published.astimezone(TIMEZONE).date() == today:
                return story
    return None


@app.before_request
def remember_language() -> None:
    requested = request.args.get("lang", "").lower()
    if requested in ("ar", "en"):
        session["lang"] = requested


def current_language() -> str:
    value = session.get("lang", "ar")
    return value if value in ("ar", "en") else "ar"


@app.context_processor
def inject_shared_template_data() -> dict[str, Any]:
    lang = current_language()
    return {
        "lang": lang,
        "ui": UI_TEXT[lang],
        "site_name": SITE_NAME_AR if lang == "ar" else SITE_NAME_EN,
        "site_name_other": SITE_NAME_EN if lang == "ar" else SITE_NAME_AR,
        "categories": [{"key": key, "label": value[lang]} for key, value in CATEGORY_NAMES.items()],
        "category_names": CATEGORY_NAMES,
        "category_images": CATEGORY_IMAGES,
        "news_refresh_interval": NEWS_REFRESH_MINUTES,
        "now_year": datetime.now(TIMEZONE).year,
    }


@app.get("/")
def index():
    _maybe_start_refresh()
    lang = current_language()
    category = request.args.get("category", "all").lower()
    if category not in CATEGORY_NAMES and category != "all":
        category = "all"
    all_stories = _get_display_stories(lang)
    stories = all_stories if category == "all" else [s for s in all_stories if s["category"] == category]
    return render_template(
        "index.html",
        page="home",
        stories=stories,
        all_story_count=len(all_stories),
        active_category=category,
        breaking_story=_today_breaking(all_stories, lang),
        related_stories=[],
        article=None,
    )


@app.post("/api/refresh")
def api_refresh():
    state = _maybe_start_refresh(force=True)
    code = 202 if state == "started" else 200
    return {"state": state, "interval_minutes": NEWS_REFRESH_MINUTES}, code


@app.get("/api/news-status")
def api_news_status():
    # An open browser tab keeps the normal refresh cycle alive even without navigation.
    # Use a Render Cron Job as well when updates must run with no visitors at all.
    _maybe_start_refresh()
    # Cron Jobs run in a separate process; persisted metadata is the shared source of truth.
    meta = _read_refresh_meta()
    with _STATE_LOCK:
        local = {
            "state": _REFRESH_STATE,
            "last_refresh_at": _LAST_REFRESH_AT,
            "count": _LAST_REFRESH_COUNT,
            "error": _REFRESH_ERROR,
            "running": _REFRESHING,
        }
    if not local["running"]:
        local_at = str(local.get("last_refresh_at") or "")
        meta_at = str(meta.get("last_refresh_at") or "")
        # Prefer whichever worker (web or cron) has the newest completed refresh.
        if meta_at and (not local_at or meta_at >= local_at):
            local["last_refresh_at"] = meta_at
            local["count"] = int(meta.get("last_refresh_count", local["count"]) or 0)
            local["state"] = meta.get("last_refresh_status", local["state"])
            local["error"] = meta.get("last_refresh_error", local["error"])
    local["interval_minutes"] = NEWS_REFRESH_MINUTES
    return local, 200, {"Cache-Control": "no-store"}


@app.get("/article/<slug>")
def article(slug: str):
    lang = current_language()
    selected = _find_article(slug, lang)
    if selected is None:
        abort(404)
    pool = _get_display_stories(lang)
    related = [story for story in pool if story.get("slug") != slug and story.get("category") == selected.get("category")][:3]
    if len(related) < 3:
        related_ids = {story.get("slug") for story in related}
        related.extend([story for story in pool if story.get("slug") not in related_ids and story.get("slug") != slug][:3 - len(related)])
    return render_template(
        "index.html",
        page="article",
        stories=[],
        all_story_count=len(pool),
        active_category="all",
        breaking_story=None,
        related_stories=related,
        article=selected,
    )


@app.get("/healthz")
def healthz():
    # Liveness endpoint intentionally stays healthy during a database or RSS outage.
    return {"status": "ok", "database_configured": bool(_database_url()), "gemini_configured": bool(GEMINI_API_KEY)}, 200


@app.errorhandler(404)
def not_found(_error):
    lang = current_language()
    return render_template("index.html", page="404", stories=[], all_story_count=0,
                           active_category="all", breaking_story=None, related_stories=[], article=None), 404


if __name__ == "__main__":
    if "--refresh-news" in sys.argv:
        # Render Cron Job command: python app.py --refresh-news
        # Cron runs are separate processes, so successful results must be stored in PostgreSQL.
        success = _refresh_news_job()
        raise SystemExit(0 if success else 1)
    # Local development only. Render web service should use Gunicorn.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
