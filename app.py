"""World Pulse / نبض العالم
A small Flask news portal with RSS ingestion, optional Gemini bilingual editing,
PostgreSQL persistence, and a strict rule that only real, source-attributed stories are displayed.

Render start command:
    gunicorn --workers 2 --threads 4 --timeout 90 app:app
"""
from __future__ import annotations

import calendar
import difflib
import hashlib
import html
import json
import logging
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from email.message import EmailMessage
import smtplib
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote, urlparse
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT_SECONDS = max(8, min(45, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))))
AI_QUESTIONS_ENABLED = os.getenv("AI_QUESTIONS_ENABLED", "true").lower() not in {"0", "false", "no"}
AI_QUESTIONS_PER_HOUR = max(1, min(20, int(os.getenv("AI_QUESTIONS_PER_HOUR", "5"))))
AI_ANSWER_MAX_TOKENS = max(80, min(500, int(os.getenv("AI_ANSWER_MAX_TOKENS", "350"))))
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "syfsywf86@gmail.com").strip() or "syfsywf86@gmail.com"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MAX_ARTICLES_PER_REFRESH = max(8, min(40, int(os.getenv("MAX_ARTICLES_PER_REFRESH", "24"))))
MAX_ARTICLES_PER_CATEGORY = max(1, min(8, int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "4"))))
IMAGE_SEARCH_TIMEOUT_SECONDS = max(3, min(12, int(os.getenv("IMAGE_SEARCH_TIMEOUT_SECONDS", "5"))))
MAX_IMAGE_LOOKUPS_PER_REFRESH = max(0, min(40, int(os.getenv("MAX_IMAGE_LOOKUPS_PER_REFRESH", "16"))))
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
IMAGE_CACHE_MAX_AGE_SECONDS = max(3600, int(os.getenv("IMAGE_CACHE_MAX_AGE_HOURS", "168")) * 3600)
TRUSTED_REUSABLE_IMAGE_SOURCES = {
    "wikimedia_relevant", "unsplash_api", "pexels_api", "presskit_approved"
}

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
        "footer": "التغطية بوضوح. والسياق قبل الضجيج.",
        "empty": "لا توجد أخبار مكتملة متاحة في هذا القسم حالياً.",
        "empty_detail": "لن نعرض مقالات تجريبية بدل الأخبار الحقيقية.",
        "ai_note": "أُعدّت هذه المادة التحريرية بمساعدة الذكاء الاصطناعي بالاستناد إلى المعلومات المتاحة من المصدر.",
        "brief_note": "هذا موجز أولي من عنوان الخبر ومعلومات موجزة متاحة في RSS.",
        "live": "تغطية الأخبار",
        "hero_title": "العالم يتغيّر. ابقَ على نبضه.",
        "hero_text": "أخبار من السياسة الاقتصاد والتكنولوجيا والرياضة والثقافة.",
        "search_hint": "استكشف الأخبار حسب القسم",
        "published": "نُشر",
        "open_source": "متابعة الخبر لدى المصدر",
        "theme_toggle": "تغيير المظهر",
        "refresh_news": "تحديث الأخبار",
        "refreshing": "جارٍ التحديث…",
        "auto_refresh": "تحديث تلقائي كل {minutes} دقيقة",
        "last_updated": "آخر تحديث",
        "refresh_cooldown": "تم طلب تحديث مؤخراً؛ انتظر قليلاً ثم حاول مجدداً.",
        "refresh_error": "تعذّر إكمال التحديث.",
        "article_details": "تفاصيل الخبر",
        "photo_credit": "الصورة",
        "photo_license": "الترخيص",
        "photo_provider": "المصدر",
        "illustrative_image": "صورة توضيحية",
        "body_unavailable": "لا تتوفر تفاصيل إضافية موثوقة في المادة المتاحة.",
        "sample_badge": "محتوى توضيحي — ليس خبراً حياً",
        "ai_ask_title": "اسأل الذكاء الاصطناعي عن الخبر",
        "ai_ask_desc": "اسأل عن الخلفية أو المصطلحات أو أهمية الخبر.",
        "ai_question_placeholder": "مثلاً: لماذا يُعد هذا الخبر مهماً؟",
        "ai_ask_button": "اسأل نبض العالم",
        "ai_thinking": "جارٍ إعداد الإجابة…",
        "ai_disabled": "الإجابة داخل الموقع تحتاج تفعيل مفتاح Gemini.",
        "ai_error": "لم نتمكن من إعداد إجابة الآن.",
        "ai_rate_limit": "وصلت إلى الحد المؤقت للأسئلة.",
        "ai_disclaimer": "إجابة آلية للتوضيح.",
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
        "footer": "Clarity in coverage. Context before noise.",
        "empty": "No complete news stories are available in this section right now.",
        "empty_detail": "We do not replace real news with demo articles.",
        "ai_note": "This original editorial report was prepared with AI assistance.",
        "brief_note": "This is a preliminary headline brief.",
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
        "refresh_cooldown": "A refresh was requested recently. Please wait a moment.",
        "refresh_error": "The refresh could not be completed.",
        "article_details": "Story details",
        "photo_credit": "Photo",
        "photo_license": "License",
        "photo_provider": "Image provider",
        "illustrative_image": "Illustrative image",
        "body_unavailable": "The available source material does not support additional detail.",
        "sample_badge": "EXPLANATORY SAMPLE — NOT LIVE NEWS",
        "ai_ask_title": "Ask AI about this story",
        "ai_ask_desc": "Ask about the background, terminology, or why this story matters.",
        "ai_question_placeholder": "For example: Why does this story matter?",
        "ai_ask_button": "Ask World Pulse",
        "ai_thinking": "Preparing an answer…",
        "ai_disabled": "In-site answers require a Gemini API key.",
        "ai_error": "We could not prepare an answer right now.",
        "ai_rate_limit": "You have reached the temporary question limit.",
        "ai_disclaimer": "AI-generated explanation.",
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

# Expanded major Arabic and English news source domains per category
CATEGORY_SOURCE_DOMAINS = {
    "politics": {
        "ar": ["aljazeera.net", "alarabiya.net", "skynewsarabia.com", "aawsat.com", "alquds.co.uk", "arabic.cnn.com"],
        "en": ["bbc.com", "reuters.com", "apnews.com", "cnn.com", "politico.com"],
    },
    "economy": {
        "ar": ["asharqbusiness.com", "cnbcarabia.com", "maaal.com", "mubasher.info", "alarabiya.net"],
        "en": ["bloomberg.com", "cnbc.com", "ft.com", "wsj.com", "reuters.com"],
    },
    "technology": {
        "ar": ["aitnews.com", "tech-wd.com", "arabhardware.net"],
        "en": ["techcrunch.com", "theverge.com", "wired.com", "arstechnica.com"],
    },
    "gaming": {
        "ar": ["saudigamer.com", "arabhardware.net"],
        "en": ["ign.com", "gamespot.com", "eurogamer.net", "polygon.com", "pcgamer.com"],
    },
    "sports": {
        "ar": ["filgoal.com", "kooora.com", "beinsports.com"],
        "en": ["espn.com", "skysports.com", "bbc.com", "reuters.com"],
    },
    "science": {
        "ar": ["ngalarabiya.com", "aljazeera.net", "alarabiya.net"],
        "en": ["nasa.gov", "space.com", "scientificamerican.com", "livescience.com"],
    },
    "culture": {
        "ar": ["alqafilah.com", "aljazeera.net", "alaraby.co.uk", "alarab.co.uk"],
        "en": ["lithub.com", "artsy.net", "theguardian.com"],
    },
    "world": {
        "ar": ["france24.com", "bbc.com", "dw.com", "aljazeera.net", "euronews.com"],
        "en": ["euronews.com", "bbc.com", "apnews.com", "reuters.com"],
    },
}

