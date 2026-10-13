"""World Pulse / نبض العالم
A small Flask news portal with RSS ingestion, optional Gemini bilingual editing,
PostgreSQL persistence, and bilingual sample content as a last-resort fallback.

Render start command:
    gunicorn --workers 1 --threads 4 --timeout 90 app:app
"""
from __future__ import annotations

import calendar
import difflib
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
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urljoin, quote, urlparse
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = max(10, min(60, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "35"))))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "syfsywf86@gmail.com").strip() or "syfsywf86@gmail.com"
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = max(1, min(65535, int(os.getenv("SMTP_PORT", "587"))))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
MAX_ARTICLES_PER_REFRESH = max(4, min(20, int(os.getenv("MAX_ARTICLES_PER_REFRESH", "10"))))
MAX_ARTICLES_PER_CATEGORY = max(1, min(6, int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "3"))))
IMAGE_SEARCH_TIMEOUT_SECONDS = max(3, min(12, int(os.getenv("IMAGE_SEARCH_TIMEOUT_SECONDS", "5"))))
MAX_IMAGE_LOOKUPS_PER_REFRESH = max(0, min(30, int(os.getenv("MAX_IMAGE_LOOKUPS_PER_REFRESH", "12"))))
AI_QUESTIONS_ENABLED = os.getenv("AI_QUESTIONS_ENABLED", "true").lower() not in {"0", "false", "no"}
AI_QUESTIONS_PER_HOUR = max(1, min(20, int(os.getenv("AI_QUESTIONS_PER_HOUR", "5"))))
AI_ANSWER_MAX_TOKENS = max(100, min(600, int(os.getenv("AI_ANSWER_MAX_TOKENS", "350"))))

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
        "theme_toggle": "تغيير المظهر",
        "refresh_news": "تحديث الأخبار",
        "refreshing": "جارٍ التحديث…",
        "auto_refresh": "تحديث تلقائي كل {minutes} دقيقة",
        "last_updated": "آخر تحديث",
        "refresh_cooldown": "تم طلب تحديث مؤخراً؛ انتظر قليلاً ثم حاول مجدداً.",
        "refresh_error": "تعذّر إكمال التحديث. ستبقى الأخبار المتاحة ظاهرة.",
        "article_details": "تفاصيل الخبر",
        "body_unavailable": "المصدر لم يوفّر تفاصيل إضافية موثوقة لهذا الخبر. يمكنك متابعة التفاصيل من المصدر الأصلي.",
        "photo_credit": "الصورة",
        "photo_license": "الترخيص",
        "ai_ask_title": "اسأل الذكاء الاصطناعي عن الخبر",
        "ai_ask_desc": "اسأل عن الخلفية أو المصطلحات أو ما الذي يعنيه الخبر. الإجابة تعتمد على المعلومات المتاحة في هذه الصفحة وقد تكون غير مكتملة.",
        "ai_question_placeholder": "مثلاً: لماذا يُعد هذا الخبر مهماً؟",
        "ai_ask_button": "اسأل نبض العالم",
        "ai_thinking": "جارٍ إعداد الإجابة…",
        "ai_disabled": "الإجابة داخل الموقع تحتاج تفعيل مفتاح Gemini في إعدادات Render.",
        "ai_error": "لم نتمكن من إعداد إجابة الآن. حاول لاحقاً أو راجع المصدر الأصلي.",
        "ai_rate_limit": "وصلت إلى الحد المؤقت للأسئلة. حاول بعد ساعة.",
        "ai_disclaimer": "إجابة آلية للتوضيح، وليست بديلاً عن التحقق من المصدر الأصلي.",
        "ask_chatgpt": "اسأل عبر ChatGPT",
        "ask_gemini": "اسأل عبر Gemini",
        "question_required": "اكتب سؤالك أولاً.",
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
        "theme_toggle": "Toggle theme",
        "refresh_news": "Refresh news",
        "refreshing": "Refreshing…",
        "auto_refresh": "News refresh automatically every {minutes} minutes",
        "last_updated": "Last updated",
        "refresh_cooldown": "A refresh was requested recently. Please wait a moment and try again.",
        "refresh_error": "The refresh could not be completed. Available stories will remain visible.",
        "article_details": "Story details",
        "body_unavailable": "The source did not provide enough verified detail for a longer summary. Continue reading at the original source.",
        "photo_credit": "Photo",
        "photo_license": "License",
        "ai_ask_title": "Ask AI about this story",
        "ai_ask_desc": "Ask about background, terms, or why this story matters. Answers use the information available on this page and may be incomplete.",
        "ai_question_placeholder": "For example: Why does this story matter?",
        "ai_ask_button": "Ask World Pulse",
        "ai_thinking": "Preparing an answer…",
        "ai_disabled": "In-site answers require a Gemini API key in Render settings.",
        "ai_error": "We could not prepare an answer right now. Try later or check the original source.",
        "ai_rate_limit": "You have reached the temporary question limit. Try again in an hour.",
        "ai_disclaimer": "AI-generated explanation, not a substitute for checking the original source.",
        "ask_chatgpt": "Ask with ChatGPT",
        "ask_gemini": "Ask with Gemini",
        "question_required": "Enter a question first.",
    },
}

