"""World Pulse / نبض العالم
A Flask news portal with allowlisted RSS discovery, optional Gemini bilingual editing,
PostgreSQL persistence, and a strict licensed-image sourcing pipeline.

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
MAX_ARTICLES_PER_REFRESH = max(8, min(40, int(os.getenv("MAX_ARTICLES_PER_REFRESH", "24"))))
MAX_ARTICLES_PER_CATEGORY = max(1, min(8, int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "4"))))
IMAGE_SEARCH_TIMEOUT_SECONDS = max(3, min(12, int(os.getenv("IMAGE_SEARCH_TIMEOUT_SECONDS", "5"))))
MAX_IMAGE_LOOKUPS_PER_REFRESH = max(0, min(40, int(os.getenv("MAX_IMAGE_LOOKUPS_PER_REFRESH", "24"))))
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
IMAGE_CACHE_MAX_AGE_SECONDS = max(3600, int(os.getenv("IMAGE_CACHE_MAX_AGE_HOURS", "168")) * 3600)
TRUSTED_REUSABLE_IMAGE_SOURCES = {"wikimedia_relevant", "unsplash_api", "pexels_api", "presskit_approved"}

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
        "photos_provided_by_pexels": "صور مقدّمة من Pexels",
        "photo_page": "صفحة الصورة",
        "illustrative_image": "صورة توضيحية",
        "empty_detail": "نعرض الأخبار الحقيقية فقط من المصادر المعتمدة. إذا لم تظهر أخبار، افتح حالة النظام لمعرفة سبب تعذّر الجلب.",
        "brief_note": "نبذة أولية من تغذية الأخبار؛ راجع المصدر الأصلي للتفاصيل الكاملة.",

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
        "photos_provided_by_pexels": "Photos provided by Pexels",
        "photo_page": "Photo page",
        "illustrative_image": "Illustrative image",
        "empty_detail": "Only real stories from approved sources are shown. If no stories appear, open system status to see why fetching may have failed.",
        "brief_note": "Preliminary brief based on a news feed; visit the original source for full details.",

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

# Publisher catalog by category and language. These domains are search preferences,
# not reuse licences. Actual results are filtered against this list before they can be saved.
CATEGORY_SOURCE_DOMAINS = {
    "politics": {
        "ar": ["aljazeera.net", "alarabiya.com", "alarabiya.net", "skynewsarabia.com", "aawsat.com", "alquds.co.uk"],
        "en": ["bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "politico.com"],
    },
    "economy": {
        "ar": ["asharqbusiness.com", "cnbcarabia.com", "mubasher.info", "alarabiya.com", "alarabiya.net"],
        "en": ["bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "reuters.com"],
    },
    "technology": {
        "ar": ["aitnews.com", "tech-wd.com", "arabhardware.net"],
        "en": ["theverge.com", "techcrunch.com", "wired.com", "arstechnica.com"],
    },
    "gaming": {
        "ar": ["saudigamer.com", "arabiangamer.net", "arabhardware.net"],
        "en": ["ign.com", "gamespot.com", "polygon.com", "pcgamer.com"],
    },
    "sports": {
        "ar": ["filgoal.com", "kooora.com", "beinsports.com"],
        "en": ["bbc.com", "bbc.co.uk", "espn.com", "skysports.com", "reuters.com"],
    },
    "science": {
        "ar": ["natgeotv.com", "aljazeera.net", "alarabiya.com", "alarabiya.net", "dw.com"],
        "en": ["nasa.gov", "space.com", "scientificamerican.com", "livescience.com"],
    },
    "culture": {
        "ar": ["alqafilah.com", "thifaf.com", "aljazeera.net", "alaraby.co.uk", "alarab.co.uk"],
        "en": ["lithub.com", "artsy.net", "theguardian.com"],
    },
    "world": {
        "ar": ["france24.com", "bbc.com", "bbc.co.uk", "dw.com", "aljazeera.net", "euronews.com"],
        "en": ["euronews.com", "bbc.com", "bbc.co.uk", "apnews.com", "reuters.com"],
    },
}

# Conservative site policy: block these publishers until their current terms and the intended
# commercial/AI use have been checked and any required permission has been obtained.
# Add a domain to PUBLISHER_LICENSED_DOMAINS only after that review/permission.
LICENSE_REQUIRED_DOMAINS = {
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "techcrunch.com",
    "espn.com", "sciencedaily.com", "theguardian.com", "aljazeera.net", "aljazeera.com",
    "bloomberg.com", "ft.com", "wsj.com", "alarabiya.com", "alarabiya.net",
}
LICENSE_REQUIRED_SOURCE_NAMES = (
    "bbc", "reuters", "associated press", "ap news", "techcrunch", "espn",
    "science daily", "sciencedaily", "the guardian", "al jazeera", "bloomberg",
    "financial times", "wall street journal", "alarabiya", "al arabiya",
)
GOOGLE_NEWS_HOSTS = {"news.google.com", "news.googleusercontent.com"}


def _url_host(value: str) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _domain_matches_host(host: str, domain: str) -> bool:
    host = (host or "").lower().rstrip(".")
    domain = (domain or "").lower().strip().lstrip(".").rstrip(".")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _configured_licensed_domains() -> set[str]:
    """Explicit operator override; use only for publishers with permission/licensing."""
    raw = os.getenv("PUBLISHER_LICENSED_DOMAINS", "")
    domains: set[str] = set()
    for token in re.split(r"[,;\s]+", raw):
        token = token.strip()
        if not token:
            continue
        host = _url_host(token if "://" in token else "https://" + token) or token.lower().strip(".")
        if host:
            domains.add(host)
    return domains


def _domain_requires_license(host: str) -> bool:
    """Keep commercial-reuse-gated publishers blocked unless the exact root domain is licensed."""
    configured = _configured_licensed_domains()
    host = (host or "").lower().rstrip(".")
    for restricted in LICENSE_REQUIRED_DOMAINS:
        if _domain_matches_host(host, restricted):
            # The override must be the exact root domain, e.g. bbc.com; a broad parent
            # like "com" or a different licensed publisher can never unlock this source.
            return restricted not in configured
    return False


def _effective_source_domains(category: str, lang: str) -> list[str]:
    domains = CATEGORY_SOURCE_DOMAINS.get(category, {}).get(lang, [])
    return [domain for domain in domains if not _domain_requires_license(domain)]


LICENSED_NAME_DOMAIN_MAP = {
    "bbc": ("bbc.com", "bbc.co.uk"),
    "reuters": ("reuters.com",),
    "associated press": ("apnews.com",),
    "ap news": ("apnews.com",),
    "techcrunch": ("techcrunch.com",),
    "espn": ("espn.com",),
    "science daily": ("sciencedaily.com",),
    "sciencedaily": ("sciencedaily.com",),
    "the guardian": ("theguardian.com",),
    "al jazeera": ("aljazeera.net", "aljazeera.com"),
    "bloomberg": ("bloomberg.com",),
    "financial times": ("ft.com",),
    "wall street journal": ("wsj.com",),
    "alarabiya": ("alarabiya.com", "alarabiya.net"),
    "al arabiya": ("alarabiya.com", "alarabiya.net"),
}


def _publisher_requires_license(source_name: str = "", source_urls: tuple[str, ...] = ()) -> bool:
    """Fail closed for gated publishers; attribution or a link is not a reuse licence."""
    hosts = [_url_host(candidate) for candidate in source_urls if candidate]
    if any(host and _domain_requires_license(host) for host in hosts):
        return True

    name = re.sub(r"\s+", " ", (source_name or "").casefold()).strip()
    configured = _configured_licensed_domains()
    for term, domains in LICENSED_NAME_DOMAIN_MAP.items():
        if term not in name:
            continue
        # The correct publisher's exact domain must be both explicitly licensed and
        # present in the source metadata. Licensing a different publisher has no effect.
        if not any(domain in configured and any(_domain_matches_host(host, domain) for host in hosts)
                   for domain in domains):
            return True
    return False


# Category photos are CSS-generated placeholders. Old fixed stock URLs are listed
# only so records from older builds can be rejected during refresh.
CATEGORY_IMAGES = {category: "" for category in CATEGORY_NAMES}
LEGACY_IMAGE_URLS = {
    "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1532094349884-543bc11b234d?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1513364776144-60967b0f800f?auto=format&fit=crop&w=1400&q=82",
    "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1400&q=82",
}

# ---------------------------------------------------------------------------
# PostgreSQL: Supabase shared pooler is preferred for Render's IPv4 network.
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
    image_provider_url TEXT NOT NULL DEFAULT '',
    image_license_url TEXT NOT NULL DEFAULT '',
    image_rights_checked BOOLEAN NOT NULL DEFAULT FALSE,
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
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_source TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_credit TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_credit_url TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_provider_url TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_license_url TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_rights_checked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS image_checked_at TIMESTAMPTZ NULL;
-- Clear image URLs from older builds unless the exact asset was re-verified by the new pipeline.
UPDATE world_pulse_articles SET image_url = '', image_source = 'none', image_credit = '', image_credit_url = '', image_provider_url = '', image_license_url = '', image_checked_at = NULL WHERE image_url <> '' AND image_rights_checked = FALSE;
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
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_rights_checked, image_checked_at,
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


def _db_last_fetched_at() -> datetime | None:
    """Return the latest persisted fetch time, including updates from an independent Render Cron Job."""
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
        logger.debug("Could not read persisted refresh timestamp", exc_info=True)
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
            image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_rights_checked, image_checked_at,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo
        ) VALUES (
            %(slug)s, %(source_url)s, %(category)s, %(source_name)s, %(image_url)s,
            %(image_source)s, %(image_credit)s, %(image_credit_url)s, %(image_provider_url)s, %(image_license_url)s, %(image_rights_checked)s, %(image_checked_at)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s,
            %(content_ar)s, %(content_en)s, %(published_at)s, NOW(),
            %(read_minutes)s, %(original_language)s, FALSE
        )
        ON CONFLICT (source_url) DO UPDATE SET
            category = EXCLUDED.category,
            source_name = EXCLUDED.source_name,
            image_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_url
                ELSE EXCLUDED.image_url END,
            image_source = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_source
                ELSE EXCLUDED.image_source END,
            image_credit = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_credit
                ELSE EXCLUDED.image_credit END,
            image_credit_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_credit_url
                ELSE EXCLUDED.image_credit_url END,
            image_provider_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN world_pulse_articles.image_provider_url
                ELSE EXCLUDED.image_provider_url END,
            image_rights_checked = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
                    THEN TRUE
                ELSE EXCLUDED.image_rights_checked END,
            image_license_url = CASE
                WHEN EXCLUDED.image_source IN ('category', 'none') AND world_pulse_articles.image_rights_checked IS TRUE AND world_pulse_articles.image_url <> ''
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


# ---------------------------------------------------------------------------
# RSS ingestion and Gemini editorial processing
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
    """Conservative title-to-image metadata match; generic photos must not masquerade as event photos."""
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
    """Find a story-related Commons image, accepting only PD, CC0 or CC BY (not BY-SA/NC/ND)."""
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
    request_obj = Request(url, headers={"User-Agent": "WorldPulseNews/1.3 (news image finder; Wikimedia Commons API; contact site owner)"})
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
            # Keep the allowlist deliberately narrow: CC BY-SA is not included in this site's policy.
            is_cc0_url = bool(re.search(r"/publicdomain/zero/1\.0/?$", license_url_path))
            is_pd_url = bool(re.search(r"/publicdomain/mark/1\.0/?$", license_url_path))
            is_cc_by_url = bool(re.search(r"/licenses/by/(?:2\.0|3\.0|4\.0)/?$", license_url_path))
            # Require an explicit, supported licence URL; a text label alone is insufficient.
            license_ok = is_pd_url or is_cc0_url or is_cc_by_url
            forbidden = any(term in license_short for term in ("noncommercial", "non-commercial", "no derivatives", "no-derivatives", "by-nc", "by-nd", "by-sa", "share alike"))
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
            artist = _clean_text((ext.get("Artist") or {}).get("value", ""), 180)
            credit = artist or "Wikimedia Commons"
            # The Commons file page is always linked, so users can see attribution and source licensing.
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
    except Exception as exc:
        logger.debug("Wikimedia image search failed for %r: %s", title, exc)
        return {}


def _search_pexels_image(title: str) -> dict[str, str]:
    """Use Pexels only through its official API and retain required platform/photographer attribution."""
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
    except Exception as exc:
        logger.debug("Pexels image search failed for %r: %s", title, exc)
        return {}


def _with_unsplash_tracking(url: Any) -> str:
    """Add required attribution tracking to Unsplash page links, never to image URLs."""
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
    """Use official Unsplash API results, keep returned CDN URL unchanged, and attribute photographer + Unsplash."""
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
            # Unsplash's API guidelines require using URLs returned by the API; do not rewrite these URLs.
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
    except Exception as exc:
        logger.debug("Unsplash image search failed for %r: %s", title, exc)
        return {}


def _search_approved_presskit_image(title: str, category: str) -> dict[str, str]:
    """Only use press-kit assets that the site owner manually reviewed and explicitly approved."""
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "approved_presskit_images.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            entries = json.load(manifest_file)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(entries, list):
        return {}
    best: tuple[float, dict[str, str]] | None = None
    title_tokens = _image_tokens(title)
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
    """Provider priority: verified Commons, owner-approved press kit, then opt-in stock-photo APIs."""
    for finder in (
        lambda: _search_commons_image(title, lang),
        lambda: _search_approved_presskit_image(title, category),
        lambda: _search_pexels_image(title),
        lambda: _search_unsplash_image(title),
    ):
        result = finder()
        if result:
            return result
    return {}


def _resolve_article_image(raw: dict[str, Any]) -> dict[str, Any]:
    existing = str(raw.get("image_url") or "").strip()
    source = str(raw.get("image_source") or "")
    if (existing and source in TRUSTED_REUSABLE_IMAGE_SOURCES
            and raw.get("image_rights_checked") is True and existing not in LEGACY_IMAGE_URLS):
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
                "image_rights_checked": True,
            }

    search_title = _clean_text(raw.get("image_search_title") or raw.get("original_title") or "", 240)
    if search_title:
        result = _search_any_reusable_image(search_title, str(raw.get("original_language") or "en"), str(raw.get("category") or "world"))
        if result:
            result["image_checked_at"] = datetime.now(timezone.utc)
            result["image_rights_checked"] = True
            return result

    return {
        "image_url": "",
        "image_source": "none",
        "image_credit": "",
        "image_credit_url": "",
        "image_provider_url": "",
        "image_license_url": "",
        "image_rights_checked": False,
        "image_checked_at": datetime.now(timezone.utc),
    }


def _enrich_article_images(raw_articles: list[dict[str, Any]]) -> None:
    """Find article-relevant pictures while preserving attribution and licence metadata."""
    known_images: dict[str, dict[str, Any]] = {}
    try:
        for row in _db_fetch_all():
            if row.get("source_url"):
                known_images[str(row["source_url"])] = row
    except Exception:
        logger.debug("Could not load prior image cache", exc_info=True)
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
        if (input_source in TRUSTED_REUSABLE_IMAGE_SOURCES and item.get("image_url")
                and item.get("image_rights_checked") is True
                and isinstance(input_checked, datetime)
                and (now_utc - input_checked.astimezone(timezone.utc)).total_seconds() < IMAGE_CACHE_MAX_AGE_SECONDS):
            continue

        # Never carry forward an unverified publisher thumbnail or a legacy hard-coded stock URL.
        item.update({
            "image_url": "", "image_source": "none", "image_credit": "",
            "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
        })
        cached = known_images.get(source_url)
        cached_source = str((cached or {}).get("image_source") or "")
        if (cached and cached.get("image_url") and cached_source in TRUSTED_REUSABLE_IMAGE_SOURCES
                and str(cached.get("image_url")) not in LEGACY_IMAGE_URLS):
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
                item["image_rights_checked"] = bool(cached.get("image_rights_checked"))
                if not item["image_rights_checked"]:
                    # Old or incomplete cache metadata is not good enough to show an image.
                    item.update({"image_url": "", "image_source": "none", "image_credit": "",
                                 "image_credit_url": "", "image_provider_url": "", "image_license_url": ""})
                continue
        if cached and cached.get("image_source") in {"none", "duplicate_removed"} and cached.get("image_checked_at"):
            checked = cached.get("image_checked_at")
            if isinstance(checked, str):
                try:
                    checked = datetime.fromisoformat(checked.replace("Z", "+00:00"))
                except ValueError:
                    checked = None
            if isinstance(checked, datetime):
                if checked.tzinfo is None:
                    checked = checked.replace(tzinfo=timezone.utc)
                if (now_utc - checked.astimezone(timezone.utc)).total_seconds() < 12 * 60 * 60:
                    item["image_checked_at"] = checked
                    skip_image_lookup.add(source_url)

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
                logger.exception("Could not resolve image for article %s", item.get("source_url"))
                item.update({
                    "image_url": "", "image_source": "none", "image_credit": "",
                    "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
                    "image_checked_at": datetime.now(timezone.utc),
                })


def _parse_any_rss(feed_url: str, category: str, lang: str, default_source: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Discover stories via Google News RSS, but save only allowlisted publisher domains."""
    request_obj = Request(feed_url, headers={"User-Agent": "WorldPulseNews/1.3 (+RSS discovery; link to publisher; contact site owner)"})
    try:
        with urlopen(request_obj, timeout=RSS_TIMEOUT_SECONDS) as response:
            raw = response.read(2_000_000)
        feed = feedparser.parse(raw)
        active_domains = _effective_source_domains(category, lang)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:30]:
            title = _clean_text(entry.get("title", ""), 350)
            story_url = str(entry.get("link", "")).strip()
            if not title or not story_url.startswith(("https://", "http://")):
                continue
            source_info = entry.get("source")
            publisher = _clean_text(source_info.get("title", ""), 120) if source_info else ""
            source_href = ""
            if source_info:
                source_href = str(source_info.get("href") or source_info.get("url") or "").strip()
            if not publisher:
                continue

            source_host = _url_host(source_href)
            article_host = _url_host(story_url)
            source_allowed = any(_domain_matches_host(source_host, domain) for domain in active_domains)
            article_allowed = any(_domain_matches_host(article_host, domain) for domain in active_domains)
            google_redirect = article_host in GOOGLE_NEWS_HOSTS

            # In Google News RSS, the item link is often a Google redirect; in that case
            # source.href must identify an approved publisher. Reject unrecognised hosts.
            if source_host:
                if not source_allowed:
                    continue
                if not google_redirect and not article_allowed:
                    continue
            elif not article_allowed:
                continue

            if _publisher_requires_license(publisher, (source_href, story_url)):
                logger.debug("Skipping publisher pending written permission: %s", publisher)
                continue

            summary_raw = entry.get("summary", "") or entry.get("description", "")
            if not summary_raw and entry.get("content"):
                try:
                    summary_raw = entry.get("content", [{}])[0].get("value", "")
                except (IndexError, TypeError):
                    summary_raw = ""
            items.append({
                "category": category,
                "source_url": story_url,
                "source_name": publisher,
                # Publisher thumbnails are never reused without an explicit image licence.
                "image_url": "", "image_source": "none", "image_credit": "",
                "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
                "image_rights_checked": False, "image_checked_at": None,
                "original_title": title,
                "original_summary": _clean_text(summary_raw, 500),
                "published_at": _parse_published(entry),
                "original_language": lang,
            })
        logger.info("RSS discovery %s/%s: %s accepted from %s domains", category, lang, len(items), len(active_domains))
        return category, lang, items
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        logger.info("RSS feed unavailable for %s/%s (%s): %s", category, lang, default_source, exc)
        return category, lang, []
    except Exception:
        logger.exception("Unexpected RSS parsing error for %s/%s (%s)", category, lang, default_source)
        return category, lang, []