CATEGORY_MATCH_TERMS = {
    "politics": [
        "سياسة", "سياسي", "الحكومة", "حكوم", "الانتخابات", "انتخاب", "برلمان", "رئيس الوزراء", "دبلوماس", "وزير", "عقوبات", "سفارة", "politics", "political", "election", "government", "parliament", "diplomacy", "minister", "president", "sanctions", "senate", "congress", "policy",
    ],
    "economy": [
        "اقتصاد", "اقتصادي", "أسهم", "اسهم", "أسواق", "اسواق", "سوق", "بنك", "مصرف", "شركة", "شركات", "أرباح", "ارباح", "استثمار", "استثمارات", "تضخم", "نفط", "تداول", "مالية", "اقتصادية", "الطاقة", "تكاليف", "ميزان تجاري", "فائض", "عجز", "صادرات", "واردات", "economy", "economic", "market", "markets", "stock", "stocks", "shares", "finance", "business", "investor", "company", "earnings", "investment", "inflation", "interest rate", "oil prices", "energy", "trade balance", "trade deficit", "exports", "imports", "banking", "revenue",
    ],
    "technology": [
        "تكنولوجيا", "تقنية", "الذكاء الاصطناعي", "ذكاء اصطناعي", "هاتف", "آيفون", "ايفون", "أندرويد", "اندرويد", "برمجيات", "سيبراني", "اختراق", "رقائق", "معالج", "حاسوب", "تطبيق", "شبكة", "technology", "tech", "artificial intelligence", " AI ", "software", "hardware", "smartphone", "cybersecurity", "chip", "processor", "app launch", "startup", "cloud computing",
    ],
    "gaming": [
        "ألعاب الفيديو", "لعبة", "ألعاب", "بلايستيشن", "بلاي ستيشن", "إكس بوكس", "اكس بوكس", "ستيم", "نينتندو", "تحديث اللعبة", "game", "games", "gaming", "playstation", "xbox", "nintendo", "steam", "gta 6", "gta vi", "pc gamer", "esports", "videogame", "video game", "gamepass", "game pass",
    ],
    "sports": [
        "رياضة", "رياضي", "كرة القدم", "مباراة", "مباريات", "دوري", "كأس", "هدف", "أهداف", "منتخب", "بطولة", "انتقالات", "لاعب", "كرة السلة", "تنس", "فورمولا", "sports", "football", "soccer", "match", "league", "cup", "goal", "player", "transfer", "basketball", "tennis", "formula 1", "championship", "olympics",
    ],
    "science": [
        "علوم", "علمي", "علمية", "ناسا", "فضاء", "فضائي", "فلك", "كوكب", "تلسكوب", "اكتشاف علمي", "بحث علمي", "دراسة علمية", "علماء", "مريخ", "قمر", "science", "scientific", "nasa", "space", "astronomy", "planet", "telescope", "research", "discovery", "scientist", "mars", "moon", "physics", "biology",
    ],
    "culture": [
        "ثقافة", "ثقافي", "أدب", "أدبي", "كتاب", "رواية", "فيلم", "سينما", "مسرح", "موسيقى", "فنون", "فن", "معرض", "متحف", "مهرجان", "شاعر", "قصيدة", "culture", "literary", "literature", "book", "novel", "film", "movie", "cinema", "theatre", "theater", "music", "arts", "art exhibition", "museum", "festival", "poet", "fiction",
    ],
}

def _classify_story(title: str, summary: str, fallback_category: str, source_domain: str = "") -> str:
    text = " " + _clean_text(f"{title} {summary}", 1100).casefold() + " "
    scores: dict[str, float] = {key: 0.0 for key in CATEGORY_NAMES}
    for category, terms in CATEGORY_MATCH_TERMS.items():
        for term in terms:
            needle = term.casefold().strip()
            if needle == "ai":
                if re.search(r"\bai\b", text):
                    scores[category] += 1.1
            elif re.fullmatch(r"[a-z0-9]+", needle):
                if re.search(r"\b" + re.escape(needle) + r"\b", text):
                    scores[category] += 1.0
            elif needle and needle in text:
                scores[category] += 1.0 if " " not in needle else 1.4

    domain = (source_domain or "").casefold().removeprefix("www.")
    domain_categories: dict[str, set[str]] = {}
    for cat, language_map in CATEGORY_SOURCE_DOMAINS.items():
        for domains in language_map.values():
            for candidate in domains:
                domain_categories.setdefault(candidate, set()).add(cat)
    for candidate, cats in domain_categories.items():
        if len(cats) == 1 and _domain_matches(domain, candidate):
            scores[next(iter(cats))] += 2.0
            break
    best = max(scores, key=scores.get)
    fallback_score = scores.get(fallback_category, 0.0)
    if best != fallback_category and scores[best] >= 1.8 and scores[best] >= fallback_score + 1.2:
        return best
    if fallback_category in CATEGORY_NAMES:
        return fallback_category
    return best if scores[best] > 0 else "world"

LICENSE_REQUIRED_DOMAINS = {
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "techcrunch.com",
    "espn.com", "sciencedaily.com", "theguardian.com", "aljazeera.net",
    "aljazeera.com",
}
CONTENT_LICENSE_APPROVED_DOMAINS = {
    part.strip().lower().removeprefix("www.")
    for part in os.getenv("CONTENT_LICENSE_APPROVED_DOMAINS", "").split(",")
    if part.strip()
}

def _domain_matches(host: str, domain: str) -> bool:
    host = (host or "").casefold().rstrip(".").removeprefix("www.")
    domain = (domain or "").casefold().rstrip(".").removeprefix("www.")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))

def _domain_is_approved(domain: str) -> bool:
    return any(_domain_matches(domain, approved) for approved in CONTENT_LICENSE_APPROVED_DOMAINS)

def _domain_needs_license(domain: str) -> bool:
    return any(_domain_matches(domain, restricted) for restricted in LICENSE_REQUIRED_DOMAINS) and not _domain_is_approved(domain)

LICENSE_REQUIRED_SOURCE_NAMES = (
    "bbc", "reuters", "associated press", "ap news", "techcrunch", "espn", "sciencedaily",
    "science daily", "the guardian", "al jazeera",
)

def _publisher_requires_license(source_name: str = "", source_urls: tuple[str, ...] = ()) -> bool:
    hosts = []
    for candidate in source_urls:
        try:
            hosts.append((urlparse(candidate).hostname or "").casefold().rstrip(".").removeprefix("www."))
        except ValueError:
            continue
    if any(host and _domain_is_approved(host) for host in hosts):
        return False
    if any(host and _domain_needs_license(host) for host in hosts):
        return True
    name = re.sub(r"\s+", " ", (source_name or "").casefold()).strip()
    return any(term in name for term in LICENSE_REQUIRED_SOURCE_NAMES)