CATEGORY_QUERIES = {
    "politics": {"ar": "أخبار السياسة الدولية الحكومات الانتخابات الدبلوماسية", "en": "international politics governments elections diplomacy"},
    "economy": {"ar": "أخبار الاقتصاد الأسواق الشركات المال الأعمال", "en": "global economy markets business companies finance"},
    "technology": {"ar": "أخبار التكنولوجيا الذكاء الاصطناعي الشركات والأمن السيبراني", "en": "technology AI cybersecurity gadgets software companies"},
    "gaming": {"ar": "أخبار ألعاب الفيديو الألعاب الإلكترونية بلايستيشن إكس بوكس بي سي", "en": "video game industry releases PlayStation Xbox PC gaming esports"},
    "sports": {"ar": "أخبار الرياضة العالمية كرة القدم السلة التنس الفورمولا", "en": "world sports football basketball tennis motorsport athletics"},
    "science": {"ar": "أخبار العلوم الفضاء الطب البيئة الاكتشافات العلمية", "en": "science research space environment health discoveries"},
    "culture": {"ar": "أخبار الثقافة والفنون والسينما والموسيقى والكتب", "en": "culture arts film music books museums entertainment"},
    "world": {"ar": "أخبار العالم الدولية والمجتمعات والكوارث والإنجازات", "en": "world international news society environment humanitarian"},
}