def _parse_feed_task(category: str, lang: str, source_focus: bool = False) -> tuple[str, str, list[dict[str, Any]]]:
    query = CATEGORY_QUERIES[category][lang]
    if source_focus:
        domains = _effective_source_domains(category, lang)
        if not domains:
            return category, lang, []
        domain_query = " OR ".join(f"site:{domain}" for domain in domains)
        query = f"({query}) ({domain_query})"
    if lang == "ar":
        locale = {"hl": "ar", "gl": "JO", "ceid": "JO:ar"}
    else:
        locale = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    params = {"q": query, **locale}
    feed_url = "https://news.google.com/rss/search?" + urlencode(params)
    label = "Google News RSS · targeted allowlisted discovery" if source_focus else "Google News RSS · filtered discovery"
    return _parse_any_rss(feed_url, category, lang, label)

def _slug_for_url(url: str) -> str:
    return "story-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:18]


def _collect_rss_articles() -> list[dict[str, Any]]:
    """Two search passes for each category/language, then strict allowlist and deduplication."""
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
                category, _lang, items = future.result()
                by_category[category].extend(items)
            except Exception:
                logger.exception("RSS discovery worker failed")

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
    summary = raw.get("original_summary", "").strip()
    original_lang = raw.get("original_language", "ar" if _looks_arabic(title) else "en")
    if not summary:
        summary = title
    raw_image_source = str(raw.get("image_source") or "")
    image_approved = bool(raw.get("image_rights_checked")) and raw_image_source in TRUSTED_REUSABLE_IMAGE_SOURCES and bool(raw.get("image_url")) and str(raw.get("image_url")) not in LEGACY_IMAGE_URLS
    image_fields = {
        "image_url": str(raw.get("image_url") or "") if image_approved else "",
        "image_source": raw_image_source if image_approved else "none",
        "image_credit": raw.get("image_credit", "") if image_approved else "",
        "image_credit_url": raw.get("image_credit_url", "") if image_approved else "",
        "image_provider_url": raw.get("image_provider_url", "") if image_approved else "",
        "image_license_url": raw.get("image_license_url", "") if image_approved else "",
        "image_rights_checked": image_approved,
        "image_checked_at": raw.get("image_checked_at"),
    }
    return {
        "slug": raw["slug"],
        "source_url": raw["source_url"],
        "category": raw["category"],
        "source_name": raw.get("source_name") or "",
        **image_fields,
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
            "source_url": article.get("source_url", "")[:500],
            "excerpt": article.get("original_summary", "")[:500],
        }
        for i, article in enumerate(raw_articles)
    ]
    prompt = f"""You are the bilingual editorial desk for World Pulse. Make a concise, original, attributed news brief from a headline and a short RSS discovery excerpt only.
Copyright and factuality rules:
- The supplied headline and short RSS excerpt are limited discovery metadata, not permission to reproduce the source article. Do not fetch or reproduce the article body, and do not repeat distinctive sentences or long source phrases.
- Clearly identify the publisher and link to the original source. Never claim independent verification or claim to have read the full article.
- Use only facts explicitly supported by the supplied headline/excerpt. Do not invent names, numbers, quotes, dates, causes, outcomes, or details. Keep analysis distinct from confirmed facts.
- Write original and useful Arabic/English briefings. If the source material is thin, do not pad the article with general filler. Leave the extra body short rather than copying or inventing.

Return valid JSON only with key stories. Each story must preserve index and include exactly index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en. Use natural Modern Standard Arabic and neutral international English. The summary should be 1–2 concise sentences. The body should contain 1–3 short paragraphs of additional information that do not repeat the executive summary. If no extra facts are supported, content fields may be empty. Do not include Markdown or text outside JSON.
Input JSON: {json.dumps(payload, ensure_ascii=False)}"""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
        )
        text = (response.text or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        parsed = json.loads(text)
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
    # Count a bilingual article only once approximately; 200 wpm is a reasonable display estimate.
    return max(1, min(20, (words // 400) + 1))


def _avoid_repeated_news_photos(raw_articles: list[dict[str, Any]]) -> None:
    """Prefer one article-specific image per story, re-searching collisions when possible."""
    seen: set[str] = set()
    alt_lookups = 0
    ordered = sorted(
        raw_articles,
        key=lambda item: item.get("published_at") or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    for item in ordered:
        image_url = str(item.get("image_url") or "")
        if not image_url or image_url in set(CATEGORY_IMAGES.values()):
            continue  # Category placeholders are intentionally generic fallback art.
        parsed = urlparse(image_url)
        identity = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}" if parsed.netloc else image_url
        if identity not in seen:
            seen.add(identity)
            continue

        alternative: dict[str, str] = {}
        if alt_lookups < MAX_IMAGE_LOOKUPS_PER_REFRESH:
            alt_lookups += 1
            query = str(item.get("image_search_title") or item.get("original_title") or "")
            alternative = _search_commons_image(query, str(item.get("original_language") or "en"))
        candidate_url = str(alternative.get("image_url") or "")
        candidate = urlparse(candidate_url)
        candidate_identity = f"{candidate.scheme.lower()}://{candidate.netloc.lower()}{candidate.path.rstrip('/')}" if candidate.netloc else candidate_url
        if candidate_url and candidate_identity not in seen and candidate_url not in set(CATEGORY_IMAGES.values()):
            item.update(alternative)
            seen.add(candidate_identity)
        else:
            # If no genuinely different relevant picture is available, avoid repeating the same photo.
            item.update({
                "image_url": "",
                "image_source": "duplicate_removed",
                "image_credit": "",
                "image_credit_url": "",
                "image_provider_url": "",
                "image_license_url": "",
                "image_rights_checked": False,
                "image_checked_at": datetime.now(timezone.utc),
            })


def _refresh_news_job() -> None:
    global _REFRESHING, _LAST_REFRESH_SUCCESS, _LAST_REFRESH_AT, _LAST_REFRESH_STATE, _LAST_REFRESH_ERROR
    try:
        with _STATE_LOCK:
            _LAST_REFRESH_STATE = "running"
            _LAST_REFRESH_ERROR = ""
        raw_articles = _collect_rss_articles()
        if not raw_articles:
            logger.warning("RSS refresh returned no stories; existing articles remain available")
            with _STATE_LOCK:
                _LAST_REFRESH_STATE = "error"
                _LAST_REFRESH_ERROR = "No RSS stories returned"
            return

        # Translate first so Arabic headlines can also be searched in English image indexes.
        translations = _translate_batch(raw_articles)
        for index, raw in enumerate(raw_articles):
            translated = translations.get(index, {})
            raw["image_search_title"] = translated.get("title_en", "")
        # Image enrichment runs in parallel and never blocks the user-facing request.
        _enrich_article_images(raw_articles)
        _avoid_repeated_news_photos(raw_articles)
        ready: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_articles):
            article = _base_article(raw)
            if index in translations:
                article.update(translations[index])
            article["read_minutes"] = _reading_minutes(article)
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
    """Refresh in a daemon thread so a slow external feed never blocks the page render."""
    global _REFRESHING, _LAST_REFRESH_ATTEMPT
    if not NEWS_AUTO_FETCH:
        return
    now = time.monotonic()
    with _STATE_LOCK:
        if _REFRESHING:
            return
        interval = NEWS_REFRESH_MINUTES * 60 if _LAST_REFRESH_SUCCESS else NEWS_RETRY_MINUTES * 60
        # On a newly started worker, retry slowly if there's already persisted data; otherwise
        # make one initial attempt and let the fallback render immediately.
        if _LAST_REFRESH_ATTEMPT and now - _LAST_REFRESH_ATTEMPT < min(interval, NEWS_RETRY_MINUTES * 60):
            return
        if _LAST_REFRESH_SUCCESS and now - _LAST_REFRESH_SUCCESS < interval:
            return
        _LAST_REFRESH_ATTEMPT = now
        _REFRESHING = True
    thread = threading.Thread(target=_refresh_news_job, name="world-pulse-rss-refresh", daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Display helpers, fallback and routes
# ---------------------------------------------------------------------------


def _normalise_summary_body(summary: str, content: str) -> str:
    """Remove duplicated executive-summary sentences/paragraphs from the article body."""
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
        # Handle providers that concatenate the executive summary and extra text directly.
        content = content[len(summary):].lstrip(" \n\r—:؛.،-")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
    if len(paragraphs) == 1:
        # Some feeds/AI responses put each sentence on one line or omit paragraph breaks.
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


def _normalise_story(row: dict[str, Any], lang: str) -> dict[str, Any]:
    story = dict(row)
    story.setdefault("source_name", "")
    story.setdefault("image_url", CATEGORY_IMAGES.get(story.get("category", "world"), CATEGORY_IMAGES["world"]) if story.get("is_demo") else "")
    story.setdefault("image_source", "")
    story.setdefault("image_credit", "")
    story.setdefault("image_credit_url", "")
    story.setdefault("image_provider_url", "")
    story.setdefault("image_license_url", "")
    story.setdefault("image_rights_checked", False)
    story.setdefault("is_demo", False)
    if story.get("is_demo"):
        story["source_name"] = UI_TEXT[lang]["sample_source"]
    elif (story.get("image_source") not in TRUSTED_REUSABLE_IMAGE_SOURCES
          or not story.get("image_rights_checked")
          or story.get("image_url") in LEGACY_IMAGE_URLS):
        story["image_url"] = ""
        story["image_source"] = "none"
        story["image_credit"] = ""
        story["image_credit_url"] = ""
        story["image_provider_url"] = ""
        story["image_license_url"] = ""
    story["title"] = story.get(f"title_{lang}") or ""
    story["summary"] = story.get(f"summary_{lang}") or ""
    raw_content = story.get(f"content_{lang}") or ""
    story["content"] = _normalise_summary_body(story["summary"], raw_content)
    story["category_label"] = CATEGORY_NAMES.get(story.get("category", "world"), CATEGORY_NAMES["world"])[lang]
    story["published_label"] = _format_date(story.get("published_at"), lang)
    story["read_minutes"] = max(1, int(story.get("read_minutes") or 1))
    if not story.get("slug"):
        story["slug"] = _slug_for_url(story.get("source_url", "world-pulse"))
    if not story.get("image_url") and story.get("is_demo"):
        story["image_url"] = CATEGORY_IMAGES.get(story.get("category", "world"), CATEGORY_IMAGES["world"])
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
    live = [row for row in _all_live_articles() if not row.get("is_demo") and row.get("source_url") and row.get(f"title_{lang}") and row.get("category") in CATEGORY_NAMES]
    live.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
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


@app.get("/api/news-status")
def news_status():
    # Read the database timestamp so an independent Render Cron Job can notify open pages.
    persisted_at = _db_last_fetched_at()
    last_refresh_at = persisted_at or _LAST_REFRESH_AT
    return jsonify({
        "running": bool(_REFRESHING),
        "state": _LAST_REFRESH_STATE,
        "last_refresh_at": last_refresh_at.isoformat() if last_refresh_at else None,
        "interval_minutes": NEWS_REFRESH_MINUTES,
        "error": _LAST_REFRESH_ERROR,
        "source_allowlist_enabled": True,
        "active_source_domains": {cat: {lang: _effective_source_domains(cat, lang) for lang in ("ar", "en")} for cat in CATEGORY_NAMES},
        "publisher_license_override_domains": sorted(_configured_licensed_domains()),
        "image_api_configured": {"unsplash": bool(UNSPLASH_ACCESS_KEY), "pexels": bool(PEXELS_API_KEY)},
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


# Static/legal pages, contact form, and crawl endpoints
STATIC_PAGES = {
    "about": {
        "title_ar": "من نحن", "title_en": "About Us",
        "sections_ar": [
            ("رسالتنا", "نبض العالم منصة إخبارية وتحليلية تهدف إلى وضع الأحداث في سياقها، مع روابط واضحة إلى المصادر الأصلية."),
            ("منهجنا التحريري", "نميّز بين الخبر المنقول والتحليل والرأي، ونشجّع القراء على الرجوع إلى المصادر الأصلية والتحقق من المعلومات. قد تُستخدم أدوات الذكاء الاصطناعي للمساعدة في التحرير، وتظل المراجعة البشرية والتحقق ضروريين."),
            ("التصحيحات", "إذا لاحظت خطأً أو معلومة تحتاج إلى توضيح، تواصل معنا عبر صفحة اتصل بنا مع رابط المادة والتفاصيل ذات الصلة."),
        ],
        "sections_en": [
            ("Our mission", "World Pulse is a news and analysis platform focused on context, with clear links to original sources."),
            ("Editorial approach", "We distinguish reported information from analysis and opinion and encourage readers to consult original sources. AI tools may assist editorial work; human review and fact-checking remain important."),
            ("Corrections", "If you spot an error or a claim that needs clarification, contact us with the article URL and relevant details."),
        ],
    },
    "privacy": {
        "title_ar": "سياسة الخصوصية", "title_en": "Privacy Policy",
        "sections_ar": [
            ("المعلومات التي نعالجها", "قد نعالج المعلومات التي ترسلها طوعاً عبر نموذج التواصل، وبيانات تقنية أساسية لازمة لتشغيل الموقع وحمايته. لا تكتب معلومات حساسة في نموذج التواصل."),
            ("ملفات تعريف الارتباط", "قد يستخدم الموقع جلسة ضرورية لحفظ تفضيل اللغة والحد من إساءة استخدام بعض الميزات، كما يحفظ تفضيل المظهر محلياً في متصفحك."),
            ("الخدمات الخارجية", "قد يعتمد الموقع على خدمات خارجية مثل الاستضافة وقاعدة البيانات وواجهات الذكاء الاصطناعي. تخضع البيانات المرسلة إليها لسياسات تلك الخدمات."),
            ("الإعلانات والتحليلات", "إذا أضيفت خدمات إعلانات أو تحليلات لاحقاً، يجب تحديث هذه السياسة والإفصاح عن استخدام ملفات تعريف الارتباط والبيانات ذات الصلة قبل تفعيلها عند الاقتضاء."),
            ("التواصل", "للاستفسارات المتعلقة بالخصوصية، راسل syfsywf86@gmail.com."),
        ],
        "sections_en": [
            ("Information we process", "We may process information you voluntarily submit through the contact form and basic technical data needed to operate and protect the website. Do not submit sensitive information."),
            ("Cookies and local storage", "The site may use a necessary session cookie for language preferences and abuse prevention. Your theme preference is stored locally in your browser."),
            ("Third-party services", "Hosting, database, and AI features may rely on third-party services. Data sent to those services is subject to their own policies."),
            ("Advertising and analytics", "If advertising or analytics services are added later, this policy must be updated to explain relevant cookies and data use before activation where required."),
            ("Contact", "For privacy questions, email syfsywf86@gmail.com."),
        ],
    },
    "terms": {
        "title_ar": "شروط الاستخدام", "title_en": "Terms of Service",
        "sections_ar": [
            ("الاستخدام المسؤول", "استخدم الموقع لأغراض قانونية، ولا تحاول تعطيل خدماته أو إساءة استخدام واجهات الذكاء الاصطناعي أو نموذج التواصل."),
            ("المحتوى والمصادر", "تُعرض الأخبار مع الإشارة إلى مصادرها وروابطها متى توفرت. الروابط الخارجية تقود إلى مواقع لا نديرها. تحقق من المعلومات المهمة بالرجوع إلى المصدر الأصلي."),
            ("التحليل والذكاء الاصطناعي", "المحتوى التحليلي وإجابات الذكاء الاصطناعي لأغراض معلوماتية عامة وقد تحتوي على نقص أو خطأ؛ لا تعتمد عليها وحدها في القرارات المهمة."),
            ("حقوق النشر", "لا تنسخ أو تعِد نشر مواد الموقع أو الصور إلا وفق الترخيص المنطبق أو إذن صاحب الحقوق. أبلغنا عن أي استخدام يثير مخاوف حقوقية."),
            ("التعديلات", "قد تتغير هذه الشروط عند تحديث الموقع أو المتطلبات القانونية."),
        ],
        "sections_en": [
            ("Responsible use", "Use this website lawfully. Do not disrupt services or abuse AI endpoints or the contact form."),
            ("Content and sources", "Stories link to original sources where available. External links lead to sites we do not operate. Verify important claims with the original source."),
            ("Analysis and AI", "Analysis and AI answers are for general information and may be incomplete or incorrect. Do not rely on them alone for consequential decisions."),
            ("Copyright", "Do not copy or republish site content or images except as allowed by the applicable license or rights holder. Contact us about rights concerns."),
            ("Changes", "These terms may be updated as the site and applicable requirements evolve."),
        ],
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
    return render_template(
        "index.html", page="static", static_page=page_data,
        static_page_key=page_key, static_sections=page_data["sections_ar" if lang == "ar" else "sections_en"],
        stories=[], all_story_count=0, active_category="all", breaking_story=None,
        related_stories=[], article=None, contact_sent=False, contact_error="",
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
        if not name or not email or not message or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            error = "يرجى تعبئة الحقول بشكل صحيح." if lang == "ar" else "Please complete all fields with a valid email address."
        elif not all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")):
            error = "نموذج التواصل غير مفعّل حالياً. راسلنا مباشرة عبر البريد." if lang == "ar" else "The contact form is not configured yet. Please email us directly."
        else:
            try:
                msg = EmailMessage()
                msg["Subject"] = f"World Pulse contact from {name[:80]}"
                msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USERNAME"))
                msg["To"] = "syfsywf86@gmail.com"
                msg["Reply-To"] = email
                msg.set_content(f"Name: {name}\nEmail: {email}\n\n{message}")
                with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
                    server.starttls()
                    server.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
                    server.send_message(msg)
                sent = True
                session.pop("contact_csrf", None)
            except Exception:
                logger.exception("Contact email delivery failed")
                error = "تعذّر إرسال الرسالة حالياً. جرّب البريد المباشر." if lang == "ar" else "Message delivery failed. Please use the direct email link."
    return render_template(
        "index.html", page="contact", static_page=None, static_page_key="contact",
        static_sections=[], stories=[], all_story_count=0, active_category="all",
        breaking_story=None, related_stories=[], article=None, contact_sent=sent,
        contact_error=error, contact_csrf=token,
    ), 200

@app.get("/sitemap.xml")
def sitemap():
    origin = _site_origin()
    urls = [url_for("index", _external=False)]
    urls += [url_for("static_page", page_key=key, _external=False) for key in STATIC_PAGES]
    urls += [url_for("contact", _external=False)]
    for story in _get_display_stories(current_language()):
        if not story.get("is_demo") and story.get("slug"):
            urls.append(url_for("article", slug=story["slug"], _external=False))
    xml_urls = "".join(f"<url><loc>{html.escape(origin + path)}</loc></url>" for path in dict.fromkeys(urls))
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + xml_urls + '</urlset>'
    return app.response_class(body, mimetype="application/xml")

@app.get("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {_site_origin()}/sitemap.xml\n"
    return app.response_class(body, mimetype="text/plain")


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
        # Render Cron Job entry point: run one refresh synchronously and exit with status.
        with _STATE_LOCK:
            _REFRESHING = True
            _LAST_REFRESH_ATTEMPT = time.monotonic()
        _refresh_news_job()
        raise SystemExit(0 if _LAST_REFRESH_STATE in {"success", "memory_only"} else 1)
    # Local development only. Render web services should use Gunicorn.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