CATEGORY_IMAGES = {category: "" for category in CATEGORY_NAMES}
LEGACY_IMAGE_URLS = set()

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_DB_RETRY_AFTER = 0.0
_DB_LOCK = threading.Lock()
_CONTROL_CACHE: dict[str, tuple[bool, float]] = {}
_CONTROL_CACHE_LOCK = threading.Lock()

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
    image_provider_url TEXT NOT NULL DEFAULT '',
    image_license_url TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS world_pulse_controls (
    control_key TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def _database_url() -> str:
    return (os.getenv("SUPABASE_POOLER_URL") or os.getenv("DATABASE_URL") or "").strip()

def _news_setup_issues() -> list[str]:
    issues: list[str] = []
    if not GEMINI_API_KEY:
        issues.append("Missing GEMINI_API_KEY in Render Environment")
    elif genai is None or types is None:
        issues.append("Gemini SDK unavailable; check requirements.txt and redeploy")
    if not _database_url():
        issues.append("Missing SUPABASE_POOLER_URL or DATABASE_URL in Render Environment")
    return issues

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
        logger.warning("Database connection unavailable: %s", exc)
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

def _control_enabled(control_key: str, default: bool = True) -> bool:
    now = time.monotonic()
    with _CONTROL_CACHE_LOCK:
        cached = _CONTROL_CACHE.get(control_key)
        if cached and cached[1] > now:
            return cached[0]
    if not _ensure_schema():
        return default
    conn = _connect_db()
    if conn is None:
        return default
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT enabled FROM world_pulse_controls WHERE control_key = %s", (control_key,))
            row = cur.fetchone()
            value = bool(row[0]) if row else default
            with _CONTROL_CACHE_LOCK:
                _CONTROL_CACHE[control_key] = (value, time.monotonic() + 20)
            return value
    except Exception:
        return default
    finally:
        conn.close()

def _set_control_enabled(control_key: str, enabled: bool) -> bool:
    if not _ensure_schema():
        return False
    conn = _connect_db()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO world_pulse_controls(control_key, enabled, updated_at)
                VALUES (%s, %s, NOW()) ON CONFLICT(control_key) DO UPDATE
                SET enabled = EXCLUDED.enabled, updated_at = NOW()""", (control_key, enabled))
        conn.commit()
        with _CONTROL_CACHE_LOCK:
            _CONTROL_CACHE[control_key] = (enabled, time.monotonic() + 20)
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def _known_source_controls() -> list[dict[str, str]]:
    rows = []
    for category, langs in CATEGORY_SOURCE_DOMAINS.items():
        for lang, domains in langs.items():
            for domain in domains:
                key = f"news:{category}:{lang}:{domain}"
                rows.append({"key": key, "type": "news", "category": category, "lang": lang, "name": domain, "default": "true", "license_required": any(domain == blocked or domain.endswith("." + blocked) for blocked in LICENSE_REQUIRED_DOMAINS)})
    for provider, title in [("wikimedia_relevant", "Wikimedia Commons"), ("presskit_approved", "Approved press kits"), ("pexels_api", "Pexels API"), ("unsplash_api", "Unsplash API")]:
        rows.append({"key": f"image:{provider}", "type": "image", "category": "images", "lang": "all", "name": title, "default": "true"})
    return rows

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
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_checked_at,
                       title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at,
                       read_minutes, original_language, is_demo
                FROM world_pulse_articles
                WHERE is_demo = FALSE
                  AND LENGTH(TRIM(COALESCE(content_ar, ''))) >= 220
                  AND LENGTH(TRIM(COALESCE(content_en, ''))) >= 220
                ORDER BY published_at DESC NULLS LAST, fetched_at DESC
                LIMIT 120
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _db_search_articles(query: str, limit: int = 60) -> list[dict[str, Any]] | None:
    query = _clean_text(query, 160)
    terms = [term for term in re.findall(r"[\w\u0600-\u06ff]+", query) if len(term) > 1][:8]
    if not terms:
        return []
    if not _ensure_schema():
        return None
    conn = _connect_db()
    if conn is None:
        return None
    conditions = []
    params: list[Any] = []
    fields = ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en", "source_name", "category")
    for term in terms:
        conditions.append("(" + " OR ".join(f"COALESCE({field}, '') ILIKE %s" for field in fields) + ")")
        like_value = "%" + term.replace("%", "\\%").replace("_", "\\_") + "%"
        params.extend([like_value] * len(fields))
    sql = """
        SELECT slug, source_url, category, source_name, image_url,
               image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_checked_at,
               title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
               published_at, fetched_at, read_minutes, original_language, is_demo
        FROM world_pulse_articles
        WHERE is_demo = FALSE
          AND LENGTH(TRIM(COALESCE(content_ar, ''))) >= 220
          AND LENGTH(TRIM(COALESCE(content_en, ''))) >= 220
          AND """ + " AND ".join(conditions) + " ORDER BY published_at DESC NULLS LAST, fetched_at DESC LIMIT %s"
    params.append(max(1, min(100, int(limit))))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return None
    finally:
        conn.close()

def _db_fetch_articles_needing_editorial(limit: int = 4) -> list[dict[str, Any]]:
    if not GEMINI_API_KEY or genai is None or types is None or not _ensure_schema():
        return []
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT slug, source_url, category, source_name, image_url,
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_checked_at,
                       title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at,
                       read_minutes, original_language, is_demo
                FROM world_pulse_articles
                WHERE is_demo = FALSE
                  AND source_url <> ''
                  AND (COALESCE(title_ar, '') <> '' OR COALESCE(title_en, '') <> '')
                  AND (
                    LENGTH(TRIM(COALESCE(content_ar, ''))) < 250
                    OR LENGTH(TRIM(COALESCE(content_en, ''))) < 250
                    OR TRIM(COALESCE(content_ar, '')) = TRIM(COALESCE(summary_ar, ''))
                    OR TRIM(COALESCE(content_en, '')) = TRIM(COALESCE(summary_en, ''))
                  )
                ORDER BY published_at DESC NULLS LAST, fetched_at DESC
                LIMIT %s
            """, (max(1, min(8, int(limit))),))
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _raw_from_stored_article(row: dict[str, Any]) -> dict[str, Any]:
    original_language = row.get("original_language", "en")
    if original_language not in {"ar", "en"}:
        original_language = "ar" if _looks_arabic(row.get("title_ar", "")) else "en"
    title = row.get(f"title_{original_language}") or row.get("title_en") or row.get("title_ar") or ""
    summary = row.get(f"summary_{original_language}") or row.get("summary_en") or row.get("summary_ar") or ""
    return {
        "slug": row.get("slug") or _slug_for_url(row.get("source_url", "")),
        "source_url": row.get("source_url", ""),
        "category": row.get("category", "world"),
        "source_name": row.get("source_name", ""),
        "image_url": row.get("image_url", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "",
        "image_source": row.get("image_source", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "none",
        "image_credit": row.get("image_credit", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "",
        "image_credit_url": row.get("image_credit_url", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "",
        "image_provider_url": row.get("image_provider_url", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "",
        "image_license_url": row.get("image_license_url", "") if row.get("image_source") in TRUSTED_REUSABLE_IMAGE_SOURCES else "",
        "image_checked_at": row.get("image_checked_at"),
        "original_title": title,
        "original_summary": summary,
        "original_language": original_language,
        "published_at": row.get("published_at"),
        "_database_backfill": True,
    }

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
            image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_checked_at,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo
        ) VALUES (
            %(slug)s, %(source_url)s, %(category)s, %(source_name)s, %(image_url)s,
            %(image_source)s, %(image_credit)s, %(image_credit_url)s, %(image_provider_url)s, %(image_license_url)s, %(image_checked_at)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s, %(content_ar)s, %(content_en)s,
            %(published_at)s, NOW(),
            %(read_minutes)s, %(original_language)s, FALSE
        )
        ON CONFLICT (source_url) DO UPDATE SET
            category = EXCLUDED.category,
            source_name = EXCLUDED.source_name,
            image_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_url
                ELSE EXCLUDED.image_url END,
            image_source = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_source
                ELSE EXCLUDED.image_source END,
            image_credit = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_credit
                ELSE EXCLUDED.image_credit END,
            image_credit_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_credit_url
                ELSE EXCLUDED.image_credit_url END,
            image_provider_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_provider_url
                ELSE EXCLUDED.image_provider_url END,
            image_license_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_source IN ('wikimedia_relevant', 'unsplash_api', 'pexels_api', 'presskit_approved') AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_license_url
                ELSE EXCLUDED.image_license_url END,
            image_checked_at = COALESCE(EXCLUDED.image_checked_at, world_pulse_articles.image_checked_at),
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

_IMAGE_STOPWORDS = {
    "with", "from", "into", "this", "that", "news", "today", "after", "before", "over", "under",
    "says", "said", "report", "reports", "update", "latest", "breaking", "world", "international",
    "about", "could", "would", "amid", "their", "what", "when", "where", "will", "been", "have",
    "أخبار", "العالم", "اليوم", "هذا", "هذه", "بعد", "قبل", "على", "إلى", "عن", "مع", "في", "من",
    "يقول", "قال", "تقرير", "تطورات", "عاجل", "الجديد", "التي", "الذي", "خلال", "حول", "بعدما",
}

def _image_tokens(value: str) -> set[str]:
    return {t.casefold() for t in re.findall(r"[\w\u0600-\u06ff]{3,}", value or "") if t.casefold() not in _IMAGE_STOPWORDS}

def _image_match_score(title: str, description: str) -> float:
    title_tokens = _image_tokens(title)
    if not title_tokens:
        return 0.0
    image_tokens = _image_tokens(description)
    overlap_count = len(title_tokens & image_tokens)
    required = 1 if len(title_tokens) <= 4 else 2
    overlap_ratio = overlap_count / max(1, len(title_tokens))
    if overlap_count < required or overlap_ratio < 0.12:
        return 0.0
    return overlap_ratio + min(overlap_count, 4) * 0.025

def _https_url(value: Any, allowed_hosts: set[str] | None = None) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold().rstrip(".")
    if allowed_hosts and not any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
        return ""
    return url

def _search_commons_image(title: str, lang: str) -> dict[str, str]:
    title = _clean_text(title, 240)
    if not title:
        return {}
    params = {
        "action": "query", "generator": "search", "gsrsearch": title,
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": 1400,
        "format": "json", "formatversion": 2,
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    request_obj = Request(url, headers={"User-Agent": "WorldPulseNews/1.3 (news image finder; Wikimedia Commons API)"})
    title_tokens = _image_tokens(title)
    if not title_tokens:
        return {}
    try:
        with urlopen(request_obj, timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read(1_800_000).decode("utf-8", errors="replace"))
        pages = data.get("query", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        best: tuple[float, dict[str, str]] | None = None
        for page in pages:
            imageinfos = page.get("imageinfo") or []
            if not imageinfos:
                continue
            info = imageinfos[0]
            mime = str(info.get("mime", "")).lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            page_title = str(page.get("title", ""))
            if re.search(r"(?i)\b(logo|icon|wordmark|commons-logo|flag icon|map icon)\b", page_title):
                continue
            ext = info.get("extmetadata") or {}
            license_short = _clean_text((ext.get("LicenseShortName") or {}).get("value", ""), 100).casefold()
            license_url = _https_url(html.unescape((ext.get("LicenseUrl") or {}).get("value", "")), {"creativecommons.org"})
            license_url_path = urlparse(license_url).path.casefold() if license_url else ""
            is_cc0_url = bool(re.search(r"/publicdomain/zero/1\.0/?$", license_url_path))
            is_pd_url = bool(re.search(r"/publicdomain/mark/1\.0/?$", license_url_path))
            is_cc_by_url = bool(re.search(r"/licenses/by/(?:2\.0|3\.0|4\.0)/?$", license_url_path))
            license_ok = is_pd_url or is_cc0_url or is_cc_by_url
            forbidden = any(term in license_short for term in ("noncommercial", "non-commercial", "no derivatives", "no-derivatives", "by-nc", "by-nd", "by-sa", "share alike"))
            artist = _clean_text((ext.get("Artist") or {}).get("value", ""), 180)
            if is_cc_by_url and not artist:
                continue
            if not license_ok or forbidden:
                continue
            image_url = _https_url(info.get("thumburl") or info.get("url"), {"wikimedia.org", "wikipedia.org"})
            if not image_url:
                continue
            desc = _clean_text((ext.get("ImageDescription") or {}).get("value", ""), 1000)
            score = _image_match_score(title, page_title + " " + desc)
            if score <= 0:
                continue
            file_page_url = "https://commons.wikimedia.org/wiki/" + quote(page_title.replace(" ", "_"), safe=":_()!,.'-")
            credit = artist or "Public-domain image via Wikimedia Commons"
            result = {
                "image_url": image_url,
                "image_source": "wikimedia_relevant",
                "image_credit": credit,
                "image_credit_url": file_page_url,
                "image_provider_url": file_page_url,
                "image_license_url": license_url,
                "image_checked_at": datetime.now(timezone.utc),
            }
            if best is None or score > best[0]:
                best = (score, result)
        return best[1] if best else {}
    except Exception:
        return {}

def _search_pexels_image(title: str) -> dict[str, str]:
    if not PEXELS_API_KEY or not title:
        return {}
    query = _clean_text(title, 100)
    params = urlencode({"query": query, "per_page": 10, "orientation": "landscape"})
    request_obj = Request(
        "https://api.pexels.com/v1/search?" + params,
        headers={"Authorization": PEXELS_API_KEY, "User-Agent": "WorldPulseNews/1.3 (+image sourcing)"},
    )
    try:
        with urlopen(request_obj, timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read(1_500_000).decode("utf-8", errors="replace"))
        best: tuple[float, dict[str, str]] | None = None
        for photo in data.get("photos", [])[:10]:
            src = photo.get("src") or {}
            image_url = _https_url(src.get("large") or src.get("large2x") or src.get("medium"), {"pexels.com"})
            photo_page = _https_url(photo.get("url"), {"pexels.com"})
            photographer = _clean_text(photo.get("photographer", ""), 160)
            photographer_url = _https_url(photo.get("photographer_url"), {"pexels.com"})
            if not image_url or not photo_page or not photographer:
                continue
            score = _image_match_score(title, " ".join([str(photo.get("alt", "")), photographer]))
            if score <= 0:
                continue
            result = {
                "image_url": image_url,
                "image_source": "pexels_api",
                "image_credit": photographer,
                "image_credit_url": photographer_url or photo_page,
                "image_provider_url": photo_page,
                "image_license_url": "https://www.pexels.com/license/",
                "image_checked_at": datetime.now(timezone.utc),
            }
            if best is None or score > best[0]:
                best = (score, result)
        return best[1] if best else {}
    except Exception:
        return {}

def _with_unsplash_tracking(url: Any) -> str:
    safe = _https_url(url, {"unsplash.com"})
    if not safe:
        return ""
    parsed = urlparse(safe)
    query = parsed.query
    additions = "utm_source=world_pulse&utm_medium=referral"
    if "utm_source=" not in query:
        query = query + ("&" if query else "") + additions
    return parsed._replace(query=query).geturl()

def _search_unsplash_image(title: str) -> dict[str, str]:
    if not UNSPLASH_ACCESS_KEY or not title:
        return {}
    params = urlencode({"query": _clean_text(title, 100), "per_page": 10, "orientation": "landscape", "content_filter": "high"})
    request_obj = Request(
        "https://api.unsplash.com/search/photos?" + params,
        headers={
            "Authorization": "Client-ID " + UNSPLASH_ACCESS_KEY,
            "Accept-Version": "v1",
            "User-Agent": "WorldPulseNews/1.3 (+image sourcing)",
        },
    )
    try:
        with urlopen(request_obj, timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read(1_500_000).decode("utf-8", errors="replace"))
        best: tuple[float, dict[str, str]] | None = None
        for photo in data.get("results", [])[:10]:
            urls = photo.get("urls") or {}
            image_url = _https_url(urls.get("regular") or urls.get("small"), {"images.unsplash.com"})
            links = photo.get("links") or {}
            user = photo.get("user") or {}
            user_links = user.get("links") or {}
            photo_page = _with_unsplash_tracking(links.get("html"))
            photographer = _clean_text(user.get("name", ""), 160)
            photographer_url = _with_unsplash_tracking(user_links.get("html"))
            if not image_url or not photo_page or not photographer:
                continue
            description = " ".join([
                str(photo.get("alt_description", "")), str(photo.get("description", "")),
                " ".join(_clean_text(tag.get("title", ""), 80) for tag in photo.get("tags", [])[:12] if isinstance(tag, dict)),
            ])
            score = _image_match_score(title, description)
            if score <= 0:
                continue
            result = {
                "image_url": image_url,
                "image_source": "unsplash_api",
                "image_credit": photographer,
                "image_credit_url": photographer_url or photo_page,
                "image_provider_url": photo_page,
                "image_license_url": "https://unsplash.com/license",
                "image_checked_at": datetime.now(timezone.utc),
            }
            if best is None or score > best[0]:
                best = (score, result)
        return best[1] if best else {}
    except Exception:
        return {}

def _search_approved_presskit_image(title: str, category: str) -> dict[str, str]:
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "approved_presskit_images.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            entries = json.load(manifest_file)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(entries, list):
        return {}
    best: tuple[float, dict[str, str]] | None = None
    for entry in entries[:500]:
        if not isinstance(entry, dict) or entry.get("approved_for_commercial_use") is not True:
            continue
        if entry.get("category") not in (None, "", category):
            continue
        image_url = _https_url(entry.get("image_url"))
        image_page = _https_url(entry.get("image_page_url"))
        credit = _clean_text(entry.get("credit", ""), 160)
        credit_url = _https_url(entry.get("credit_url")) or image_page
        license_url = _https_url(entry.get("license_url"))
        license_name = _clean_text(entry.get("license_name", ""), 180)
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        keyword_text = " ".join(_clean_text(term, 80) for term in keywords[:30])
        description = _clean_text(entry.get("description", ""), 500)
        if not (image_url and image_page and credit and license_url and license_name and keyword_text):
            continue
        score = _image_match_score(title, keyword_text + " " + description)
        if score <= 0:
            continue
        result = {
            "image_url": image_url,
            "image_source": "presskit_approved",
            "image_credit": credit,
            "image_credit_url": credit_url,
            "image_provider_url": image_page,
            "image_license_url": license_url,
            "image_checked_at": datetime.now(timezone.utc),
        }
        if best is None or score > best[0]:
            best = (score, result)
    return best[1] if best else {}

def _search_any_reusable_image(title: str, lang: str = "en", category: str = "world") -> dict[str, str]:
    finders = (
        ("image:wikimedia_relevant", lambda: _search_commons_image(title, lang)),
        ("image:presskit_approved", lambda: _search_approved_presskit_image(title, category)),
        ("image:pexels_api", lambda: _search_pexels_image(title)),
        ("image:unsplash_api", lambda: _search_unsplash_image(title)),
    )
    for control_key, finder in finders:
        if not _control_enabled(control_key, True):
            continue
        result = finder()
        if result:
            return result
    return {}

def _resolve_article_image(raw: dict[str, Any]) -> dict[str, Any]:
    existing = str(raw.get("image_url") or "").strip()
    source = str(raw.get("image_source") or "")
    if (existing and source in TRUSTED_REUSABLE_IMAGE_SOURCES and existing not in LEGACY_IMAGE_URLS
            and _control_enabled(f"image:{source}", True)):
        checked = raw.get("image_checked_at")
        if isinstance(checked, str):
            try:
                checked = datetime.fromisoformat(checked.replace("Z", "+00:00"))
            except ValueError:
                checked = None
        if isinstance(checked, datetime) and checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        if isinstance(checked, datetime) and (datetime.now(timezone.utc) - checked.astimezone(timezone.utc)).total_seconds() < IMAGE_CACHE_MAX_AGE_SECONDS:
            return {
                "image_url": existing,
                "image_source": source,
                "image_credit": raw.get("image_credit") or "",
                "image_credit_url": raw.get("image_credit_url") or "",
                "image_provider_url": raw.get("image_provider_url") or "",
                "image_license_url": raw.get("image_license_url") or "",
                "image_checked_at": checked,
            }

    search_title = _clean_text(raw.get("image_search_title") or raw.get("original_title") or "", 240)
    if search_title:
        result = _search_any_reusable_image(search_title, str(raw.get("original_language") or "en"), str(raw.get("category") or "world"))
        if result:
            result["image_checked_at"] = datetime.now(timezone.utc)
            return result

    return {
        "image_url": "",
        "image_source": "none",
        "image_credit": "",
        "image_credit_url": "",
        "image_provider_url": "",
        "image_license_url": "",
        "image_checked_at": datetime.now(timezone.utc),
    }

def _enrich_article_images(raw_articles: list[dict[str, Any]]) -> None:
    known_images: dict[str, dict[str, Any]] = {}
    try:
        for row in _db_fetch_all():
            if row.get("source_url"):
                known_images[str(row["source_url"])] = row
    except Exception:
        pass
    for row in _MEMORY_ARTICLES.values():
        if row.get("source_url"):
            known_images.setdefault(str(row["source_url"]), row)

    skip_image_lookup: set[str] = set()
    now_utc = datetime.now(timezone.utc)
    for item in raw_articles:
        source_url = str(item.get("source_url") or "")
        input_source = str(item.get("image_source") or "")
        input_checked = item.get("image_checked_at")
        if isinstance(input_checked, str):
            try:
                input_checked = datetime.fromisoformat(input_checked.replace("Z", "+00:00"))
            except ValueError:
                input_checked = None
        if isinstance(input_checked, datetime) and input_checked.tzinfo is None:
            input_checked = input_checked.replace(tzinfo=timezone.utc)
        if (input_source in TRUSTED_REUSABLE_IMAGE_SOURCES and _control_enabled(f"image:{input_source}", True)
                and item.get("image_url") and isinstance(input_checked, datetime)
                and (now_utc - input_checked.astimezone(timezone.utc)).total_seconds() < IMAGE_CACHE_MAX_AGE_SECONDS):
            continue

        item.update({
            "image_url": "", "image_source": "none", "image_credit": "",
            "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
        })
        cached = known_images.get(source_url)
        cached_source = str((cached or {}).get("image_source") or "")
        if (cached and cached.get("image_url") and cached_source in TRUSTED_REUSABLE_IMAGE_SOURCES
                and _control_enabled(f"image:{cached_source}", True)):
            checked = cached.get("image_checked_at")
            if isinstance(checked, str):
                try:
                    checked = datetime.fromisoformat(checked.replace("Z", "+00:00"))
                except ValueError:
                    checked = None
            if isinstance(checked, datetime) and checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if isinstance(checked, datetime) and (now_utc - checked.astimezone(timezone.utc)).total_seconds() < IMAGE_CACHE_MAX_AGE_SECONDS:
                for key in ("image_url", "image_source", "image_credit", "image_credit_url", "image_provider_url", "image_license_url", "image_checked_at"):
                    if cached.get(key) not in (None, ""):
                        item[key] = cached[key]
                continue

    pending = [
        item for item in raw_articles
        if not item.get("image_url") and str(item.get("source_url") or "") not in skip_image_lookup
    ][:MAX_IMAGE_LOOKUPS_PER_REFRESH]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_resolve_article_image, item): item for item in pending}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item.update(future.result())
            except Exception:
                item.update({
                    "image_url": "", "image_source": "none", "image_credit": "",
                    "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
                    "image_checked_at": datetime.now(timezone.utc),
                })

def _parse_any_rss(feed_url: str, category: str, lang: str, default_source: str) -> tuple[str, str, list[dict[str, Any]]]:
    request_obj = Request(feed_url, headers={"User-Agent": "WorldPulseNews/1.2 (+RSS news reader)"})
    try:
        with urlopen(request_obj, timeout=RSS_TIMEOUT_SECONDS) as response:
            raw = response.read(2_000_000)
        feed = feedparser.parse(raw)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:18]:
            title = _clean_text(entry.get("title", ""), 350)
            url = str(entry.get("link", "")).strip()
            if not title or not url.startswith(("https://", "http://")):
                continue
            source_info = entry.get("source")
            publisher = _clean_text(source_info.get("title", ""), 120) if source_info else ""
            source_href = ""
            if source_info:
                source_href = str(source_info.get("href") or source_info.get("url") or "").strip()
            if not publisher:
                continue
            if _publisher_requires_license(publisher, (url, source_href)):
                continue
            publisher_host = (urlparse(source_href or url).hostname or "").casefold().removeprefix("www.")
            disabled_domain = False
            for domain in CATEGORY_SOURCE_DOMAINS.get(category, {}).get(lang, []):
                if publisher_host == domain or publisher_host.endswith("." + domain):
                    if not _control_enabled(f"news:{category}:{lang}:{domain}", True):
                        disabled_domain = True
                        break
            if disabled_domain:
                continue
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            if not summary_raw and entry.get("content"):
                summary_raw = entry.get("content", [{}])[0].get("value", "")
            publisher_host = (urlparse(source_href or url).hostname or "").casefold().removeprefix("www.")
            items.append({
                "category": category, "source_url": url, "source_name": publisher, "source_domain": publisher_host,
                "image_url": "", "image_source": "none", "image_credit": "",
                "image_credit_url": "", "image_provider_url": "", "image_license_url": "", "image_checked_at": None,
                "original_title": title, "original_summary": _clean_text(summary_raw, 320),
                "published_at": _parse_published(entry), "original_language": lang,
            })
        return category, lang, items
    except Exception:
        return category, lang, []

def _parse_feed_task(category: str, lang: str, source_focus: bool = False) -> tuple[str, str, list[dict[str, Any]]]:
    query = CATEGORY_QUERIES[category][lang]
    if source_focus:
        domains = CATEGORY_SOURCE_DOMAINS.get(category, {}).get(lang, [])
        domains = [domain for domain in domains
                   if _control_enabled(f"news:{category}:{lang}:{domain}", True)
                   and not _domain_needs_license(domain)]
        if domains:
            domain_query = " OR ".join(f"site:{domain}" for domain in domains)
            query = f"({query}) ({domain_query})"
    if lang == "ar":
        locale = {"hl": "ar", "gl": "JO", "ceid": "JO:ar"}
    else:
        locale = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    params = {"q": query, **locale}
    feed_url = "https://news.google.com/rss/search?" + urlencode(params)
    label = "Google News RSS · targeted source discovery" if source_focus else "Google News RSS · broad discovery"
    return _parse_any_rss(feed_url, category, lang, label)

def _slug_for_url(url: str) -> str:
    return "story-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:18]

def _collect_rss_articles() -> list[dict[str, Any]]:
    tasks = [
        (category, lang, source_focus)
        for category in CATEGORY_NAMES
        for lang in ("ar", "en")
        for source_focus in (False, True)
    ]
    by_category: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_NAMES}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(_parse_feed_task, category, lang, source_focus)
                   for category, lang, source_focus in tasks]
        for future in as_completed(futures):
            try:
                requested_category, _lang, items = future.result()
                for item in items:
                    actual_category = _classify_story(
                        item.get("original_title", ""), item.get("original_summary", ""), requested_category,
                        item.get("source_domain", "")
                    )
                    item["category"] = actual_category
                    by_category[actual_category].append(item)
            except Exception:
                pass

    cleaned: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_NAMES}
    seen_urls: set[str] = set()
    fingerprints: list[str] = []
    for category in CATEGORY_NAMES:
        candidates = sorted(by_category[category],
                            key=lambda item: item.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
                            reverse=True)
        for item in candidates:
            url = item["source_url"]
            if url in seen_urls:
                continue
            title_key = re.sub(r"[^\w\u0600-\u06ff]+", " ", item.get("original_title", "").casefold()).strip()
            title_key = re.sub(r"\s+", " ", title_key)
            if len(title_key) > 25 and any(difflib.SequenceMatcher(None, title_key, old).ratio() >= 0.91 for old in fingerprints[-160:]):
                continue
            seen_urls.add(url)
            if title_key:
                fingerprints.append(title_key)
            item["slug"] = _slug_for_url(url)
            cleaned[category].append(item)

    selected: list[dict[str, Any]] = []
    for round_index in range(MAX_ARTICLES_PER_CATEGORY):
        for category in CATEGORY_NAMES:
            candidates = cleaned[category]
            if round_index < len(candidates):
                selected.append(candidates[round_index])
                if len(selected) >= MAX_ARTICLES_PER_REFRESH:
                    selected.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
                    return selected
    selected.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return selected