DIRECT_RSS_FEEDS = {
    "politics": [
        ("BBC News Politics", "https://feeds.bbci.co.uk/news/politics/rss.xml", "en"),
        ("Al Jazeera English", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
        ("France 24 Arabic", "https://www.france24.com/ar/rss", "ar"),
        ("BBC Arabic", "https://feeds.bbci.co.uk/arabic/rss.xml", "ar"),
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
        ("Al Jazeera English", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "en"),
        ("Euronews", "https://www.euronews.com/rss?level=theme&name=news", "en"),
    ],
}

PUBLISHER_SEARCH_FEEDS = {
    "politics": [
        ("International news publishers", "site:reuters.com OR site:cnn.com OR site:apnews.com", "en"),
        ("Arabic political coverage", "site:alarabiya.net OR site:aljazeera.net", "ar"),
    ],
    "economy": [
        ("Global business publishers", "site:bloomberg.com OR site:wsj.com", "en"),
        ("Arabic business publishers", "site:asharqbusiness.com OR site:maaal.com", "ar"),
    ],
    "technology": [
        ("Technology publishers", "site:wired.com OR site:techcrunch.com", "en"),
    ],
    "gaming": [
        ("Gaming publishers", "site:polygon.com OR site:ign.com", "en"),
    ],
    "sports": [
        ("Sports publishers", "site:espn.com OR site:skysports.com", "en"),
    ],
    "science": [
        ("Science publishers", "site:nasa.gov OR site:livescience.com", "en"),
    ],
    "culture": [
        ("Culture publishers", "site:artsy.net", "en"),
    ],
    "world": [
        ("International news agencies", "site:cnn.com OR site:reuters.com", "en"),
    ],
}

CATEGORY_IMAGES = {key: "" for key in CATEGORY_NAMES}

SAMPLE_STORIES = [
    {
        "category": "politics", "slug": "sample-politics", "source_url": "",
        "title_ar": "كيف تساعد قراءة السياق على فهم القرارات السياسية؟",
        "title_en": "Why context matters when reading political decisions",
        "summary_ar": "فهم القرار السياسي لا يتوقف عند الإعلان عنه؛ بل يحتاج إلى النظر في الأطراف المعنية والخلفية والتصريحات الرسمية ومصادر مستقلة متعددة.",
        "summary_en": "Understanding a political decision means looking beyond the announcement to the stakeholders, background, official statements and multiple independent sources.",
        "content_ar": "تتأثر القرارات السياسية بعوامل داخلية وخارجية، ولذلك فإن قراءة العنوان وحده قد تختزل الصورة.\n\nيساعد الرجوع إلى الوثائق والتصريحات الأصلية، ومقارنة التغطيات المستقلة، على تكوين فهم أكثر توازناً.",
        "content_en": "Political decisions are shaped by domestic and international factors, so a headline alone rarely tells the whole story.",
    },
    {
        "category": "economy", "slug": "sample-economy", "source_url": "",
        "title_ar": "ما المؤشرات التي تساعد على قراءة اتجاه الاقتصاد؟",
        "title_en": "Which indicators help explain where an economy is heading?",
        "summary_ar": "لا يقدّم مؤشر واحد صورة كاملة عن الاقتصاد؛ فالتضخم والتوظيف والنمو والإنفاق تتكامل لرسم صورة أوسع.",
        "summary_en": "No single indicator tells the full economic story. Inflation, employment, growth and spending provide a broader view.",
        "content_ar": "تعكس المؤشرات الاقتصادية جوانب مختلفة من حياة الأفراد والشركات. فالتضخم يقيس تغير الأسعار، بينما يوضح التوظيف سوق العمل.",
        "content_en": "Economic indicators describe different parts of life for households and businesses.",
    },
    {
        "category": "technology", "slug": "sample-technology", "source_url": "",
        "title_ar": "كيف يتغيّر العمل مع تطور أدوات الذكاء الاصطناعي؟",
        "title_en": "How are AI tools changing the way people work?",
        "summary_ar": "تساعد الأدوات الذكية في بعض مهام البحث والكتابة والتحليل، لكن التحقق البشري وحماية البيانات تبقى ضرورية.",
        "summary_en": "AI tools can assist with research, writing and analysis, while human review and data protection remain essential.",
        "content_ar": "يمكن للأنظمة الذكية تسريع مهام متكررة أو المساعدة في تنظيم المعلومات، لكنها قد تنتج أخطاء أو معلومات غير مكتملة.",
        "content_en": "AI systems can speed up repetitive tasks and help organise information, but they can also produce errors.",
    },
    {
        "category": "gaming", "slug": "sample-gaming", "source_url": "",
        "title_ar": "ما الذي يصنع تجربة لعب جيدة إلى جانب الرسومات؟",
        "title_en": "What makes a great game beyond its graphics?",
        "summary_ar": "تتشكّل تجربة اللعب من تصميم المراحل والاستجابة والتحكم والإيقاع وإمكانية الوصول، وليس من جودة الصورة وحدها.",
        "summary_en": "A game's experience depends on level design, responsiveness, controls, pacing and accessibility—not graphics alone.",
        "content_ar": "قد تجذب الرسومات الانتباه أولاً، لكن تفاعل اللاعب مع الأنظمة والتحديات هو ما يحدد استمرار المتعة.",
        "content_en": "Graphics may attract attention, but player interaction with systems determines enjoyment.",
    },
    {
        "category": "sports", "slug": "sample-sports", "source_url": "",
        "title_ar": "كيف تضيف الأرقام بُعداً جديداً لتحليل الرياضة؟",
        "title_en": "How statistics add another layer to sports analysis",
        "summary_ar": "تساعد البيانات على فهم الأداء والأنماط، لكنها تصبح أكثر فائدة عند جمعها مع مشاهدة المباريات.",
        "summary_en": "Data can reveal performance patterns, but is most useful when combined with watching the game.",
        "content_ar": "تتيح الإحصاءات مقارنة الأداء عبر المباريات واكتشاف أنماط قد لا تظهر من الانطباع الأول.",
        "content_en": "Statistics help compare performances and reveal patterns.",
    },
    {
        "category": "science", "slug": "sample-science", "source_url": "",
        "title_ar": "لماذا تحتاج الاكتشافات العلمية إلى مراجعة وتكرار؟",
        "title_en": "Why scientific findings need review and replication",
        "summary_ar": "تُختبر قوة النتيجة العلمية عبر المنهجية الواضحة ومراجعة الأقران وإمكان تكرار التجربة.",
        "summary_en": "Scientific findings gain strength through transparent methods, peer review and replication.",
        "content_ar": "تبدأ المعرفة العلمية بسؤال ومنهج لاختبار فرضية، ثم تُعرض النتائج لتقييم باحثين آخرين.",
        "content_en": "Scientific knowledge starts with a question and a method for testing a hypothesis.",
    },
    {
        "category": "culture", "slug": "sample-culture", "source_url": "",
        "title_ar": "كيف تعيد المنصات الرقمية تشكيل الوصول إلى الثقافة؟",
        "title_en": "How digital platforms are reshaping access to culture",
        "summary_ar": "توسّع المنصات فرص اكتشاف الأعمال الفنية والمعرفية، لكنها تطرح أسئلة عن حقوق المبدعين.",
        "summary_en": "Digital platforms expand creative discovery while raising questions about creator rights.",
        "content_ar": "أتاحت المنصات للجمهور الوصول إلى الموسيقى والكتب والأفلام من أماكن متعددة.",
        "content_en": "Platforms allow audiences to discover music and books from multiple places.",
    },
    {
        "category": "world", "slug": "sample-world", "source_url": "",
        "title_ar": "خطوات بسيطة للتحقق من الأخبار المتداولة عالمياً",
        "title_en": "Practical steps for checking widely shared world news",
        "summary_ar": "تحقق من تاريخ النشر والمصدر الأصلي والصور والسياق قبل مشاركة أي خبر.",
        "summary_en": "Check publication dates, original sources, images and context before sharing.",
        "content_ar": "قد تعود صورة متداولة إلى حدث قديم أو يُقتطع تصريح من سياقه الأصلي.",
        "content_en": "A widely shared image may come from an older event or be out of context.",
    },
]

# ---------------------------------------------------------------------------
# PostgreSQL Database Setup
# ---------------------------------------------------------------------------

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
CREATE INDEX IF NOT EXISTS idx_world_pulse_published
    ON world_pulse_articles (published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_world_pulse_category
    ON world_pulse_articles (category);
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
        connection = psycopg2.connect(
            dsn,
            connect_timeout=max(3, int(os.getenv("DB_CONNECT_TIMEOUT", "5"))),
            sslmode=os.getenv("PGSSLMODE", "require"),
            application_name="world-pulse",
        )
        with _DB_LOCK:
            _DB_RETRY_AFTER = 0.0
        return connection
    except Exception as exc:
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
                       image_source, image_credit, image_credit_url, image_license_url, image_license_name, image_checked_at,
                       title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at,
                       read_minutes, original_language, is_demo
                FROM world_pulse_articles
                WHERE is_demo = FALSE
                ORDER BY published_at DESC NULLS LAST, fetched_at DESC
                LIMIT 240
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Could not read news from PostgreSQL")
        return []
    finally:
        conn.close()

def _db_search_articles(query: str, lang: str, limit: int = 80) -> list[dict[str, Any]] | None:
    terms = [t.casefold() for t in re.findall(r"[\w\u0600-\u06ff]+", query) if len(t) > 1][:8]
    if not terms:
        return []
    if not _ensure_schema():
        return None
    conn = _connect_db()
    if conn is None:
        return None
    fields = ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en", "source_name", "category")
    where_parts: list[str] = []
    params: list[Any] = []
    for term in terms:
        pattern = f"%{term.replace('%', '').replace('_', '')}%"
        where_parts.append("(" + " OR ".join(f"{field} ILIKE %s" for field in fields) + ")")
        params.extend([pattern] * len(fields))
    params.append(max(1, min(int(limit), 150)))
    sql = f"""
        SELECT slug, source_url, category, source_name, image_url,
               image_source, image_credit, image_credit_url, image_license_url, image_license_name, image_checked_at,
               title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
               published_at, fetched_at, read_minutes, original_language, is_demo
        FROM world_pulse_articles
        WHERE is_demo = FALSE AND {' AND '.join(where_parts)}
        ORDER BY published_at DESC NULLS LAST, fetched_at DESC
        LIMIT %s
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Could not search PostgreSQL articles")
        return None
    finally:
        conn.close()

def _db_last_fetched_at() -> datetime | None:
    if not _ensure_schema():
        return None
    conn = _connect_db()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(fetched_at) FROM world_pulse_articles WHERE is_demo = FALSE")
            row = cur.fetchone()
            value = row[0] if row else None
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return None
    except Exception:
        return None
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
            image_source, image_credit, image_credit_url, image_license_url, image_license_name, image_checked_at,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo
        ) VALUES (
            %(slug)s, %(source_url)s, %(category)s, %(source_name)s, %(image_url)s,
            %(image_source)s, %(image_credit)s, %(image_credit_url)s, %(image_license_url)s, %(image_license_name)s, %(image_checked_at)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s,
            %(content_ar)s, %(content_en)s, %(published_at)s, NOW(),
            %(read_minutes)s, %(original_language)s, FALSE
        )
        ON CONFLICT (source_url) DO UPDATE SET
            category = EXCLUDED.category,
            source_name = EXCLUDED.source_name,
            image_url = EXCLUDED.image_url,
            image_source = EXCLUDED.image_source,
            image_credit = EXCLUDED.image_credit,
            image_credit_url = EXCLUDED.image_credit_url,
            image_license_url = EXCLUDED.image_license_url,
            image_license_name = EXCLUDED.image_license_name,
            image_checked_at = EXCLUDED.image_checked_at,
            title_ar = CASE WHEN EXCLUDED.title_ar <> '' THEN EXCLUDED.title_ar ELSE world_pulse_articles.title_ar END,
            title_en = CASE WHEN EXCLUDED.title_en <> '' THEN EXCLUDED.title_en ELSE world_pulse_articles.title_en END,
            summary_ar = CASE WHEN EXCLUDED.summary_ar <> '' THEN EXCLUDED.summary_ar ELSE world_pulse_articles.summary_ar END,
            summary_en = CASE WHEN EXCLUDED.summary_en <> '' THEN EXCLUDED.summary_en ELSE world_pulse_articles.summary_en END,
            content_ar = EXCLUDED.content_ar,
            content_en = EXCLUDED.content_en,
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
# RSS & Gemini Editorial Processor
# ---------------------------------------------------------------------------

_REFRESH_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_REFRESHING = False
_LAST_REFRESH_ATTEMPT = 0.0
_LAST_REFRESH_SUCCESS = 0.0
_MEMORY_ARTICLES: dict[str, dict[str, Any]] = {}
_LAST_REFRESH_AT: datetime | None = None
_LAST_REFRESH_STATE = "idle"
_LAST_REFRESH_ERROR = ""

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
    return ""

def _is_allowed_image_license(license_name: str, credit: str = "") -> bool:
    value = re.sub(r"\s+", " ", _clean_text(license_name, 160)).casefold()
    if not value:
        return False
    if any(marker in value for marker in ("noncommercial", "non-commercial", "no derivatives", "no-derivatives", "all rights reserved")):
        return False
    if "public domain" in value or value.startswith("pd-") or value.startswith("cc0") or "creative commons zero" in value:
        return True
    if re.match(r"^cc by(?:\s|$)", value) and credit.strip():
        return True
    return False

def _search_commons_image(title: str, lang: str) -> dict[str, str]:
    title = _clean_text(title, 240)
    if not title:
        return {}
    params = {
        "action": "query", "generator": "search", "gsrsearch": title,
        "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": 1200,
        "format": "json", "formatversion": 2,
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    request_obj = Request(url, headers={"User-Agent": "WorldPulseNews/1.4 (safe image finder)"})
    stopwords = {"with", "from", "into", "this", "that", "news", "today", "after", "before", "over", "under", "says", "said", "report"}
    def tokens(value: str) -> set[str]:
        return {t.casefold() for t in re.findall(r"[\w\u0600-\u06ff]{3,}", value or "") if t.casefold() not in stopwords}
    title_tokens = tokens(title)
    if not title_tokens:
        return {}
    try:
        with urlopen(request_obj, timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read(1_000_000).decode("utf-8", errors="replace"))
        pages = data.get("query", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            imageinfos = page.get("imageinfo") or []
            if not imageinfos:
                continue
            info = imageinfos[0]
            if str(info.get("mime", "")).lower() not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            ext = info.get("extmetadata") or {}
            artist = _clean_text((ext.get("Artist") or {}).get("value", ""), 180)
            license_name = _clean_text((ext.get("LicenseShortName") or {}).get("value", ""), 160)
            if not _is_allowed_image_license(license_name, artist):
                continue
            image_url = info.get("thumburl") or info.get("url") or ""
            if not str(image_url).startswith("https://"):
                continue
            file_name = str(page.get("title", "")).split(":", 1)[-1].replace(" ", "_")
            page_url = "https://commons.wikimedia.org/wiki/File:" + quote(file_name)
            raw_license_url = _clean_text((ext.get("LicenseUrl") or {}).get("value", ""), 400)
            return {
                "image_url": str(image_url), "image_source": "wikimedia_relevant",
                "image_credit": artist or "Wikimedia Commons",
                "image_credit_url": page_url, "image_license_url": raw_license_url or page_url,
                "image_license_name": license_name, "image_checked_at": datetime.now(timezone.utc),
            }
    except Exception:
        pass
    return {}

def _resolve_article_image(raw: dict[str, Any]) -> dict[str, str]:
    search_title = str(raw.get("image_search_title") or raw.get("original_title") or "")
    commons = _search_commons_image(search_title, str(raw.get("original_language") or "en"))
    if commons:
        return commons
    return {
        "image_url": "", "image_source": "none", "image_credit": "",
        "image_credit_url": "", "image_license_url": "", "image_license_name": "",
        "image_checked_at": datetime.now(timezone.utc),
    }

def _parse_any_rss(feed_url: str, category: str, lang: str, default_source: str) -> tuple[str, str, list[dict[str, Any]]]:
    request_obj = Request(feed_url, headers={"User-Agent": "WorldPulseNews/1.4"})
    try:
        with urlopen(request_obj, timeout=RSS_TIMEOUT_SECONDS) as response:
            raw = response.read(2_000_000)
        feed = feedparser.parse(raw)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:12]:
            title = _clean_text(entry.get("title", ""), 350)
            url = str(entry.get("link", "")).strip()
            if not title or not url.startswith(("https://", "http://")):
                continue
            source_info = entry.get("source")
            publisher = _clean_text(source_info.get("title", ""), 120) if source_info else default_source
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            items.append({
                "category": category, "source_url": url, "source_name": publisher,
                "image_url": "", "image_source": "", "image_credit": "", "image_credit_url": "",
                "image_license_url": "", "image_checked_at": None,
                "original_title": title, "original_summary": _clean_text(summary_raw, 900),
                "published_at": _parse_published(entry), "original_language": lang,
            })
        return category, lang, items
    except Exception:
        return category, lang, []

def _collect_rss_articles() -> list[dict[str, Any]]:
    tasks = [("google", category, lang) for category in CATEGORY_NAMES for lang in ("ar", "en")]
    direct_tasks = [
        (category, source_name, feed_url, lang)
        for category, feeds in DIRECT_RSS_FEEDS.items()
        for source_name, feed_url, lang in feeds
    ]
    publisher_search_tasks = [
        (category, label, domain_query, lang)
        for category, feeds in PUBLISHER_SEARCH_FEEDS.items()
        for label, domain_query, lang in feeds
    ]
    by_category: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_NAMES}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = []
        futures.extend(pool.submit(lambda c=c, l=l: _parse_any_rss(f"https://news.google.com/rss/search?q={quote(CATEGORY_QUERIES[c][l])}&hl={'ar' if l=='ar' else 'en'}", c, l, "Google News")) for c, l in [("google", cat, lng) for cat in CATEGORY_NAMES for lng in ("ar", "en")])
        futures.extend(pool.submit(_parse_any_rss, feed_url, cat, lang, name) for cat, name, feed_url, lang in direct_tasks)
        futures.extend(pool.submit(lambda c=c, l=l, q=dq, lb=lbl: _parse_any_rss(f"https://news.google.com/rss/search?q={quote(f'({q}) {CATEGORY_QUERIES[c][l]}')}&hl={'ar' if l=='ar' else 'en'}", c, l, lb)) for cat, lbl, dq, lang in publisher_search_tasks for l in [lang] if l in ("ar", "en"))
        
        for future in as_completed(futures):
            try:
                category, _lang, items = future.result()
                if category in by_category:
                    by_category[category].extend(items)
            except Exception:
                pass

    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for category in CATEGORY_NAMES:
        candidates = sorted(by_category[category], key=lambda x: x.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
        count = 0
        for item in candidates:
            if item["source_url"] in seen_urls:
                continue
            seen_urls.add(item["source_url"])
            item["slug"] = "story-" + hashlib.sha256(item["source_url"].encode("utf-8")).hexdigest()[:18]
            selected.append(item)
            count += 1
            if count >= MAX_ARTICLES_PER_CATEGORY:
                break
    selected.sort(key=lambda x: x.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
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
        "image_url": "",
        "image_source": "none",
        "image_credit": "",
        "image_credit_url": "",
        "image_license_url": "",
        "image_license_name": "",
        "image_checked_at": None,
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
    if not raw_articles or not GEMINI_API_KEY or genai is None or types is None:
        return {}
    
    # Process in safe smaller chunks to prevent timeouts and token overflow
    result: dict[int, dict[str, str]] = {}
    chunk_size = 5
    for start_idx in range(0, len(raw_articles), chunk_size):
        chunk = raw_articles[start_idx:start_idx + chunk_size]
        payload = [
            {
                "index": start_idx + i,
                "category": article["category"],
                "title": article.get("original_title", "")[:300],
                "source": article.get("source_name", "")[:100],
                "excerpt": article.get("original_summary", "")[:800],
            }
            for i, article in enumerate(chunk)
        ]
        prompt = f"""You are the senior editorial desk for World Pulse. Provide high-value original analytical journalism in Modern Standard Arabic and neutral international English based on these inputs.
Return valid JSON with key "stories" containing a list of objects with: index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en.
VALUABLE EDITORIAL REQUIREMENTS:
- Provide rich context, background analysis, and potential implications for each story so it delivers genuine original editorial value for Google AdSense compliance.
- Do not make word-for-word copies. Write professional journalistic summaries and structured details (context, analysis, outlook).
- Plain text only, no Markdown formatting inside fields, valid JSON only.
Input JSON: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3, max_output_tokens=4000),
            )
            text = (response.text or "").strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
            parsed = json.loads(text)
            stories = parsed.get("stories", []) if isinstance(parsed, dict) else parsed
            for story in stories:
                try:
                    idx = int(story.get("index"))
                except (TypeError, ValueError):
                    continue
                if not 0 <= idx < len(raw_articles):
                    continue
                fields = {}
                for key in ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"):
                    fields[key] = _clean_text(story.get(key, ""), 4000)
                if fields.get("title_ar") and fields.get("title_en") and fields.get("summary_ar") and fields.get("summary_en"):
                    result[idx] = fields
        except Exception as exc:
            logger.warning("Gemini batch chunk processing failed: %s", exc)
            continue
    return result

def _reading_minutes(article: dict[str, Any]) -> int:
    text = " ".join(str(article.get(key, "")) for key in ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"))
    return max(1, min(20, (len(text.split()) // 400) + 1))

def _refresh_news_job() -> None:
    global _REFRESHING, _LAST_REFRESH_SUCCESS, _LAST_REFRESH_AT, _LAST_REFRESH_STATE, _LAST_REFRESH_ERROR
    try:
        with _STATE_LOCK:
            _LAST_REFRESH_STATE = "running"
            _LAST_REFRESH_ERROR = ""
        raw_articles = _collect_rss_articles()
        if not raw_articles:
            with _STATE_LOCK:
                _LAST_REFRESH_STATE = "error"
                _LAST_REFRESH_ERROR = "No RSS stories returned"
            return

        translations = _translate_batch(raw_articles)
        if not translations:
            with _STATE_LOCK:
                _LAST_REFRESH_STATE = "error"
                _LAST_REFRESH_ERROR = "Gemini returned no usable editorial stories"
            return

        ready: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_articles):
            if index in translations:
                article = _base_article(raw)
                article.update(translations[index])
                article["read_minutes"] = _reading_minutes(article)
                # Resolve image safely
                img_data = _resolve_article_image(raw)
                article.update(img_data)
                ready.append(article)
                _MEMORY_ARTICLES[article["source_url"]] = article

        saved = _db_upsert_many(ready)
        _LAST_REFRESH_SUCCESS = time.monotonic()
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "success" if saved else "memory_only"
        logger.info("News refresh complete: %s stories processed; postgres_saved=%s", len(ready), saved)
    except Exception as exc:
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "error"
        _LAST_REFRESH_ERROR = str(exc)[:300]
        logger.exception("Unexpected failure while refreshing news")
    finally:
        with _STATE_LOCK:
            _REFRESHING = False

def _maybe_start_refresh() -> None:
    global _REFRESHING, _LAST_REFRESH_ATTEMPT
    if not NEWS_AUTO_FETCH:
        return
    now = time.monotonic()
    with _STATE_LOCK:
        if _REFRESHING:
            return
        interval = NEWS_REFRESH_MINUTES * 60 if _LAST_REFRESH_SUCCESS else NEWS_RETRY_MINUTES * 60
        if _LAST_REFRESH_ATTEMPT and now - _LAST_REFRESH_ATTEMPT < min(interval, NEWS_RETRY_MINUTES * 60):
            return
        if _LAST_REFRESH_SUCCESS and now - _LAST_REFRESH_SUCCESS < interval:
            return
        _LAST_REFRESH_ATTEMPT = now
        _REFRESHING = True
    threading.Thread(target=_refresh_news_job, name="world-pulse-rss-refresh", daemon=True).start()

# ---------------------------------------------------------------------------
# Helpers & Routes
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
            "read_minutes": 1,
            "original_language": "both",
            "is_demo": True,
        })
        result.append(story)
    return result

def _normalise_summary_body(summary: str, content: str) -> str:
    summary = str(summary or "").strip()
    content = str(content or "").strip()
    if not content:
        return ""
    if content.casefold() == summary.casefold():
        return ""
    return content

def _normalise_story(row: dict[str, Any], lang: str) -> dict[str, Any]:
    story = dict(row)
    story.setdefault("source_name", "")
    story.setdefault("image_url", "")
    story.setdefault("is_demo", False)
    if story.get("is_demo"):
        story["source_name"] = UI_TEXT[lang]["sample_source"]
    story["title"] = story.get(f"title_{lang}") or ""
    story["summary"] = story.get(f"summary_{lang}") or ""
    story["content"] = _normalise_summary_body(story["summary"], story.get(f"content_{lang}") or "")
    story["category_label"] = CATEGORY_NAMES.get(story.get("category", "world"), CATEGORY_NAMES["world"])[lang]
    story["published_label"] = _format_date(story.get("published_at"), lang)
    story["read_minutes"] = max(1, int(story.get("read_minutes") or 1))
    if not story.get("slug"):
        story["slug"] = "story-" + hashlib.sha256(story.get("source_url", "").encode("utf-8")).hexdigest()[:18]
    return story

def _all_live_articles() -> list[dict[str, Any]]:
    rows = _db_fetch_all()
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("source_url") or row.get("slug") or "")
        if key:
            by_url[key] = row
    for key, row in _MEMORY_ARTICLES.items():
        by_url[key] = row
    result = list(by_url.values())
    result.sort(key=lambda x: x.get("published_at") or x.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result

def _get_display_stories(lang: str) -> list[dict[str, Any]]:
    live = [row for row in _all_live_articles() if row.get(f"title_{lang}") and row.get("category") in CATEGORY_NAMES]
    live_categories = {row.get("category") for row in live}
    supplements = [row for row in _sample_articles() if row.get("category") not in live_categories]
    combined = live + supplements
    combined.sort(key=lambda x: x.get("published_at") or x.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return [_normalise_story(row, lang) for row in combined]

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
    except Exception:
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

def _contact_csrf_token() -> str:
    token = session.get("contact_csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        session["contact_csrf_token"] = token
    return str(token)

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
        "ai_ask_enabled": AI_QUESTIONS_ENABLED and bool(GEMINI_API_KEY) and genai is not None and types is not None,
        "now_year": datetime.now(TIMEZONE).year,
        "contact_email": CONTACT_EMAIL,
        "contact_smtp_enabled": bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD),
        "contact_csrf_token": _contact_csrf_token(),
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

@app.get("/search")
def search():
    lang = current_language()
    query = _clean_text(request.args.get("q", ""), 160)
    results: list[dict[str, Any]] = []
    db_rows = _db_search_articles(query, lang) if query else []
    if db_rows is not None:
        results = [_normalise_story(row, lang) for row in db_rows if row.get(f"title_{lang}")]
        existing = {story.get("source_url") for story in results}
        terms = [t.casefold() for t in re.findall(r"[\w\u0600-\u06ff]+", query) if len(t) > 1]
        for row in _MEMORY_ARTICLES.values():
            if row.get("source_url") in existing or not row.get(f"title_{lang}"):
                continue
            story = _normalise_story(row, lang)
            haystack = " ".join(str(story.get(key, "")) for key in ("title", "summary", "content", "source_name")).casefold()
            if terms and all(term in haystack for term in terms):
                results.append(story)
        results.sort(key=lambda x: x.get("published_at") or x.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    else:
        all_stories = _get_display_stories(lang)
        terms = [term.casefold() for term in re.findall(r"[\w\u0600-\u06ff]+", query) if len(term) > 1]
        if terms:
            for story in all_stories:
                haystack = " ".join(str(story.get(key, "")) for key in ("title", "summary", "content", "source_name")).casefold()
                if all(term in haystack for term in terms):
                    results.append(story)
    return render_template("index.html", page="search", stories=results, search_query=query,
        all_story_count=len(results), active_category="all", breaking_story=None,
        related_stories=[], article=None)

LEGAL_PAGES = {
    "privacy": {
        "ar": ("سياسة الخصوصية", "في نبض العالم (World Pulse)، نحترم خصوصيتك ونلتزم بحمايتها. نعالج المعلومات التي ترسلها طوعاً عبر نموذج التواصل، بالإضافة إلى البيانات التقنية الضرورية لتشغيل الموقع بأمان. إذا استخدمت ميزة (اسأل الذكاء الاصطناعي)، يُرسل سؤالك والسياق التحريري للخبر إلى Google Gemini لتوليد الرد بدقة. للتواصل بشأن الخصوصية: syfsywf86@gmail.com."),
        "en": ("Privacy Policy", "World Pulse respects your privacy. We process voluntarily submitted contact info and operational technical data. When using Ask AI, your question and story context are sent to Google Gemini. Contact: syfsywf86@gmail.com.")
    },
    "terms": {
        "ar": ("شروط الاستخدام", "يقدم موقع نبض العالم عناوين الأخبار وملخصات تحريرية وروابط لمصادرها الأصلية. استخدامك للموقع يشير إلى موافقتك على شروط الاستخدام وسياسة الخصوصية. لأية استفسارات أو ملاحظات حقوقية: syfsywf86@gmail.com."),
        "en": ("Terms of Service", "World Pulse provides news headlines, editorial summaries, and source links. Usage implies agreement with terms. Contact: syfsywf86@gmail.com.")
    },
    "about": {
        "ar": ("من نحن", "نبض العالم (World Pulse) منصة إخبارية رقمية تغطي المستجدات العالمية في السياسة، الاقتصاد، التكنولوجيا، الجيمنج، الرياضة، العلوم، الثقافة، وأخبار العالم. نسعى لتقديم رؤية سريعة وتحليل عميق يربط الزترك بالأحداث. للتواصل: syfsywf86@gmail.com."),
        "en": ("About Us", "World Pulse is a digital news platform covering global developments across politics, economy, tech, gaming, sports, science, culture, and world news. Contact: syfsywf86@gmail.com.")
    },
}

def _render_legal_page(slug: str):
    if slug not in {*LEGAL_PAGES, "contact"}:
        abort(404)
    lang = current_language()
    if slug == "contact":
        title = "اتصل بنا" if lang == "ar" else "Contact Us"
        body = "نرحب بملاحظاتكم واستفساراتكم عبر البريد الرسمي: syfsywf86@gmail.com." if lang == "ar" else "We welcome your feedback via official email: syfsywf86@gmail.com."
    else:
        title, body = LEGAL_PAGES[slug][lang]
    return render_template("index.html", page="legal", legal_slug=slug, legal_title=title, legal_body=body,
        contact_status=request.args.get("status", ""), stories=[], all_story_count=0, active_category="all",
        breaking_story=None, related_stories=[], article=None)

@app.get("/page/<slug>")
def legal_page(slug: str):
    return _render_legal_page(slug)

@app.get("/privacy-policy")
def privacy_policy_alias():
    return redirect(url_for("legal_page", slug="privacy", lang=current_language()), code=301)

@app.get("/terms-of-service")
def terms_alias():
    return redirect(url_for("legal_page", slug="terms", lang=current_language()), code=301)

@app.get("/about-us")
def about_alias():
    return redirect(url_for("legal_page", slug="about", lang=current_language()), code=301)

@app.get("/contact")
def contact_page():
    return _render_legal_page("contact")

@app.post("/contact")
def contact_submit():
    lang = current_language()
    submitted_token = str(request.form.get("csrf_token", ""))
    expected_token = str(session.get("contact_csrf_token", ""))
    if not submitted_token or not expected_token or not secrets.compare_digest(submitted_token, expected_token):
        return redirect(url_for("contact_page", lang=lang, status="invalid") + "#contact-form")
    name = _clean_text(request.form.get("name", ""), 100)
    email = _clean_text(request.form.get("email", ""), 160)
    message = _clean_text(request.form.get("message", ""), 3000)
    if not name or not email or not message or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return redirect(url_for("contact_page", lang=lang, status="invalid") + "#contact-form")

    body_text = f"World Pulse contact form\n\nName: {name}\nEmail: {email}\n\nMessage:\n{message}"
    if SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD:
        try:
            mail = EmailMessage()
            mail["Subject"] = "World Pulse website contact"
            mail["From"] = SMTP_FROM_EMAIL or SMTP_USERNAME
            mail["To"] = CONTACT_EMAIL
            mail["Reply-To"] = email
            mail.set_content(body_text)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as smtp:
                if SMTP_USE_TLS:
                    smtp.starttls()
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(mail)
            return redirect(url_for("contact_page", lang=lang, status="sent") + "#contact-form")
        except Exception:
            logger.exception("Could not send contact form email")
            return redirect(url_for("contact_page", lang=lang, status="failed") + "#contact-form")

    subject = quote("World Pulse contact from " + name)
    mail_body = quote(f"Name: {name}\nEmail: {email}\n\n{message}")
    return redirect(f"mailto:{CONTACT_EMAIL}?subject={subject}&body={mail_body}")

@app.get("/robots.txt")
def robots_txt():
    lines = ["User-agent: *", "Allow: /", f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml"]
    return app.response_class("\n".join(lines) + "\n", mimetype="text/plain")

@app.get("/sitemap.xml")
def sitemap_xml():
    from xml.sax.saxutils import escape
    base = request.url_root.rstrip("/")
    urls = [
        base + url_for("index", lang="ar"),
        base + url_for("index", lang="en"),
        base + url_for("legal_page", slug="privacy", lang="ar"),
        base + url_for("legal_page", slug="terms", lang="ar"),
        base + url_for("legal_page", slug="about", lang="ar"),
        base + url_for("contact_page", lang="ar"),
    ]
    for row in _all_live_articles()[:240]:
        slug = row.get("slug")
        if not slug:
            continue
        for lang_code in ("ar", "en"):
            if row.get(f"title_{lang_code}"):
                urls.append(base + url_for("article", slug=slug, lang=lang_code))
    unique_urls = list(dict.fromkeys(urls))
    xml_body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml_body += "".join(f"<url><loc>{escape(item)}</loc></url>" for item in unique_urls)
    xml_body += "</urlset>"
    return app.response_class(xml_body, mimetype="application/xml")

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

_AI_ASK_LOCK = threading.Lock()
_AI_ASK_CACHE: dict[str, tuple[float, str]] = {}
_AI_ASK_REQUESTS: dict[str, list[float]] = {}

@app.post("/api/ask")
def ask_article_ai():
    if not AI_QUESTIONS_ENABLED or not GEMINI_API_KEY or genai is None or types is None:
        return jsonify({"error": "disabled"}), 503
    payload = request.get_json(silent=True) or {}
    slug = str(payload.get("slug", ""))[:100]
    lang = str(payload.get("lang", "ar")).lower()
    question = _clean_text(payload.get("question", ""), 500)
    if lang not in {"ar", "en"}:
        lang = "ar"
    if not slug or not question or len(question) < 2:
        return jsonify({"error": "question_required"}), 400
    story = _find_article(slug, lang)
    if not story or story.get("is_demo"):
        return jsonify({"error": "story_unavailable"}), 404

    cache_key = hashlib.sha256(f"{slug}|{lang}|{question}".encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _AI_ASK_LOCK:
        cached = _AI_ASK_CACHE.get(cache_key)
        if cached and now - cached[0] < 1800:
            return jsonify({"answer": cached[1], "cached": True}), 200
        visitor_id = session.get("ai_visitor_id")
        if not visitor_id:
            visitor_id = secrets.token_urlsafe(18)
            session["ai_visitor_id"] = visitor_id
        requests_for_visitor = [t for t in _AI_ASK_REQUESTS.get(visitor_id, []) if now - t < 3600]
        if len(requests_for_visitor) >= AI_QUESTIONS_PER_HOUR:
            return jsonify({"error": "rate_limit"}), 429
        requests_for_visitor.append(now)
        _AI_ASK_REQUESTS[visitor_id] = requests_for_visitor

    title = str(story.get("title", ""))[:500]
    summary = str(story.get("summary", ""))[:1600]
    body = str(story.get("content", ""))[:3500]
    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=json.dumps({"title": title, "summary": summary, "details": body, "question": question}, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are the article explainer for World Pulse. Answer in 2-4 concise sentences, ideally under 90 words, "
                    "using only the provided context. Answer in Modern Standard Arabic if requested."
                ),
                temperature=0.2,
                max_output_tokens=220,
            ),
        )
        answer = html.unescape(str(response.text or "")).strip()
        answer = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", answer, flags=re.I).strip()
        if not answer:
            raise ValueError("Empty answer")
        with _AI_ASK_LOCK:
            _AI_ASK_CACHE[cache_key] = (time.monotonic(), answer)
        return jsonify({"answer": answer, "cached": False}), 200
    except Exception as exc:
        logger.warning("Article Q&A failed: %s", exc)
        return jsonify({"error": "upstream_error"}), 502

@app.get("/api/news-status")
def news_status():
    persisted_at = _db_last_fetched_at()
    last_refresh_at = persisted_at or _LAST_REFRESH_AT
    return jsonify({
        "running": bool(_REFRESHING),
        "state": _LAST_REFRESH_STATE,
        "last_refresh_at": last_refresh_at.isoformat() if last_refresh_at else None,
        "interval_minutes": NEWS_REFRESH_MINUTES,
        "error": _LAST_REFRESH_ERROR,
    }), 200

@app.post("/api/refresh")
def refresh_news_api():
    global _REFRESHING, _LAST_REFRESH_ATTEMPT, _LAST_REFRESH_STATE
    now = time.monotonic()
    with _STATE_LOCK:
        if _REFRESHING:
            return jsonify({"state": "running"}), 202
        if _LAST_REFRESH_ATTEMPT and now - _LAST_REFRESH_ATTEMPT < 20:
            return jsonify({"state": "cooldown"}), 429
        _LAST_REFRESH_ATTEMPT = now
        _REFRESHING = True
        _LAST_REFRESH_STATE = "running"
    threading.Thread(target=_refresh_news_job, name="world-pulse-manual-refresh", daemon=True).start()
    return jsonify({"state": "started"}), 202

@app.get("/healthz")
def healthz():
    return {"status": "ok", "database_configured": bool(_database_url()), "gemini_configured": bool(GEMINI_API_KEY)}, 200

@app.errorhandler(404)
def not_found(_error):
    lang = current_language()
    return render_template("index.html", page="404", stories=[], all_story_count=0,
                           active_category="all", breaking_story=None, related_stories=[], article=None), 404

if __name__ == "__main__":
    if "--refresh-news" in sys.argv:
        with _STATE_LOCK:
            _REFRESHING = True
            _LAST_REFRESH_ATTEMPT = time.monotonic()
        _refresh_news_job()
        raise SystemExit(0 if _LAST_REFRESH_STATE in {"success", "memory_only"} else 1)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