def _looks_arabic(value: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", value or ""))

def _base_article(raw: dict[str, Any]) -> dict[str, Any]:
    title = raw.get("original_title", "").strip()
    summary = _clean_text(raw.get("original_summary", ""), 280).strip()
    original_lang = raw.get("original_language", "ar" if _looks_arabic(title) else "en")
    return {
        "slug": raw["slug"],
        "source_url": raw["source_url"],
        "category": raw["category"],
        "source_name": raw.get("source_name") or "",
        "image_url": raw.get("image_url") or "",
        "image_source": raw.get("image_source") or ("none" if not raw.get("image_url") else "publisher_rss"),
        "image_credit": raw.get("image_credit", ""),
        "image_credit_url": raw.get("image_credit_url", ""),
        "image_provider_url": raw.get("image_provider_url", ""),
        "image_license_url": raw.get("image_license_url", ""),
        "image_checked_at": raw.get("image_checked_at"),
        "title_ar": title if original_lang == "ar" else "",
        "title_en": title if original_lang == "en" else "",
        "summary_ar": summary if original_lang == "ar" else "",
        "summary_en": summary if original_lang == "en" else "",
        "content_ar": "",
        "content_en": "",
        "published_at": raw.get("published_at"),
        "read_minutes": 1,
        "original_language": original_lang,
        "is_demo": False,
        "fetched_at": datetime.now(timezone.utc),
    }

def _translate_batch(raw_articles: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    if not raw_articles or not GEMINI_API_KEY or genai is None or types is None:
        return {}

    result: dict[int, dict[str, str]] = {}
    batch_size = 4
    client = None

    for batch_start in range(0, len(raw_articles), batch_size):
        batch_end = min(len(raw_articles), batch_start + batch_size)
        payload = [
            {
                "index": i,
                "category": raw_articles[i].get("category", "world"),
                "source": raw_articles[i].get("source_name", "")[:120],
                "source_url": raw_articles[i].get("source_url", "")[:500],
                "headline": raw_articles[i].get("original_title", "")[:350],
                "rss_excerpt": raw_articles[i].get("original_summary", "")[:500],
                "source_language": raw_articles[i].get("original_language", "en"),
            }
            for i in range(batch_start, batch_end)
        ]
        prompt = f'''You are the bilingual editorial desk of World Pulse. Create an original, attributed news brief from a headline and a short RSS discovery excerpt.
Return valid JSON only: {{"stories":[...]}}. Each story must use the original integer index and exactly these fields: index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en.
Stories to edit: {json.dumps(payload, ensure_ascii=False)}'''
        try:
            if client is None:
                client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.25,
                    max_output_tokens=6144,
                ),
            )
            response_text = (response.text or "").strip()
            response_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.I)
            parsed = json.loads(response_text)
            stories = parsed.get("stories", []) if isinstance(parsed, dict) else parsed
            if not isinstance(stories, list):
                raise ValueError("Gemini returned unexpected structure")
            for story in stories:
                if not isinstance(story, dict):
                    continue
                try:
                    index = int(story.get("index"))
                except (TypeError, ValueError):
                    continue
                if not batch_start <= index < batch_end:
                    continue
                fields: dict[str, str] = {}
                for key in ("title_ar", "title_en", "summary_ar", "summary_en"):
                    fields[key] = _clean_text(story.get(key, ""), 1800)
                for key in ("content_ar", "content_en"):
                    body = html.unescape(str(story.get(key, "") or ""))
                    body = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
                    body = re.sub(r"<[^>]+>", " ", body)
                    body = re.sub(r"[ \t]+", " ", body)
                    body = re.sub(r" *\n *", "\n", body)
                    body = re.sub(r"\n{3,}", "\n\n", body).strip()
                    fields[key] = body[:12000]
                required = ("title_ar", "title_en", "summary_ar", "summary_en")
                if (all(fields.get(key) for key in required)
                        and len(fields.get("content_ar", "")) >= 220
                        and len(fields.get("content_en", "")) >= 220):
                    result[index] = fields
        except Exception:
            continue
    return result

def _reading_minutes(article: dict[str, Any]) -> int:
    text = " ".join(str(article.get(key, "")) for key in (
        "title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"
    ))
    words = len(text.split())
    return max(1, min(20, (words // 400) + 1))

def _avoid_repeated_news_photos(raw_articles: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    alt_lookups = 0
    max_alternative_lookups = min(2, MAX_IMAGE_LOOKUPS_PER_REFRESH // 4)
    ordered = sorted(
        raw_articles,
        key=lambda item: item.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    for item in ordered:
        image_url = str(item.get("image_url") or "")
        if not image_url:
            continue
        parsed = urlparse(image_url)
        identity = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}" if parsed.netloc else image_url
        if identity not in seen:
            seen.add(identity)
            continue

        alternative: dict[str, str] = {}
        if alt_lookups < max_alternative_lookups:
            alt_lookups += 1
            query = str(item.get("image_search_title") or item.get("original_title") or "")
            alternative = _search_any_reusable_image(query, str(item.get("original_language") or "en"), str(item.get("category") or "world"))
        candidate_url = str(alternative.get("image_url") or "")
        candidate = urlparse(candidate_url)
        candidate_identity = f"{candidate.scheme.lower()}://{candidate.netloc.lower()}{candidate.path.rstrip('/')}" if candidate.netloc else candidate_url
        if candidate_url and candidate_identity not in seen:
            item.update(alternative)
            seen.add(candidate_identity)
        else:
            item.update({
                "image_url": "",
                "image_source": "duplicate_removed",
                "image_credit": "",
                "image_credit_url": "",
                "image_provider_url": "",
                "image_license_url": "",
                "image_checked_at": datetime.now(timezone.utc),
            })

def _refresh_news_job() -> None:
    global _REFRESHING, _LAST_REFRESH_SUCCESS, _LAST_REFRESH_AT, _LAST_REFRESH_STATE, _LAST_REFRESH_ERROR
    try:
        with _STATE_LOCK:
            _LAST_REFRESH_STATE = "running"
            _LAST_REFRESH_ERROR = ""

        schema_available = _ensure_schema()
        raw_articles = _collect_rss_articles()
        known_urls = {str(item.get("source_url", "")) for item in raw_articles}
        if schema_available:
            for stored in _db_fetch_articles_needing_editorial(limit=4):
                source_url = str(stored.get("source_url", ""))
                if source_url and source_url not in known_urls:
                    raw_articles.append(_raw_from_stored_article(stored))
                    known_urls.add(source_url)

        if not raw_articles:
            raise RuntimeError("No eligible RSS stories were returned.")

        translations = _translate_batch(raw_articles)
        existing_urls = {str(row.get("source_url", "")) for row in _db_fetch_all()} if schema_available else set()
        existing_urls.update(str(row.get("source_url", "")) for row in _MEMORY_ARTICLES.values())
        raw_to_publish: list[tuple[int, dict[str, Any]]] = []
        for index, raw in enumerate(raw_articles):
            enriched = translations.get(index)
            source_url = str(raw.get("source_url", ""))
            if not enriched:
                if source_url not in existing_urls:
                    continue
                continue
            raw["image_search_title"] = enriched.get("title_en") or raw.get("original_title", "")
            raw_to_publish.append((index, raw))

        if not raw_to_publish:
            _LAST_REFRESH_SUCCESS = time.monotonic()
            _LAST_REFRESH_AT = datetime.now(timezone.utc)
            _LAST_REFRESH_STATE = "success"
            _LAST_REFRESH_ERROR = "No new stories to publish; existing stories were retained."
            return

        image_candidates = [raw for _index, raw in raw_to_publish]
        _enrich_article_images(image_candidates)
        _avoid_repeated_news_photos(image_candidates)

        ready: list[dict[str, Any]] = []
        for index, raw in raw_to_publish:
            article_data = _base_article(raw)
            if index in translations:
                article_data.update(translations[index])
            article_data["read_minutes"] = _reading_minutes(article_data)
            ready.append(article_data)

        saved = _db_upsert_many(ready)
        for article_data in ready:
            _MEMORY_ARTICLES[article_data["source_url"]] = article_data
        _LAST_REFRESH_SUCCESS = time.monotonic()
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "success" if saved else "memory_only"
        _LAST_REFRESH_ERROR = "" if saved else "Stories are in memory only."
    except Exception as exc:
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "error"
        _LAST_REFRESH_ERROR = str(exc)[:500]
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
    thread = threading.Thread(target=_refresh_news_job, name="world-pulse-rss-refresh", daemon=True)
    thread.start()

def _normalise_summary_body(summary: str, content: str) -> str:
    summary = str(summary or "").strip()
    content = str(content or "").strip()
    if not content:
        return ""

    def norm(value: str) -> str:
        return re.sub(r"[^\w\u0600-\u06ff]+", " ", value.casefold()).strip()

    summary_norm = norm(summary)
    content_norm = norm(content)
    if not content_norm or (summary_norm and content_norm == summary_norm):
        return ""
    if summary_norm and len(summary_norm) > 35 and content.casefold().startswith(summary.casefold()):
        content = content[len(summary):].lstrip(" \n\r—:؛.،-")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
    if len(paragraphs) == 1:
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?؟])\s+(?=[^\s])", paragraphs[0]) if part.strip()]

    summary_tokens = set(summary_norm.split())
    kept: list[str] = []
    for paragraph in paragraphs:
        paragraph_norm = norm(paragraph)
        tokens = set(paragraph_norm.split())
        if not paragraph_norm:
            continue
        if summary_norm and paragraph_norm == summary_norm:
            continue
        if summary_tokens and tokens:
            overlap = len(summary_tokens & tokens) / max(1, min(len(summary_tokens), len(tokens)))
            if overlap >= 0.88 and len(tokens) <= len(summary_tokens) * 1.35:
                continue
        kept.append(paragraph)
    result = "\n\n".join(kept).strip()
    if summary_norm and norm(result) == summary_norm:
        return ""
    return result

def _image_license_label(license_url: str, source: str = "") -> str:
    value = (license_url or "").casefold()
    if "publicdomain/zero/1.0" in value:
        return "CC0 1.0"
    if "publicdomain/mark/1.0" in value:
        return "Public Domain Mark 1.0"
    match = re.search(r"creativecommons\.org/licenses/by/(2\.0|3\.0|4\.0)", value)
    if match:
        return "CC BY " + match.group(1)
    if source == "pexels_api":
        return "Pexels License"
    if source == "unsplash_api":
        return "Unsplash License"
    if source == "presskit_approved":
        return "Approved press-kit licence"
    return ""

def _image_provider_label(source: str) -> str:
    return {
        "wikimedia_relevant": "Wikimedia Commons",
        "unsplash_api": "Unsplash",
        "pexels_api": "Pexels",
        "presskit_approved": "Approved press kit",
    }.get(source or "", "")

def _normalise_story(row: dict[str, Any], lang: str) -> dict[str, Any]:
    story = dict(row)
    story["is_demo"] = False
    story.setdefault("source_name", "")
    story.setdefault("image_url", "")
    story.setdefault("image_source", "")
    story.setdefault("image_credit", "")
    story.setdefault("image_credit_url", "")
    story.setdefault("image_provider_url", "")
    story.setdefault("image_license_url", "")
    story["image_license_name"] = _image_license_label(str(story.get("image_license_url") or ""), str(story.get("image_source") or ""))
    story["image_provider_name"] = _image_provider_label(str(story.get("image_source") or ""))
    story["title"] = story.get(f"title_{lang}") or ""
    story["summary"] = story.get(f"summary_{lang}") or ""
    raw_content = story.get(f"content_{lang}") or ""
    story["content"] = _normalise_summary_body(story["summary"], raw_content)
    story["ai_enriched"] = bool(
        len(str(story.get("title_ar") or "").strip()) > 0
        and len(str(story.get("title_en") or "").strip()) > 0
        and len(str(story.get("content_ar") or "").strip()) >= 220
        and len(str(story.get("content_en") or "").strip()) >= 220
    )
    story["category_label"] = CATEGORY_NAMES.get(story.get("category", "world"), CATEGORY_NAMES["world"])[lang]
    story["published_label"] = _format_date(story.get("published_at"), lang)
    story["read_minutes"] = max(1, int(story.get("read_minutes") or 1))
    if not story.get("slug"):
        story["slug"] = _slug_for_url(story.get("source_url", "world-pulse"))
    return story

def _all_live_articles() -> list[dict[str, Any]]:
    rows = _db_fetch_all()
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("is_demo"):
            continue
        key = str(row.get("source_url") or row.get("slug") or "")
        if key:
            by_url[key] = row
    for key, row in _MEMORY_ARTICLES.items():
        if row.get("is_demo"):
            continue
        by_url[key] = row
    result = list(by_url.values())
    result.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return result

def _get_display_stories(lang: str) -> list[dict[str, Any]]:
    live = [
        row for row in _all_live_articles()
        if not row.get("is_demo")
        and row.get("source_url")
        and row.get(f"title_{lang}")
        and row.get("category") in CATEGORY_NAMES
    ]
    live.sort(
        key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    return [_normalise_story(row, lang) for row in live]

def _find_article(slug: str, lang: str) -> dict[str, Any] | None:
    for row in _all_live_articles():
        if row.get("is_demo"):
            continue
        if row.get("slug") == slug and row.get("source_url") and row.get(f"title_{lang}"):
            return _normalise_story(row, lang)
    return None

def _format_date(value: Any, lang: str) -> str:
    if not value:
        return "التاريخ غير متاح" if lang == "ar" else "Date unavailable"
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
        "ai_ask_enabled": AI_QUESTIONS_ENABLED and bool(GEMINI_API_KEY) and genai is not None and types is not None,
        "contact_email": CONTACT_EMAIL,
        "contact_smtp_enabled": bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD")),
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

@app.get("/search")
def search():
    lang = current_language()
    query = _clean_text(request.args.get("q", ""), 160)
    results: list[dict[str, Any]] = []
    if query and len(query) >= 2:
        db_rows = _db_search_articles(query)
        if db_rows is not None:
            results = [_normalise_story(row, lang) for row in db_rows if row.get(f"title_{lang}")]
            found_urls = {str(row.get("source_url", "")) for row in results}
            terms = [term.casefold() for term in re.findall(r"[\w\u0600-\u06ff]+", query) if len(term) > 1]
            for stored in _MEMORY_ARTICLES.values():
                url = str(stored.get("source_url", ""))
                if url in found_urls or not stored.get(f"title_{lang}"):
                    continue
                story = _normalise_story(stored, lang)
                searchable = " ".join(str(story.get(key, "")) for key in ("title", "summary", "content", "source_name")).casefold()
                if terms and all(term in searchable for term in terms):
                    results.append(story)
        else:
            all_stories = _get_display_stories(lang)
            terms = [term.casefold() for term in re.findall(r"[\w\u0600-\u06ff]+", query) if len(term) > 1]
            if terms:
                results = [story for story in all_stories if all(term in " ".join(str(story.get(key, "")) for key in ("title", "summary", "content", "source_name")).casefold() for term in terms)]
        results.sort(key=lambda row: row.get("published_at") or row.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return render_template("index.html", page="search", stories=results, search_query=query,
        all_story_count=len(results), active_category="all", breaking_story=None,
        related_stories=[], article=None)

@app.get("/article/<slug>")
def article(slug: str):
    lang = current_language()
    selected = _find_article(slug, lang)
    if selected is None:
        abort(404)
    pool = _get_display_stories(lang)
    related = [story for story in pool if story.get("slug") != slug and story.get("category"] == selected.get("category")][:3]
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

def _ai_ask_cache_key(slug: str, lang: str, question: str) -> str:
    normalised = re.sub(r"\s+", " ", question.casefold()).strip()
    return hashlib.sha256(f"{slug}|{lang}|{normalised}".encode("utf-8")).hexdigest()

@app.post("/api/ask")
def ask_article_ai():
    if not AI_QUESTIONS_ENABLED or not GEMINI_API_KEY or genai is None or types is None:
        return jsonify({"error": "disabled"}), 503
    payload = request.get_json(silent=True) or {}
    slug = _clean_text(payload.get("slug", ""), 100)
    lang = str(payload.get("lang", current_language())).lower()
    question = _clean_text(payload.get("question", ""), 500)
    if lang not in {"ar", "en"}:
        lang = "ar"
    if not slug or len(question) < 2:
        return jsonify({"error": "question_required"}), 400
    story = _find_article(slug, lang)
    if not story or story.get("is_demo"):
        return jsonify({"error": "story_unavailable"}), 404

    cache_key = _ai_ask_cache_key(slug, lang, question)
    now = time.monotonic()
    with _AI_ASK_LOCK:
        cached = _AI_ASK_CACHE.get(cache_key)
        if cached and now - cached[0] < 1800:
            return jsonify({"answer": cached[1], "cached": True}), 200
        visitor_id = session.get("ai_visitor_id")
        if not visitor_id:
            visitor_id = secrets.token_urlsafe(18)
            session["ai_visitor_id"] = visitor_id
        previous = [stamp for stamp in _AI_ASK_REQUESTS.get(visitor_id, []) if now - stamp < 3600]
        if len(previous) >= AI_QUESTIONS_PER_HOUR:
            return jsonify({"error": "rate_limit"}), 429
        previous.append(now)
        _AI_ASK_REQUESTS[visitor_id] = previous

    title = str(story.get("title", ""))[:500]
    summary = str(story.get("summary", ""))[:1500]
    body = str(story.get("content", ""))[:2800]
    context_payload = {"title": title, "summary": summary, "details": body, "question": question}
    prompt = (
        "Answer in Modern Standard Arabic." if lang == "ar" else
        "Answer in clear international English."
    )
    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=json.dumps(context_payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                temperature=0.2,
                max_output_tokens=AI_ANSWER_MAX_TOKENS,
            ),
        )
        answer = html.unescape(str(response.text or "")).strip()
        answer = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", answer, flags=I if False else re.I).strip()
        if not answer:
            raise ValueError("Empty response")
        with _AI_ASK_LOCK:
            _AI_ASK_CACHE[cache_key] = (time.monotonic(), answer)
        return jsonify({"answer": answer, "cached": False}), 200
    except Exception:
        return jsonify({"error": "upstream_error"}), 502

@app.get("/api/news-status")
def news_status():
    persisted_at = _db_last_fetched_at()
    timestamps = [value for value in (persisted_at, _LAST_REFRESH_AT) if isinstance(value, datetime)]
    normalised = [value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value for value in timestamps]
    last_refresh_at = max(normalised) if normalised else None
    return jsonify({
        "running": bool(_REFRESHING),
        "state": _LAST_REFRESH_STATE,
        "last_refresh_at": last_refresh_at.isoformat() if last_refresh_at else None,
        "interval_minutes": NEWS_REFRESH_MINUTES,
        "error": _LAST_REFRESH_ERROR,
        "database_url_configured": bool(_database_url()),
        "gemini_api_key_configured": bool(GEMINI_API_KEY),
        "setup_issues": _news_setup_issues(),
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
    thread = threading.Thread(target=_refresh_news_job, name="world-pulse-manual-refresh", daemon=True)
    thread.start()
    return jsonify({"state": "started"}), 202

STATIC_PAGES = {
    "about": {
        "title_ar": "من نحن", "title_en": "About Us",
        "sections_ar": [("رسالتنا", "نبض العالم منصة إخبارية وتحليلية...")],
        "sections_en": [("Our mission", "World Pulse is a news platform...")],
    },
    "privacy": {
        "title_ar": "سياسة الخصوصية", "title_en": "Privacy Policy",
        "sections_ar": [("المعلومات", "...")],
        "sections_en": [("Information", "...")],
    },
    "terms": {
        "title_ar": "شروط الاستخدام", "title_en": "Terms of Service",
        "sections_ar": [("الاستخدام", "...")],
        "sections_en": [("Use", "...")],
    },
}

def _site_origin() -> str:
    configured = (os.getenv("SITE_URL") or request.url_root).strip().rstrip("/")
    if not configured.startswith(("https://", "http://")):
        configured = request.url_root.rstrip("/")
    return configured

@app.get("/page/<page_key>")
def static_page(page_key: str):
    page_data = STATIC_PAGES.get(page_key)
    if not page_data:
        abort(404)
    lang = current_language()
    title = page_data["title_ar" if lang == "ar" else "title_en"]
    sections = page_data["sections_ar" if lang == "ar" else "sections_en"]
    body = "\n\n".join(f"{heading}\n{paragraph}" for heading, paragraph in sections)
    return render_template(
        "index.html", page="legal", legal_slug=page_key, legal_title=title, legal_body=body,
        contact_status="", contact_csrf_token=session.get("contact_csrf", ""),
        contact_smtp_enabled=bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD")),
        stories=[], all_story_count=0, active_category="all", breaking_story=None,
        related_stories=[], article=None,
    )

@app.route("/contact", methods=["GET", "POST"])
def contact():
    lang = current_language()
    sent = False
    error = ""
    token = session.get("contact_csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["contact_csrf"] = token
    if request.method == "POST":
        if not secrets.compare_digest(str(request.form.get("csrf_token", "")), token):
            abort(400)
        name = _clean_text(request.form.get("name", ""), 100)
        email = _clean_text(request.form.get("email", ""), 254)
        message = _clean_text(request.form.get("message", ""), 5000)
        if not name or not email or not message:
            error = "error"
        else:
            sent = True
    legal_title = "اتصل بنا" if lang == "ar" else "Contact Us"
    legal_body = "البريد الرسمي للتواصل: " + CONTACT_EMAIL
    return render_template(
        "index.html", page="legal", legal_slug="contact", legal_title=legal_title, legal_body=legal_body,
        contact_status="sent" if sent else ("failed" if error else ""), contact_csrf_token=token,
        contact_smtp_enabled=False, stories=[], all_story_count=0, active_category="all",
        breaking_story=None, related_stories=[], article=None,
    ), 200

@app.get("/sitemap.xml")
def sitemap():
    origin = _site_origin()
    urls = [url_for("index", _external=False)]
    urls += [url_for("static_page", page_key=key, _external=False) for key in STATIC_PAGES]
    xml_urls = "".join(f"<url><loc>{html.escape(origin + path)}</loc></url>" for path in dict.fromkeys(urls))
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + xml_urls + '</urlset>'
    return app.response_class(body, mimetype="application/xml")

@app.get("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {_site_origin()}/sitemap.xml\n"
    return app.response_class(body, mimetype="text/plain")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200

def _admin_enabled() -> bool:
    return bool(os.getenv("ADMIN_PANEL_PASSWORD", "").strip())

def _require_admin():
    if not _admin_enabled():
        abort(404)
    if not session.get("wp_admin_authenticated"):
        return redirect(url_for("admin_login", next=request.path))
    return None

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not _admin_enabled():
        abort(404)
    error = ""
    if request.method == "POST":
        supplied = request.form.get("password", "")
        expected = os.getenv("ADMIN_PANEL_PASSWORD", "")
        if supplied and secrets.compare_digest(supplied, expected):
            session.clear()
            session["wp_admin_authenticated"] = True
            session["wp_admin_csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin_sources"))
        error = "كلمة المرور غير صحيحة"
    return render_template("admin_login.html", error=error)

@app.route("/admin/sources", methods=["GET", "POST"])
def admin_sources():
    guard = _require_admin()
    if guard is not None:
        return guard
    return render_template("admin_sources.html", controls=[], images=[], notice="", csrf_token="")

@app.errorhandler(404)
def not_found(_error):
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
