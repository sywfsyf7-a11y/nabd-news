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
from functools import wraps
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
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

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
MAX_IMAGE_LOOKUPS_PER_REFRESH = max(0, min(60, int(os.getenv("MAX_IMAGE_LOOKUPS_PER_REFRESH", "48"))))
MAX_IMAGE_BACKFILL_PER_REFRESH = max(0, min(24, int(os.getenv("MAX_IMAGE_BACKFILL_PER_REFRESH", "24"))))
MAX_EDITORIAL_BACKFILL_PER_REFRESH = max(0, min(12, int(os.getenv("MAX_EDITORIAL_BACKFILL_PER_REFRESH", "4"))))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
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
        "search_hint": "ابحث عن خبر أو موضوع",
        "search_label": "ابحث في الأخبار",
        "search_placeholder": "مثلاً: تطبيقات المغرب أو أسعار النفط",
        "search_button": "بحث",
        "search_results": "نتائج البحث",
        "search_empty": "لم نعثر على أخبار تطابق بحثك. جرّب كلمات أخرى.",
        "search_query_required": "اكتب كلمة أو عبارة للبحث.",
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
        "search_hint": "Search news and topics",
        "search_label": "Search the news",
        "search_placeholder": "For example: Morocco apps or oil prices",
        "search_button": "Search",
        "search_results": "Search results",
        "search_empty": "No stories matched your search. Try different keywords.",
        "search_query_required": "Enter a word or phrase to search.",
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
        "en": ["bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "politico.com", "aljazeera.com", "skynews.com"],
    },
    "economy": {
        "ar": ["asharqbusiness.com", "cnbcarabia.com", "mubasher.info", "alarabiya.com", "alarabiya.net", "skynewsarabia.com"],
        "en": ["bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "reuters.com", "politico.com"],
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
        "ar": ["natgeotv.com", "nationalgeographic.com", "aljazeera.net", "alarabiya.com", "alarabiya.net", "dw.com", "france24.com", "arabic.cnn.com"],
        "en": ["nasa.gov", "space.com", "scientificamerican.com", "livescience.com", "newscientist.com"],
    },
    "culture": {
        "ar": ["qafilah.com", "alqafilah.com", "alsahafa.org", "thifaf.com", "aljazeera.net", "alaraby.co.uk", "alarab.co.uk"],
        "en": ["lithub.com", "artsy.net", "theguardian.com"],
    },
    "world": {
        "ar": ["france24.com", "bbc.com", "bbc.co.uk", "dw.com", "aljazeera.net", "euronews.com"],
        "en": ["euronews.com", "bbc.com", "bbc.co.uk", "apnews.com", "reuters.com", "france24.com", "dw.com", "skynews.com"],
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


_SOURCE_CONTROL_LOCK = threading.Lock()
_SOURCE_CONTROL_CACHE: dict[str, dict[str, Any]] = {}
_SOURCE_CONTROL_CACHE_AT = 0.0
_SOURCE_CONTROL_CACHE_TTL = 45.0
_IMAGE_ADMIN_LOCK = threading.Lock()
_IMAGE_ADMIN_CACHE: dict[str, Any] = {"providers": {}, "blocked": set()}
_IMAGE_ADMIN_CACHE_AT = 0.0
_IMAGE_ADMIN_CACHE_TTL = 45.0
_IMAGE_DIAGNOSTICS_LOCK = threading.Lock()
_IMAGE_DIAGNOSTICS: dict[str, Any] = {
    "lookups_started": 0, "images_found": 0, "images_not_found": 0,
    "lookup_errors": 0, "last_success_at": None, "last_source": "", "last_problem": "",
}


def _load_source_controls(force: bool = False) -> dict[str, dict[str, Any]]:
    """Load administrator source decisions; if DB is unavailable, retain safe defaults."""
    global _SOURCE_CONTROL_CACHE, _SOURCE_CONTROL_CACHE_AT
    now = time.monotonic()
    with _SOURCE_CONTROL_LOCK:
        if not force and now - _SOURCE_CONTROL_CACHE_AT < _SOURCE_CONTROL_CACHE_TTL:
            return dict(_SOURCE_CONTROL_CACHE)
    if not _ensure_schema():
        return dict(_SOURCE_CONTROL_CACHE)
    conn = _connect_db()
    if conn is None:
        return dict(_SOURCE_CONTROL_CACHE)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT domain, enabled, license_verified, notes, updated_at FROM world_pulse_source_controls")
            rows = {str(row["domain"]).lower(): dict(row) for row in cur.fetchall()}
        with _SOURCE_CONTROL_LOCK:
            _SOURCE_CONTROL_CACHE = rows
            _SOURCE_CONTROL_CACHE_AT = now
        return dict(rows)
    except Exception:
        logger.warning("Could not load source controls", exc_info=True)
        return dict(_SOURCE_CONTROL_CACHE)
    finally:
        conn.close()


def _is_restricted_source_domain(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(_domain_matches_host(host, restricted) for restricted in LICENSE_REQUIRED_DOMAINS)


def _domain_requires_license(host: str) -> bool:
    """Restricted publishers stay off unless explicit licensing is configured or reviewed by admin."""
    host = (host or "").lower().rstrip(".")
    matched = next((domain for domain in LICENSE_REQUIRED_DOMAINS if _domain_matches_host(host, domain)), None)
    if not matched:
        return False
    if matched in _configured_licensed_domains():
        return False
    control = _load_source_controls().get(matched, {})
    return not (bool(control.get("enabled")) and bool(control.get("license_verified")))


def _source_domain_enabled(domain: str) -> bool:
    domain = (domain or "").lower().strip().strip(".")
    if not domain:
        return False
    controls = _load_source_controls()
    control = controls.get(domain)
    if control is not None and not bool(control.get("enabled")):
        return False
    if _is_restricted_source_domain(domain):
        if domain in _configured_licensed_domains():
            return True
        return bool(control and control.get("enabled") and control.get("license_verified"))
    return True


def _effective_source_domains(category: str, lang: str) -> list[str]:
    domains = CATEGORY_SOURCE_DOMAINS.get(category, {}).get(lang, [])
    return [domain for domain in domains if _source_domain_enabled(domain) and not _domain_requires_license(domain)]


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

# Source labels in Google News RSS are not always accompanied by source.href.
# These explicit aliases permit a domain inference only when the inferred domain is
# already listed for that section/language. Unknown names remain rejected (fail closed).
SOURCE_NAME_DOMAIN_HINTS = {
    "bbc": ("bbc.com", "bbc.co.uk"), "بي بي سي": ("bbc.com", "bbc.co.uk"),
    "reuters": ("reuters.com",), "رويترز": ("reuters.com",),
    "associated press": ("apnews.com",), "ap news": ("apnews.com",), "أسوشيتد برس": ("apnews.com",),
    "politico": ("politico.com",), "الجزيرة": ("aljazeera.net", "aljazeera.com"), "al jazeera": ("aljazeera.net", "aljazeera.com"),
    "العربية": ("alarabiya.com", "alarabiya.net"), "al arabiya": ("alarabiya.com", "alarabiya.net"),
    "سكاي نيوز عربية": ("skynewsarabia.com",), "sky news": ("skynewsarabia.com", "skynews.com"),
    "الشرق الأوسط": ("aawsat.com",), "asharq al-awsat": ("aawsat.com",), "القدس العربي": ("alquds.co.uk",),
    "اقتصاد الشرق": ("asharqbusiness.com",), "asharq business": ("asharqbusiness.com",),
    "cnbc عربية": ("cnbcarabia.com",), "cnbc arabia": ("cnbcarabia.com",), "مباشر": ("mubasher.info",), "mubasher": ("mubasher.info",),
    "bloomberg": ("bloomberg.com",), "financial times": ("ft.com",), "wall street journal": ("wsj.com",),
    "البوابة العربية للأخبار التقنية": ("aitnews.com",), "aitnews": ("aitnews.com",),
    "عالم التقنية": ("tech-wd.com",), "tech-wd": ("tech-wd.com",), "عرب هاردوير": ("arabhardware.net",), "arab hardware": ("arabhardware.net",),
    "the verge": ("theverge.com",), "techcrunch": ("techcrunch.com",), "wired": ("wired.com",),
    "سعودي جيمر": ("saudigamer.com",), "saudi gamer": ("saudigamer.com",), "شبكة ألعاب العرب": ("arabiangamer.net",), "arabian gamer": ("arabiangamer.net",),
    "ign": ("ign.com",), "gamespot": ("gamespot.com",), "polygon": ("polygon.com",), "pc gamer": ("pcgamer.com",),
    "في الجول": ("filgoal.com",), "filgoal": ("filgoal.com",), "كووورة": ("kooora.com",), "kooora": ("kooora.com",),
    "bein sports": ("beinsports.com",), "بي إن سبورتس": ("beinsports.com",), "espn": ("espn.com",), "sky sports": ("skysports.com",),
    "ناشيونال جيوغرافيك": ("nationalgeographic.com", "natgeotv.com"), "national geographic": ("nationalgeographic.com", "natgeotv.com"),
    "nasa": ("nasa.gov",), "space.com": ("space.com",), "scientific american": ("scientificamerican.com",), "live science": ("livescience.com",),
    "القافلة": ("qafilah.com", "alqafilah.com"), "qafilah": ("qafilah.com", "alqafilah.com"),
    "العربي الجديد": ("alaraby.co.uk",), "al araby": ("alaraby.co.uk",), "صحيفة العرب": ("alarab.co.uk",),
    "literary hub": ("lithub.com",), "artsy": ("artsy.net",), "the guardian": ("theguardian.com",),
    "فرانس 24": ("france24.com",), "france 24": ("france24.com",), "دويتشه فيله": ("dw.com",), "deutsche welle": ("dw.com",),
    "euronews": ("euronews.com",), "cnn": ("arabic.cnn.com",),
}

def _infer_source_domain(source_name: str, allowed_domains: list[str] | set[str] | tuple[str, ...]) -> str:
    """Map a publisher label to a catalog domain, constrained to caller's allowlist."""
    name = re.sub(r"\s+", " ", str(source_name or "").casefold()).strip()
    allowed = set(allowed_domains)
    for alias in sorted(SOURCE_NAME_DOMAIN_HINTS, key=len, reverse=True):
        if alias.casefold() not in name:
            continue
        for candidate in SOURCE_NAME_DOMAIN_HINTS[alias]:
            if candidate in allowed:
                return candidate
    return ""


def _publisher_requires_license(source_name: str = "", source_urls: tuple[str, ...] = ()) -> bool:
    """Fail closed for gated publishers; attribution or a link is not a reuse licence."""
    hosts = [_url_host(candidate) for candidate in source_urls if candidate]
    if any(host and _domain_requires_license(host) for host in hosts):
        return True

    name = re.sub(r"\s+", " ", (source_name or "").casefold()).strip()
    for term, domains in LICENSED_NAME_DOMAIN_MAP.items():
        if term not in name:
            continue
        # Matching source metadata and a domain-specific licence approval are both required.
        if not any(any(_domain_matches_host(host, domain) for host in hosts)
                   and not _domain_requires_license(domain) and _source_domain_enabled(domain)
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
    source_domain TEXT NOT NULL DEFAULT '',
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
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    ai_enriched BOOLEAN NOT NULL DEFAULT FALSE
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
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS source_domain TEXT NOT NULL DEFAULT '';
ALTER TABLE world_pulse_articles ADD COLUMN IF NOT EXISTS ai_enriched BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS world_pulse_source_controls (
    domain TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT TRUE,
    license_verified BOOLEAN NOT NULL DEFAULT FALSE, notes TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS world_pulse_image_provider_controls (
    provider TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS world_pulse_image_controls (
    image_url TEXT PRIMARY KEY, blocked BOOLEAN NOT NULL DEFAULT TRUE,
    reason TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS world_pulse_admin_audit (
    id BIGSERIAL PRIMARY KEY, actor TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
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
                SELECT slug, source_url, source_domain, category, source_name, image_url,
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_rights_checked, image_checked_at,
                       title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at,
                       read_minutes, original_language, is_demo, ai_enriched
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


def _load_image_admin_controls(force: bool = False) -> dict[str, Any]:
    global _IMAGE_ADMIN_CACHE, _IMAGE_ADMIN_CACHE_AT
    now = time.monotonic()
    with _IMAGE_ADMIN_LOCK:
        if not force and now - _IMAGE_ADMIN_CACHE_AT < _IMAGE_ADMIN_CACHE_TTL:
            return {"providers": dict(_IMAGE_ADMIN_CACHE.get("providers", {})), "blocked": set(_IMAGE_ADMIN_CACHE.get("blocked", set()))}
    if not _ensure_schema():
        return {"providers": dict(_IMAGE_ADMIN_CACHE.get("providers", {})), "blocked": set(_IMAGE_ADMIN_CACHE.get("blocked", set()))}
    conn = _connect_db()
    if conn is None:
        return {"providers": dict(_IMAGE_ADMIN_CACHE.get("providers", {})), "blocked": set(_IMAGE_ADMIN_CACHE.get("blocked", set()))}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT provider, enabled FROM world_pulse_image_provider_controls")
            providers = {str(row[0]): bool(row[1]) for row in cur.fetchall()}
            cur.execute("SELECT image_url FROM world_pulse_image_controls WHERE blocked IS TRUE")
            blocked = {str(row[0]) for row in cur.fetchall()}
        with _IMAGE_ADMIN_LOCK:
            _IMAGE_ADMIN_CACHE = {"providers": providers, "blocked": blocked}
            _IMAGE_ADMIN_CACHE_AT = now
        return {"providers": dict(providers), "blocked": set(blocked)}
    except Exception:
        logger.warning("Could not load image controls", exc_info=True)
        return {"providers": dict(_IMAGE_ADMIN_CACHE.get("providers", {})), "blocked": set(_IMAGE_ADMIN_CACHE.get("blocked", set()))}
    finally:
        conn.close()


def _image_provider_enabled(provider: str) -> bool:
    controls = _load_image_admin_controls()
    defaults = {
        "wikimedia": True,
        "presskit": True,
        "pexels": bool(PEXELS_API_KEY),
        "unsplash": bool(UNSPLASH_ACCESS_KEY),
    }
    return bool(controls["providers"].get(provider, defaults.get(provider, False))) and (provider not in {"pexels", "unsplash"} or defaults[provider])


def _image_identity(image_url: str) -> str:
    """Canonical image identity for blocking: ignore tracking/query and fragments."""
    try:
        parsed = urlparse(str(image_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(image_url or "").strip()
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    except ValueError:
        return str(image_url or "").strip()


def _is_image_blocked(image_url: str) -> bool:
    if not image_url:
        return False
    target = _image_identity(image_url)
    blocked = _load_image_admin_controls().get("blocked", set())
    return any(target == _image_identity(item) for item in blocked)


def _image_source_provider(image_source: str) -> str:
    return {
        "wikimedia_relevant": "wikimedia",
        "presskit_approved": "presskit",
        "pexels_api": "pexels",
        "unsplash_api": "unsplash",
    }.get(str(image_source or ""), "")


def _db_fetch_articles_needing_editorial(limit: int = 4) -> list[dict[str, Any]]:
    """Select a small number of real stories whose executive summary likely repeats the headline."""
    if not GEMINI_API_KEY or genai is None or types is None or not _ensure_schema():
        return []
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT slug, source_url, source_domain, category, source_name,
                       title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
                       published_at, fetched_at, read_minutes, original_language, ai_enriched
                FROM world_pulse_articles
                WHERE is_demo=FALSE AND source_url<>''
                  AND (COALESCE(ai_enriched,FALSE)=FALSE
                    OR (title_ar<>'' AND (summary_ar='' OR summary_ar=title_ar OR LENGTH(summary_ar)<90))
                    OR (title_en<>'' AND (summary_en='' OR summary_en=title_en OR LENGTH(summary_en)<90)))
                ORDER BY fetched_at ASC, published_at DESC NULLS LAST
                LIMIT %s
            """, (max(1, min(12, int(limit) * 5)),))
            rows = [dict(row) for row in cur.fetchall()]
        selected = []
        for row in rows:
            if not _article_source_is_enabled(row):
                continue
            title_ar, summary_ar = str(row.get("title_ar") or ""), str(row.get("summary_ar") or "")
            title_en, summary_en = str(row.get("title_en") or ""), str(row.get("summary_en") or "")
            if ((title_ar and not _summary_is_distinct(title_ar, summary_ar))
                    or (title_en and not _summary_is_distinct(title_en, summary_en))):
                selected.append(row)
            if len(selected) >= max(1, min(12, int(limit))):
                break
        return selected
    except Exception:
        logger.debug("Could not read articles needing editorial backfill", exc_info=True)
        return []
    finally:
        conn.close()


def _stored_article_for_editorial_backfill(row: dict[str, Any]) -> dict[str, Any]:
    original_language = str(row.get("original_language") or "")
    if original_language not in {"ar", "en"}:
        original_language = "ar" if _looks_arabic(str(row.get("title_ar") or "")) else "en"
    title = str(row.get(f"title_{original_language}") or row.get("title_en") or row.get("title_ar") or "")
    summary = str(row.get(f"summary_{original_language}") or row.get("summary_en") or row.get("summary_ar") or "")
    return {
        "slug": row.get("slug") or _slug_for_url(str(row.get("source_url") or "")),
        "source_url": str(row.get("source_url") or ""),
        "source_domain": str(row.get("source_domain") or ""),
        "category": str(row.get("category") or "world"),
        "source_name": str(row.get("source_name") or ""),
        "original_title": title,
        "original_summary": summary[:700],
        "original_language": original_language,
        "published_at": row.get("published_at"),
        "_database_editorial_backfill": True,
        "_stored_row": row,
    }


def _db_update_editorial_many(articles: list[dict[str, Any]]) -> bool:
    """Update AI-edited fields only; do not bump fetched_at or touch image rights metadata."""
    if not articles or not _ensure_schema():
        return False
    conn = _connect_db()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            for item in articles:
                cur.execute("""
                    UPDATE world_pulse_articles SET
                        title_ar=COALESCE(NULLIF(%s,''), title_ar),
                        title_en=COALESCE(NULLIF(%s,''), title_en),
                        summary_ar=COALESCE(NULLIF(%s,''), summary_ar),
                        summary_en=COALESCE(NULLIF(%s,''), summary_en),
                        content_ar=COALESCE(NULLIF(%s,''), content_ar),
                        content_en=COALESCE(NULLIF(%s,''), content_en),
                        read_minutes=GREATEST(%s,1), ai_enriched=TRUE
                    WHERE source_url=%s AND is_demo=FALSE
                """, (
                    item.get("title_ar", ""), item.get("title_en", ""),
                    item.get("summary_ar", ""), item.get("summary_en", ""),
                    item.get("content_ar", ""), item.get("content_en", ""),
                    int(item.get("read_minutes") or 1), item.get("source_url", "")
                ))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logger.warning("Could not persist editorial backfill", exc_info=True)
        return False
    finally:
        conn.close()


def _db_fetch_articles_needing_images(limit: int = 8) -> list[dict[str, Any]]:
    """Select real stored stories whose images were never approved/found; backfill gradually."""
    if not _ensure_schema():
        return []
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT slug, source_url, source_domain, category, source_name, image_url,
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url,
                       image_rights_checked, image_checked_at, title_ar, title_en, summary_ar, summary_en,
                       content_ar, content_en, published_at, fetched_at, read_minutes,
                       original_language, is_demo, ai_enriched
                FROM world_pulse_articles
                WHERE is_demo = FALSE AND source_url <> '' AND COALESCE(image_url, '') = ''
                  AND (image_checked_at IS NULL OR image_checked_at < NOW() - INTERVAL '12 hours')
                ORDER BY image_checked_at ASC NULLS FIRST, published_at DESC NULLS LAST
                LIMIT %s
            """, (max(0, min(120, int(limit) * 4)),))
            rows = [dict(row) for row in cur.fetchall()]
        return [row for row in rows if _article_source_is_enabled(row)][:max(0, min(24, int(limit)))]
    except Exception:
        logger.debug("Could not read articles for image backfill", exc_info=True)
        return []
    finally:
        conn.close()


def _db_update_images_many(articles: list[dict[str, Any]]) -> bool:
    """Update only image metadata on existing stories, without changing article text or recency."""
    if not articles or not _ensure_schema():
        return False
    conn = _connect_db()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            for item in articles:
                cur.execute("""
                    UPDATE world_pulse_articles SET image_url=%s, image_source=%s,
                        image_credit=%s, image_credit_url=%s, image_provider_url=%s,
                        image_license_url=%s, image_rights_checked=%s, image_checked_at=%s
                    WHERE source_url=%s AND is_demo=FALSE
                """, (
                    item.get("image_url", ""), item.get("image_source", "none"), item.get("image_credit", ""),
                    item.get("image_credit_url", ""), item.get("image_provider_url", ""), item.get("image_license_url", ""),
                    bool(item.get("image_rights_checked")), item.get("image_checked_at"), item.get("source_url", "")
                ))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logger.warning("Could not persist image backfill", exc_info=True)
        return False
    finally:
        conn.close()


def _audit_admin(actor: str, action: str, target: str, details: str = "") -> None:
    if not _ensure_schema():
        return
    conn = _connect_db()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO world_pulse_admin_audit(actor, action, target, details) VALUES (%s,%s,%s,%s)",
                        (actor[:120], action[:80], target[:500], details[:1500]))
        conn.commit()
    except Exception:
        conn.rollback()
        logger.warning("Could not write admin audit log", exc_info=True)
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
            slug, source_url, source_domain, category, source_name, image_url,
            image_source, image_credit, image_credit_url, image_provider_url, image_license_url, image_rights_checked, image_checked_at,
            title_ar, title_en, summary_ar, summary_en, content_ar, content_en,
            published_at, fetched_at, read_minutes, original_language, is_demo, ai_enriched
        ) VALUES (
            %(slug)s, %(source_url)s, %(source_domain)s, %(category)s, %(source_name)s, %(image_url)s,
            %(image_source)s, %(image_credit)s, %(image_credit_url)s, %(image_provider_url)s, %(image_license_url)s, %(image_rights_checked)s, %(image_checked_at)s,
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s,
            %(content_ar)s, %(content_en)s, %(published_at)s, NOW(),
            %(read_minutes)s, %(original_language)s, FALSE, %(ai_enriched)s
        )
        ON CONFLICT (source_url) DO UPDATE SET
            source_domain = CASE WHEN EXCLUDED.source_domain <> '' THEN EXCLUDED.source_domain ELSE world_pulse_articles.source_domain END,
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
            summary_ar = CASE WHEN (EXCLUDED.ai_enriched IS TRUE OR world_pulse_articles.summary_ar = '') AND EXCLUDED.summary_ar <> '' THEN EXCLUDED.summary_ar ELSE world_pulse_articles.summary_ar END,
            summary_en = CASE WHEN (EXCLUDED.ai_enriched IS TRUE OR world_pulse_articles.summary_en = '') AND EXCLUDED.summary_en <> '' THEN EXCLUDED.summary_en ELSE world_pulse_articles.summary_en END,
            content_ar = CASE WHEN (EXCLUDED.ai_enriched IS TRUE OR world_pulse_articles.content_ar = '') AND EXCLUDED.content_ar <> '' THEN EXCLUDED.content_ar ELSE world_pulse_articles.content_ar END,
            content_en = CASE WHEN (EXCLUDED.ai_enriched IS TRUE OR world_pulse_articles.content_en = '') AND EXCLUDED.content_en <> '' THEN EXCLUDED.content_en ELSE world_pulse_articles.content_en END,
            published_at = COALESCE(EXCLUDED.published_at, world_pulse_articles.published_at),
            fetched_at = NOW(),
            read_minutes = GREATEST(EXCLUDED.read_minutes, 1),
            original_language = EXCLUDED.original_language,
            ai_enriched = world_pulse_articles.ai_enriched OR EXCLUDED.ai_enriched
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
    """Score relevance conservatively while allowing a strong entity match in a long headline."""
    title_tokens = _image_tokens(title)
    if not title_tokens:
        return 0.0
    image_tokens = _image_tokens(description)
    overlap = title_tokens & image_tokens
    overlap_count = len(overlap)
    overlap_ratio = overlap_count / max(1, len(title_tokens))
    if overlap_count >= 2 and overlap_ratio >= 0.10:
        return overlap_ratio + min(overlap_count, 4) * 0.04
    # Long news headlines often contain one distinctive place/person/product name.
    # A single meaningful overlap is permitted because the image caption will say illustrative.
    if overlap_count == 1 and any(len(token) >= 5 for token in overlap):
        return max(0.14, overlap_ratio) + 0.04
    return 0.0


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


def _search_commons_image(title: str, lang: str, category: str = "world") -> dict[str, Any]:
    """Use only file-level PD/CC0/plain CC BY licences; category results are illustrations."""
    title = _clean_text(title, 240)
    category_queries = {
        "politics": "parliament government diplomacy",
        "economy": "stock market economy business finance",
        "technology": "computer technology artificial intelligence electronics",
        "gaming": "video games gaming controller console",
        "sports": "football sports stadium athletics",
        "science": "science laboratory space telescope research",
        "culture": "art museum books theatre culture",
        "world": "earth city world map international",
    }
    category_query = category_queries.get(category, category_queries["world"])
    ordered_words = [w for w in re.findall(r"[\w\u0600-\u06ff]{3,}", title) if w.casefold() not in _IMAGE_STOPWORDS]
    primary_query = title if len(title) <= 120 else " ".join(ordered_words[:4])
    queries = []
    for query in (primary_query, category_query):
        query = _clean_text(query, 180)
        if query and query.casefold() not in {q.casefold() for q in queries}:
            queries.append(query)
    if not queries:
        return {}

    best_story: tuple[float, dict[str, Any]] | None = None
    best_illustration: tuple[float, dict[str, Any]] | None = None
    for query_index, query in enumerate(queries):
        params = {
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrnamespace": 6, "gsrlimit": 30, "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime", "iiurlwidth": 1400,
            "format": "json", "formatversion": 2,
        }
        request_obj = Request(
            "https://commons.wikimedia.org/w/api.php?" + urlencode(params),
            headers={"User-Agent": "WorldPulseNews/1.5 (licensed image finder; Wikimedia Commons API; contact site owner)"},
        )
        try:
            with urlopen(request_obj, timeout=IMAGE_SEARCH_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read(2_000_000).decode("utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("Wikimedia Commons image search failed for query %r: %s", query, exc)
            continue
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
            page_title = str(page.get("title", ""))
            if re.search(r"(?i)\b(logo|icon|wordmark|commons-logo|flag icon|map icon|watermark)\b", page_title):
                continue
            ext = info.get("extmetadata") or {}
            license_short = _clean_text((ext.get("LicenseShortName") or {}).get("value", ""), 100).casefold()
            raw_license_url = html.unescape(str((ext.get("LicenseUrl") or {}).get("value", ""))).strip()
            if raw_license_url.lower().startswith("http://creativecommons.org/"):
                raw_license_url = "https://" + raw_license_url[len("http://"):]
            license_url = _https_url(raw_license_url, {"creativecommons.org"})
            license_path = urlparse(license_url).path.casefold() if license_url else ""
            license_ok = bool(
                re.search(r"/publicdomain/mark/1\.0/?$", license_path)
                or re.search(r"/publicdomain/zero/1\.0/?$", license_path)
                or re.search(r"/licenses/by/(?:1\.0|2\.0|2\.5|3\.0|4\.0)/?$", license_path)
            )
            forbidden = any(term in license_short for term in (
                "noncommercial", "non-commercial", "no derivatives", "no-derivatives", "by-nc", "by-nd", "by-sa", "share alike"
            ))
            if not license_ok or forbidden:
                continue
            image_url = _https_url(info.get("thumburl") or info.get("url"), {"wikimedia.org", "wikipedia.org"})
            if not image_url or _is_image_blocked(image_url):
                continue

            desc = _clean_text((ext.get("ImageDescription") or {}).get("value", ""), 1000)
            file_text = page_title + " " + desc
            score = _image_match_score(title, file_text) if title else 0.0
            illustrative = query_index > 0 or score <= 0
            if illustrative:
                # For an illustration, relevance is assessed against category vocabulary;
                # it is explicitly captioned as illustrative and not as the event photo.
                score = _image_match_score(category_query, file_text)
                if score <= 0:
                    continue
            elif score < 0.14:
                continue

            file_page_url = "https://commons.wikimedia.org/wiki/" + quote(page_title.replace(" ", "_"), safe=":_()!,.'-")
            artist = _clean_text((ext.get("Artist") or {}).get("value", ""), 180)
            result = {
                "image_url": image_url,
                "image_source": "wikimedia_relevant",
                "image_credit": artist or "Wikimedia Commons",
                "image_credit_url": file_page_url,
                "image_provider_url": file_page_url,
                "image_license_url": license_url,
                "image_checked_at": datetime.now(timezone.utc),
                "image_rights_checked": True,
            }
            bucket = "illustration" if illustrative else "story"
            current = best_illustration if bucket == "illustration" else best_story
            if current is None or score > current[0]:
                if bucket == "illustration":
                    best_illustration = (score, result)
                else:
                    best_story = (score, result)
        # A good story-specific image wins. Otherwise continue to the category illustration query.
        if query_index == 0 and best_story and best_story[0] >= 0.18:
            return best_story[1]
    if best_story and best_story[0] >= 0.18:
        return best_story[1]
    if best_illustration:
        return best_illustration[1]
    return best_story[1] if best_story else {}

def _search_pexels_image(title: str) -> dict[str, str]:
    """Use Pexels only through its official API and retain required platform/photographer attribution."""
    if not _image_provider_enabled("pexels") or not PEXELS_API_KEY or not title:
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
            if not image_url or not photo_page or not photographer or _is_image_blocked(image_url):
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
    if not _image_provider_enabled("unsplash") or not UNSPLASH_ACCESS_KEY or not title:
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
            if not image_url or not photo_page or not photographer or _is_image_blocked(image_url):
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
    if not _image_provider_enabled("presskit"):
        return {}
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
        if _is_image_blocked(image_url):
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


def _search_any_reusable_image(title: str, lang: str = "en", category: str = "world") -> dict[str, Any]:
    """Prefer story-related media; only then use clearly illustrative category imagery."""
    category_queries = {
        "politics": "parliament government diplomacy",
        "economy": "stock market business economy",
        "technology": "computer technology electronics",
        "gaming": "video games gaming controller",
        "sports": "football sports stadium",
        "science": "science laboratory space",
        "culture": "art books museum culture",
        "world": "earth city international",
    }
    direct_finders = (
        ("wikimedia", lambda: _search_commons_image(title, lang, category)),
        ("presskit", lambda: _search_approved_presskit_image(title, category)),
        ("pexels", lambda: _search_pexels_image(title)),
        ("unsplash", lambda: _search_unsplash_image(title)),
    )
    for provider, finder in direct_finders:
        if not _image_provider_enabled(provider):
            continue
        try:
            result = finder()
            if result and result.get("image_url") and not _is_image_blocked(str(result["image_url"])):
                return result
        except Exception:
            logger.debug("Image provider %s failed", provider, exc_info=True)

    # If a specific match is unavailable, query an image platform for a category illustration.
    # This is labelled "illustrative image" in the card and is never claimed to depict the event.
    topic = category_queries.get(category, category_queries["world"])
    for provider, finder in (("pexels", _search_pexels_image), ("unsplash", _search_unsplash_image)):
        if not _image_provider_enabled(provider):
            continue
        try:
            result = finder(topic)
            if result and result.get("image_url") and not _is_image_blocked(str(result["image_url"])):
                return result
        except Exception:
            logger.debug("Category illustration fallback failed for %s", provider, exc_info=True)
    return {}


def _resolve_article_image(raw: dict[str, Any]) -> dict[str, Any]:
    existing = str(raw.get("image_url") or "").strip()
    source = str(raw.get("image_source") or "")
    if (existing and source in TRUSTED_REUSABLE_IMAGE_SOURCES
            and raw.get("image_rights_checked") is True and existing not in LEGACY_IMAGE_URLS
            and not _is_image_blocked(existing)):
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
        input_provider = _image_source_provider(input_source)
        if (input_source in TRUSTED_REUSABLE_IMAGE_SOURCES and item.get("image_url")
                and (not input_provider or _image_provider_enabled(input_provider))
                and not _is_image_blocked(str(item.get("image_url") or ""))
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
        cached_provider = _image_source_provider(cached_source)
        if (cached and cached.get("image_url") and cached_source in TRUSTED_REUSABLE_IMAGE_SOURCES
                and (not cached_provider or _image_provider_enabled(cached_provider))
                and str(cached.get("image_url")) not in LEGACY_IMAGE_URLS
                and not _is_image_blocked(str(cached.get("image_url") or ""))):
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
    with _IMAGE_DIAGNOSTICS_LOCK:
        _IMAGE_DIAGNOSTICS["lookups_started"] += len(pending)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_resolve_article_image, item): item for item in pending}
        for future in as_completed(futures):
            item = futures[future]
            try:
                item.update(future.result())
                with _IMAGE_DIAGNOSTICS_LOCK:
                    if item.get("image_url") and item.get("image_rights_checked") is True:
                        _IMAGE_DIAGNOSTICS["images_found"] += 1
                        _IMAGE_DIAGNOSTICS["last_success_at"] = datetime.now(timezone.utc).isoformat()
                        _IMAGE_DIAGNOSTICS["last_source"] = str(item.get("image_source") or "")
                        _IMAGE_DIAGNOSTICS["last_problem"] = ""
                    else:
                        _IMAGE_DIAGNOSTICS["images_not_found"] += 1
                        _IMAGE_DIAGNOSTICS["last_problem"] = "No compliant relevant image returned; the placeholder is retained."
            except Exception as exc:
                logger.exception("Could not resolve image for article %s", item.get("source_url"))
                with _IMAGE_DIAGNOSTICS_LOCK:
                    _IMAGE_DIAGNOSTICS["lookup_errors"] += 1
                    _IMAGE_DIAGNOSTICS["last_problem"] = str(exc)[:240]
                item.update({
                    "image_url": "", "image_source": "none", "image_credit": "",
                    "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
                    "image_rights_checked": False, "image_checked_at": datetime.now(timezone.utc),
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

            source_host_raw = _url_host(source_href)
            article_host = _url_host(story_url)
            google_redirect = article_host in GOOGLE_NEWS_HOSTS
            active_host = ""

            # Prefer an explicit publisher domain from RSS metadata. Some Google News feeds
            # omit source.href, however; in that case infer only from a known source label and
            # only to a domain already allowlisted for this category/language.
            if source_host_raw and source_host_raw not in GOOGLE_NEWS_HOSTS:
                active_host = next((d for d in active_domains if _domain_matches_host(source_host_raw, d)), "")
                if not active_host:
                    continue
            elif article_host and article_host not in GOOGLE_NEWS_HOSTS:
                active_host = next((d for d in active_domains if _domain_matches_host(article_host, d)), "")
            if not active_host:
                active_host = _infer_source_domain(publisher, active_domains)
            if not active_host:
                continue

            # For direct article links, make sure the URL itself agrees with the publisher.
            # Google News redirect URLs are allowed only when the publisher was identified above.
            if not google_redirect and article_host and not _domain_matches_host(article_host, active_host):
                continue

            license_urls = (source_href, story_url, "https://" + active_host + "/")
            if _publisher_requires_license(publisher, license_urls):
                logger.debug("Skipping publisher pending written permission: %s (%s)", publisher, active_host)
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
                "source_domain": active_host,
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
    original_lang = raw.get("original_language", "ar" if _looks_arabic(title) else "en")
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
        "source_domain": str(raw.get("source_domain") or ""),
        "category": raw["category"],
        "source_name": raw.get("source_name") or "",
        **image_fields,
        "title_ar": title if original_lang == "ar" else "",
        "title_en": title if original_lang == "en" else "",
        # Raw RSS excerpts are discovery metadata for the editor, not display content.
        # If Gemini fails, show a transparent source-link note instead of republishing feed copy.
        "summary_ar": "",
        "summary_en": "",
        "content_ar": "",
        "content_en": "",
        "published_at": raw.get("published_at"),
        "read_minutes": 1,
        "original_language": original_lang,
        "is_demo": False,
        "ai_enriched": False,
        "fetched_at": datetime.now(timezone.utc),
    }


def _summary_norm(value: str) -> str:
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", str(value or "").casefold()).strip()


def _summary_is_distinct(title: str, summary: str) -> bool:
    title = str(title or "").strip()
    summary = str(summary or "").strip()
    if len(summary.split()) < 12:
        return False
    title_norm, summary_norm = _summary_norm(title), _summary_norm(summary)
    if not title_norm or not summary_norm:
        return False
    if difflib.SequenceMatcher(None, title_norm, summary_norm).ratio() >= 0.72:
        return False
    title_tokens = set(title_norm.split())
    summary_tokens = set(summary_norm.split())
    if len(title_tokens) >= 3 and len(title_tokens & summary_tokens) / len(title_tokens) >= 0.88:
        return False
    return True


def _text_matches_language(value: str, lang: str) -> bool:
    """Avoid mixing the source-language teaser into the other language's summary slot."""
    letters = [char for char in str(value or "") if char.isalpha()]
    if not letters:
        return False
    arabic = sum("\u0600" <= char <= "\u06ff" for char in letters)
    latin = sum(("a" <= char.casefold() <= "z") for char in letters)
    if lang == "ar":
        return arabic >= max(3, int(len(letters) * 0.18))
    return latin >= max(6, int(len(letters) * 0.45)) and arabic < len(letters) * 0.25


def _fallback_summary(title: str, candidate: str, excerpt: str, body: str, lang: str) -> str:
    """Choose a distinct, language-consistent summary from available source text."""
    sentences = re.split(r"(?<=[.!?؟])\s+", str(body or "").strip())
    body_lead = " ".join(sentences[:2]).strip()
    # Only use text produced by the editorial model (candidate/body). The RSS excerpt is
    # supplied to the function for context, but is never displayed verbatim as a fallback.
    for value in (candidate, body_lead):
        value = _clean_text(value, 800)
        if _summary_is_distinct(title, value) and _text_matches_language(value, lang):
            return value
    if lang == "ar":
        return "المعلومات المتاحة في موجز المصدر لا تكفي لتأكيد تفاصيل إضافية عن هذا التطور. راجع المصدر الأصلي لمعرفة ما أُعلن تحديدًا، وما إذا كانت هناك شروط أو نتائج أو خطوات لاحقة لم يذكرها الموجز."
    return "The available feed excerpt does not establish enough detail to expand this report responsibly. Consult the original source for the exact announcement and any conditions, outcomes, or follow-up steps that the excerpt does not describe."


def _translate_batch(raw_articles: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """Create concise original bilingual briefings in small batches to avoid JSON truncation."""
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
                "title": raw_articles[i].get("original_title", "")[:350],
                "source": raw_articles[i].get("source_name", "")[:120],
                "source_url": raw_articles[i].get("source_url", "")[:500],
                # This is a short RSS metadata excerpt, not the full publisher article.
                "excerpt": raw_articles[i].get("original_summary", "")[:700],
            }
            for i in range(batch_start, batch_end)
        ]
        prompt = f"""You are the bilingual editorial desk for World Pulse. Turn the provided news headline and short RSS excerpt into an original, useful, source-attributed briefing.
Copyright and factual accuracy:
- Treat the headline and excerpt only as limited discovery metadata; do not fetch, reconstruct, or copy the publisher's full article.
- Do not copy distinctive wording or long phrases. Do not claim independent verification.
- Use only facts explicitly supported by the headline/excerpt. Never invent details, numbers, quotations, names, causes, or consequences.
- Separate confirmed information from context/analysis, and clearly identify when the short excerpt does not support more detail.

CRITICAL EXECUTIVE SUMMARY RULE:
- summary_ar and summary_en must NOT repeat or merely paraphrase the headline. The headline is only a label, not an executive summary.
- Write an informative 2–3 sentence summary. Aim for 40–75 Arabic words and 35–65 English words only if the excerpt genuinely supports that much detail.
- Begin with the reported development, not the headline's wording. Include specific who/what/where/when details only when the input states them.
- If the excerpt is too short, be concise and explicitly avoid claiming details not present. Never inflate a thin source into a long story.

ARTICLE BODY:
- content_ar and content_en should add useful context that is not just a repeat of the executive summary, in 1–3 short paragraphs.
- If the source supports no additional facts, say what specific information is missing and direct readers to the original source. Do not use the raw RSS excerpt as the article body.
- Keep all wording original and proportionate to the facts in the input.

Return valid JSON only: {{"stories":[...]}}. Each story must preserve its original integer index and include exactly index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en. Use natural Modern Standard Arabic and neutral international English. No Markdown fences or text outside JSON. Use blank lines between body paragraphs.
Input JSON: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            if client is None:
                client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
            response_text = (response.text or "").strip()
            response_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.I)
            parsed = json.loads(response_text)
            stories = parsed.get("stories", []) if isinstance(parsed, dict) else parsed
            if not isinstance(stories, list):
                raise ValueError("Gemini returned an unexpected JSON structure")

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
                    body = re.sub(r"(?i)<br\s*/?>|</p\s*>|</div\s*>|</li\s*>", "\n\n", body)
                    body = re.sub(r"<[^>]+>", " ", body)
                    body = re.sub(r"[ \t\xa0]+", " ", body)
                    body = re.sub(r" *\n *", "\n", body)
                    body = re.sub(r"\n{3,}", "\n\n", body).strip()
                    fields[key] = body[:12000]

                if not fields.get("title_ar") or not fields.get("title_en"):
                    continue
                raw = raw_articles[index]
                original_lang = str(raw.get("original_language") or "en")
                excerpt = _clean_text(raw.get("original_summary", ""), 700) if original_lang in {"ar", "en"} else ""
                for summary_lang in ("ar", "en"):
                    fields[f"summary_{summary_lang}"] = _fallback_summary(
                        fields.get(f"title_{summary_lang}", ""),
                        fields.get(f"summary_{summary_lang}", ""),
                        excerpt if summary_lang == original_lang else "",
                        fields.get(f"content_{summary_lang}", ""),
                        summary_lang,
                    )
                result[index] = fields
        except Exception as exc:
            # A failed batch must not discard successful work from other batches.
            logger.warning("Gemini editorial batch %s-%s failed: %s", batch_start, batch_end - 1, exc)
            continue
    return result

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


def _stored_article_for_image_backfill(row: dict[str, Any]) -> dict[str, Any]:
    title_en = str(row.get("title_en") or "").strip()
    title_ar = str(row.get("title_ar") or "").strip()
    original_language = "en" if title_en else "ar"
    return {
        "slug": row.get("slug") or _slug_for_url(str(row.get("source_url") or "")),
        "source_url": row.get("source_url", ""),
        "source_domain": row.get("source_domain", ""),
        "category": row.get("category", "world"),
        "source_name": row.get("source_name", ""),
        "image_url": "", "image_source": "none", "image_credit": "",
        "image_credit_url": "", "image_provider_url": "", "image_license_url": "",
        "image_rights_checked": False, "image_checked_at": row.get("image_checked_at"),
        "original_title": title_en or title_ar,
        "original_summary": str(row.get("summary_en") or row.get("summary_ar") or ""),
        "original_language": original_language,
        "image_search_title": title_en or title_ar,
        "_database_image_backfill": True,
        "_stored_row": row,
    }


def _refresh_news_job() -> None:
    global _REFRESHING, _LAST_REFRESH_SUCCESS, _LAST_REFRESH_AT, _LAST_REFRESH_STATE, _LAST_REFRESH_ERROR
    try:
        with _STATE_LOCK:
            _LAST_REFRESH_STATE = "running"
            _LAST_REFRESH_ERROR = ""

        raw_articles = _collect_rss_articles()
        fresh_count = len(raw_articles)
        fresh_urls = {str(item.get("source_url", "")) for item in raw_articles}

        # Repair older executive summaries gradually when they substantially repeat a headline.
        editorial_backfills: list[dict[str, Any]] = []
        if MAX_EDITORIAL_BACKFILL_PER_REFRESH > 0 and GEMINI_API_KEY and genai is not None and types is not None:
            for stored in _db_fetch_articles_needing_editorial(MAX_EDITORIAL_BACKFILL_PER_REFRESH):
                source_url = str(stored.get("source_url") or "")
                if source_url and source_url not in fresh_urls:
                    editorial_backfills.append(_stored_article_for_editorial_backfill(stored))
                    fresh_urls.add(source_url)
                if len(editorial_backfills) >= MAX_EDITORIAL_BACKFILL_PER_REFRESH:
                    break

        # Translate both new discovery items and the small editorial-backfill batch.
        translation_inputs = raw_articles + editorial_backfills
        translations = _translate_batch(translation_inputs) if translation_inputs else {}
        for index, raw in enumerate(raw_articles):
            translated = translations.get(index, {})
            raw["image_search_title"] = translated.get("title_en", "") or raw.get("original_title", "")

        # Old records whose URLs were cleared during strict licence checks are retried gradually.
        known_urls = {str(item.get("source_url", "")) for item in translation_inputs}
        image_backfills: list[dict[str, Any]] = []
        if MAX_IMAGE_BACKFILL_PER_REFRESH > 0:
            for stored in _db_fetch_articles_needing_images(MAX_IMAGE_BACKFILL_PER_REFRESH):
                source_url = str(stored.get("source_url") or "")
                if source_url and source_url not in known_urls:
                    image_backfills.append(_stored_article_for_image_backfill(stored))
                    known_urls.add(source_url)
                if len(image_backfills) >= MAX_IMAGE_BACKFILL_PER_REFRESH:
                    break

        if not raw_articles and not editorial_backfills and not image_backfills:
            logger.warning("RSS refresh returned no stories; existing records remain available")
            with _STATE_LOCK:
                _LAST_REFRESH_STATE = "error"
                _LAST_REFRESH_ERROR = "No RSS stories or backfill candidates returned"
            return

        # Image work is independent from AI text repair and never stores publisher thumbnails.
        image_work = raw_articles + image_backfills
        _enrich_article_images(image_work)
        _avoid_repeated_news_photos(image_work)

        # Keep prior saved/edited copy available in memory if a later Gemini call fails.
        # Otherwise the memory cache would shadow the richer database row with a short RSS teaser.
        existing_by_url = {str(row.get("source_url") or ""): row for row in _db_fetch_all() if row.get("source_url")}
        existing_by_url.update({str(key): value for key, value in _MEMORY_ARTICLES.items() if key})
        ready: list[dict[str, Any]] = []
        text_fields = ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en")
        for index, raw in enumerate(raw_articles):
            article = _base_article(raw)
            if index in translations:
                article.update(translations[index])
                article["ai_enriched"] = True
            else:
                previous = existing_by_url.get(str(article.get("source_url") or ""), {})
                for key in text_fields:
                    if previous.get(key):
                        article[key] = previous[key]
                article["ai_enriched"] = bool(previous.get("ai_enriched"))
            article["read_minutes"] = _reading_minutes(article)
            ready.append(article)
            _MEMORY_ARTICLES[article["source_url"]] = article

        editorial_updates: list[dict[str, Any]] = []
        editorial_offset = len(raw_articles)
        for index, raw in enumerate(editorial_backfills, start=editorial_offset):
            translated = translations.get(index)
            if not translated:
                continue
            updated = dict(translated)
            updated["source_url"] = raw["source_url"]
            updated["read_minutes"] = _reading_minutes(updated)
            editorial_updates.append(updated)
            stored_row = dict(raw.get("_stored_row") or {})
            if stored_row:
                stored_row.update(updated)
                stored_row["ai_enriched"] = True
                _MEMORY_ARTICLES[raw["source_url"]] = stored_row

        saved = _db_upsert_many(ready) if ready else False
        editorial_saved = _db_update_editorial_many(editorial_updates) if editorial_updates else False
        backfill_saved = _db_update_images_many(image_backfills) if image_backfills else False

        # Keep in-memory image metadata aligned without overwriting existing article prose.
        for raw in image_backfills:
            stored = dict(raw.get("_stored_row") or {})
            if stored and stored.get("source_url"):
                for key in ("image_url", "image_source", "image_credit", "image_credit_url", "image_provider_url", "image_license_url", "image_rights_checked", "image_checked_at"):
                    stored[key] = raw.get(key)
                _MEMORY_ARTICLES[str(stored["source_url"])] = stored

        _LAST_REFRESH_SUCCESS = time.monotonic()
        _LAST_REFRESH_AT = datetime.now(timezone.utc)
        _LAST_REFRESH_STATE = "success" if (saved or editorial_saved or backfill_saved or not ready) else "memory_only"
        logger.info(
            "News refresh complete: fresh=%s translated=%s saved=%s editorial_backfill=%s editorial_saved=%s image_backfill=%s image_saved=%s",
            fresh_count, len(translations), saved, len(editorial_backfills), editorial_saved,
            len(image_backfills), backfill_saved
        )
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



def _remove_headline_only_body(title: str, content: str) -> str:
    """Drop a repeated headline/first headline line from the article body."""
    content = str(content or "").strip()
    if not content:
        return ""
    title_norm = _summary_norm(title)
    if not title_norm:
        return content
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
    if not paragraphs:
        return ""
    first_norm = _summary_norm(paragraphs[0])
    if first_norm:
        similarity = difflib.SequenceMatcher(None, title_norm, first_norm).ratio()
        title_tokens, first_tokens = set(title_norm.split()), set(first_norm.split())
        overlap = len(title_tokens & first_tokens) / max(1, min(len(title_tokens), len(first_tokens)))
        headline_like = similarity >= 0.72 or (overlap >= 0.90 and len(first_tokens) <= max(len(title_tokens) * 1.8, len(title_tokens) + 4))
        if headline_like and len(first_norm) <= max(220, len(title_norm) * 2):
            paragraphs = paragraphs[1:]
    remaining = "\n\n".join(paragraphs).strip()
    remaining_norm = _summary_norm(remaining)
    if remaining_norm and (difflib.SequenceMatcher(None, title_norm, remaining_norm).ratio() >= 0.78):
        return ""
    return remaining

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
          or story.get("image_url") in LEGACY_IMAGE_URLS
          or _is_image_blocked(str(story.get("image_url") or ""))
          or (_image_source_provider(str(story.get("image_source") or "")) and not _image_provider_enabled(_image_source_provider(str(story.get("image_source") or ""))))):
        story["image_url"] = ""
        story["image_source"] = "none"
        story["image_credit"] = ""
        story["image_credit_url"] = ""
        story["image_provider_url"] = ""
        story["image_license_url"] = ""
    alternate_lang = "en" if lang == "ar" else "ar"
    display_lang = lang if story.get(f"title_{lang}") else alternate_lang
    story["title"] = story.get(f"title_{display_lang}") or story.get(f"title_{alternate_lang}") or ""
    editorial_copy_trusted = bool(story.get("ai_enriched"))
    stored_summary = story.get(f"summary_{display_lang}") or story.get(f"summary_{alternate_lang}") or ""
    stored_content = story.get(f"content_{display_lang}") or story.get(f"content_{alternate_lang}") or ""
    # Older builds stored raw RSS excerpts in the same columns. Until a row has been
    # re-edited by Gemini, do not display those unverified text fields.
    story["summary"] = stored_summary if editorial_copy_trusted else ""
    raw_content = stored_content if editorial_copy_trusted else ""
    summary_ok = editorial_copy_trusted and _summary_is_distinct(story["title"], story["summary"]) and _text_matches_language(story["summary"], display_lang)
    if not summary_ok:
        story["summary"] = _fallback_summary(
            story["title"], story["summary"] if editorial_copy_trusted else "", "",
            raw_content if editorial_copy_trusted else "", display_lang
        )
    # Remove a headline-only body before summary deduplication so punctuation in a
    # headline (especially Arabic question marks) cannot leave a trailing fragment.
    content_without_headline = _remove_headline_only_body(story["title"], raw_content)
    story["content"] = _remove_headline_only_body(
        story["title"], _normalise_summary_body(story["summary"], content_without_headline)
    )
    story["ai_enriched"] = bool(story.get("ai_enriched")) and summary_ok
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


def _article_source_is_enabled(row: dict[str, Any]) -> bool:
    catalog_domains = {d for by_lang in CATEGORY_SOURCE_DOMAINS.values() for by_lang_domains in by_lang.values() for d in by_lang_domains}
    domain = str(row.get("source_domain") or "").lower().strip()
    if not domain:
        domain = _url_host(str(row.get("source_url") or ""))
    if domain in GOOGLE_NEWS_HOSTS or not domain:
        inferred = _infer_source_domain(str(row.get("source_name") or ""), catalog_domains)
        if not inferred:
            # Fail closed for legacy redirect URLs whose publisher cannot be identified.
            return False
        domain = inferred
    matched_domain = next((d for d in catalog_domains if _domain_matches_host(domain, d)), "")
    if not matched_domain:
        return False
    return _source_domain_enabled(matched_domain) and not _domain_requires_license(matched_domain)


def _get_display_stories(lang: str) -> list[dict[str, Any]]:
    live = [row for row in _all_live_articles() if not row.get("is_demo") and row.get("source_url") and (row.get(f"title_{lang}") or row.get(f"title_{'en' if lang == 'ar' else 'ar'}")) and row.get("category") in CATEGORY_NAMES and _article_source_is_enabled(row)]
    live.sort(key=lambda item: item.get("published_at") or item.get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return [_normalise_story(row, lang) for row in live]


def _find_article(slug: str, lang: str) -> dict[str, Any] | None:
    for row in _all_live_articles():
        if row.get("is_demo"):
            continue
        if row.get("slug") == slug and row.get("source_url") and (row.get(f"title_{lang}") or row.get(f"title_{'en' if lang == 'ar' else 'ar'}")) and _article_source_is_enabled(row):
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


def _admin_auth_response():
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return Response("Admin panel disabled. Configure ADMIN_USERNAME and ADMIN_PASSWORD in the hosting environment.", 503, {"Content-Type": "text/plain; charset=utf-8"})
    auth = request.authorization
    valid = bool(auth and secrets.compare_digest(auth.username or "", ADMIN_USERNAME)
                 and secrets.compare_digest(auth.password or "", ADMIN_PASSWORD))
    if not valid:
        return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="World Pulse Admin", charset="UTF-8"', "Cache-Control": "no-store"})
    if not _ensure_schema():
        return Response("Admin panel requires a working PostgreSQL connection.", 503, {"Content-Type": "text/plain; charset=utf-8"})
    return None


def _source_catalog_rows() -> list[dict[str, Any]]:
    controls = _load_source_controls(force=True)
    result: dict[str, dict[str, Any]] = {}
    for category, langs in CATEGORY_SOURCE_DOMAINS.items():
        for lang, domains in langs.items():
            for domain in domains:
                row = result.setdefault(domain, {
                    "domain": domain, "categories": set(), "languages": set(),
                    "restricted": _is_restricted_source_domain(domain),
                })
                row["categories"].add(CATEGORY_NAMES.get(category, {}).get("ar", category))
                row["languages"].add("العربية" if lang == "ar" else "English")
    configured = _configured_licensed_domains()
    for domain, row in result.items():
        control = controls.get(domain, {})
        row["enabled"] = bool(control.get("enabled", (not row["restricted"]) or domain in configured))
        row["license_verified"] = bool(control.get("license_verified", domain in configured))
        if row["restricted"] and not (row["license_verified"] and (row["enabled"] or domain in configured)):
            row["enabled"] = False
        row["notes"] = str(control.get("notes") or "")
        row["categories"] = ", ".join(sorted(row["categories"]))
        row["languages"] = " / ".join(sorted(row["languages"]))
    return sorted(result.values(), key=lambda item: (not item["enabled"], item["domain"]))


def _admin_provider_rows() -> list[dict[str, Any]]:
    controls = _load_image_admin_controls(force=True).get("providers", {})
    labels = {
        "wikimedia": ("Wikimedia Commons", True, "Public Domain Mark / CC0 / CC BY فقط"),
        "presskit": ("Press-kit assets", True, "صور راجعتها وأضفتها يدويًا إلى القائمة المعتمدة"),
        "pexels": ("Pexels API", bool(PEXELS_API_KEY), "يتطلب PEXELS_API_KEY صالحًا"),
        "unsplash": ("Unsplash API", bool(UNSPLASH_ACCESS_KEY), "يتطلب UNSPLASH_ACCESS_KEY صالحًا"),
    }
    result = []
    for provider, (label, configured, note) in labels.items():
        enabled = bool(controls.get(provider, configured)) and configured
        result.append({"provider": provider, "label": label, "configured": configured, "enabled": enabled, "note": note})
    return result


def _admin_image_rows() -> list[dict[str, Any]]:
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT slug, source_url, title_ar, title_en, category, source_name, image_url,
                       image_source, image_credit, image_credit_url, image_provider_url, image_license_url,
                       image_rights_checked, image_checked_at
                FROM world_pulse_articles
                WHERE is_demo=FALSE AND image_url<>'' AND image_rights_checked=TRUE
                ORDER BY image_checked_at DESC NULLS LAST LIMIT 80
            """)
            rows = [dict(row) for row in cur.fetchall()]
        blocked = _load_image_admin_controls(force=True).get("blocked", set())
        for row in rows:
            row["title"] = row.get("title_ar") or row.get("title_en") or row.get("source_url")
            row["blocked"] = any(_image_identity(str(row.get("image_url") or "")) == _image_identity(str(item)) for item in blocked)
        return rows
    except Exception:
        logger.warning("Could not load images for admin panel", exc_info=True)
        return []
    finally:
        conn.close()


def _admin_blocked_image_rows() -> list[dict[str, Any]]:
    conn = _connect_db()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT image_url, reason, updated_at FROM world_pulse_image_controls WHERE blocked=TRUE ORDER BY updated_at DESC LIMIT 100")
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.warning("Could not load blocked images", exc_info=True)
        return []
    finally:
        conn.close()


def _admin_csrf_valid() -> bool:
    saved = str(session.get("admin_csrf") or "")
    submitted = str(request.form.get("csrf_token") or "")
    return bool(saved and submitted and secrets.compare_digest(saved, submitted))


_SEARCH_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "what", "when", "where", "who", "how", "are", "was", "were", "will", "has", "have", "had", "its", "into", "about",
    "هل", "ما", "ماذا", "كيف", "لماذا", "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "تلك", "كان", "كانت", "هو", "هي", "هل", "وما", "بعد", "قبل",
}

def _search_text_match(query: str, row: dict[str, Any]) -> int:
    normalized = _summary_norm(query)
    query_tokens = [t for t in normalized.split() if len(t) >= 2 and t not in _SEARCH_STOPWORDS]
    if not query_tokens:
        query_tokens = [t for t in normalized.split() if len(t) >= 2]
    if not query_tokens:
        return 0
    title_fields = " ".join(str(row.get(k) or "") for k in ("title_ar", "title_en")).casefold()
    other_fields = " ".join(str(row.get(k) or "") for k in ("summary_ar", "summary_en", "content_ar", "content_en", "source_name")).casefold()
    found_title = sum(1 for token in query_tokens if token.casefold() in title_fields)
    found_other = sum(1 for token in query_tokens if token.casefold() in other_fields)
    combined_norm = _summary_norm(title_fields + " " + other_fields)
    if normalized and normalized in combined_norm:
        return 10 + found_title * 3 + found_other
    # A story matching a large part of a multi-word query scores above a one-word coincidence.
    found_total = len({token for token in query_tokens if token.casefold() in title_fields or token.casefold() in other_fields})
    if found_total == 0:
        return 0
    score = found_title * 3 + found_other
    if found_total >= min(2, len(query_tokens)):
        score += 2
    return score


def _query_for_language(query: str, target_lang: str) -> str:
    """Translate search keywords when the interface language differs from the typed query."""
    query = _clean_text(query, 160).strip()
    if not query or target_lang not in {"ar", "en"}:
        return query
    query_is_arabic = _looks_arabic(query)
    if (target_lang == "ar" and query_is_arabic) or (target_lang == "en" and not query_is_arabic):
        return query
    if not GEMINI_API_KEY or genai is None or types is None:
        # Preserve user input when translation is not configured; local bilingual search still works.
        return query
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        target_name = "Modern Standard Arabic" if target_lang == "ar" else "concise international English"
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(f"Translate these news-search keywords into {target_name}. Keep names and entities accurate. "
                      "Return only a concise search query, with no quotes or explanation.\nQuery: " + query),
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=80),
        )
        translated = _clean_text(response.text or "", 160).strip(" \"'`\t\r\n")
        return translated or query
    except Exception as exc:
        logger.debug("Could not translate search keywords to %s: %s", target_lang, exc)
        return query


def _search_feed_task(query: str, category: str, lang: str) -> tuple[str, str, list[dict[str, Any]]]:
    domains = _effective_source_domains(category, lang)
    if not domains:
        return category, lang, []
    # Search core terms against approved domains. Long question-style queries contain many
    # function words and can suppress good matches if Google requires every word.
    normalized_terms = [term for term in _summary_norm(query).split() if len(term) >= 2 and term not in _SEARCH_STOPWORDS]
    if not normalized_terms:
        normalized_terms = _summary_norm(query).split()
    topic_query = " ".join(normalized_terms[:6]) or query
    domain_clause = " OR ".join(f"site:{domain}" for domain in domains[:12])
    query_text = f'({topic_query}) ({domain_clause})'
    locale = {"hl": "ar", "gl": "JO", "ceid": "JO:ar"} if lang == "ar" else {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    feed_url = "https://news.google.com/rss/search?" + urlencode({"q": query_text, **locale})
    return _parse_any_rss(feed_url, category, lang, "Google News live search")


@app.route("/admin/sources", methods=["GET", "POST"])
def admin_sources():
    global _SOURCE_CONTROL_CACHE_AT, _IMAGE_ADMIN_CACHE_AT
    auth_error = _admin_auth_response()
    if auth_error:
        return auth_error
    if not session.get("admin_csrf"):
        session["admin_csrf"] = secrets.token_urlsafe(24)
    message = ""
    action = str(request.form.get("action") or "") if request.method == "POST" else ""
    if request.method == "POST":
        if not _admin_csrf_valid():
            abort(400)
        actor = request.authorization.username if request.authorization else "admin"
        conn = _connect_db()
        if conn is None:
            message = "تعذّر الاتصال بقاعدة البيانات. / Database unavailable."
        else:
            try:
                with conn.cursor() as cur:
                    if action == "save_source":
                        domain = str(request.form.get("domain") or "").lower().strip().rstrip(".")
                        valid_domains = {d for section in CATEGORY_SOURCE_DOMAINS.values() for domains in section.values() for d in domains}
                        if domain not in valid_domains:
                            abort(400)
                        enabled_requested = request.form.get("enabled") == "on"
                        license_verified = request.form.get("license_verified") == "on"
                        notes = _clean_text(request.form.get("notes") or "", 500)
                        if _is_restricted_source_domain(domain) and enabled_requested and not license_verified and domain not in _configured_licensed_domains():
                            enabled_requested = False
                            message = f"لم يتم تفعيل {domain}: أكد مراجعة الترخيص أولًا. / Source kept disabled until licence review is confirmed."
                        cur.execute("""
                            INSERT INTO world_pulse_source_controls(domain, enabled, license_verified, notes, updated_at)
                            VALUES (%s,%s,%s,%s,NOW())
                            ON CONFLICT(domain) DO UPDATE SET enabled=EXCLUDED.enabled,
                                license_verified=EXCLUDED.license_verified, notes=EXCLUDED.notes, updated_at=NOW()
                        """, (domain, enabled_requested, license_verified, notes))
                        if not message:
                            message = f"تم حفظ إعدادات {domain}. / Saved source settings."
                        _audit_admin(actor, "save_source", domain, f"enabled={enabled_requested}; license_verified={license_verified}; notes={notes}")
                        _SOURCE_CONTROL_CACHE_AT = 0.0
                    elif action == "save_provider":
                        provider = str(request.form.get("provider") or "")
                        if provider not in {"wikimedia", "presskit", "pexels", "unsplash"}:
                            abort(400)
                        enabled = request.form.get("enabled") == "on"
                        if provider == "pexels" and not PEXELS_API_KEY:
                            enabled = False
                        if provider == "unsplash" and not UNSPLASH_ACCESS_KEY:
                            enabled = False
                        cur.execute("""
                            INSERT INTO world_pulse_image_provider_controls(provider, enabled, updated_at)
                            VALUES (%s,%s,NOW()) ON CONFLICT(provider) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=NOW()
                        """, (provider, enabled))
                        if not enabled:
                            source_key = {"wikimedia": "wikimedia_relevant", "presskit": "presskit_approved", "pexels": "pexels_api", "unsplash": "unsplash_api"}[provider]
                            cur.execute("""UPDATE world_pulse_articles SET image_url='', image_source='none', image_credit='', image_credit_url='', image_provider_url='', image_license_url='', image_rights_checked=FALSE, image_checked_at=NULL WHERE image_source=%s""", (source_key,))
                        else:
                            # Re-enable: retry previously missing images with this provider on the next refresh.
                            cur.execute("UPDATE world_pulse_articles SET image_checked_at=NULL WHERE is_demo=FALSE AND COALESCE(image_url,'')=''")
                        message = f"تم حفظ مصدر الصور {provider}. / Saved image provider settings."
                        _audit_admin(actor, "save_image_provider", provider, f"enabled={enabled}")
                        _IMAGE_ADMIN_CACHE_AT = 0.0
                    elif action == "block_image":
                        image_url = str(request.form.get("image_url") or "").strip()
                        reason = _clean_text(request.form.get("reason") or "Disabled from admin panel", 500)
                        if not _https_url(image_url):
                            abort(400)
                        cur.execute("""
                            INSERT INTO world_pulse_image_controls(image_url, blocked, reason, updated_at)
                            VALUES (%s,TRUE,%s,NOW()) ON CONFLICT(image_url) DO UPDATE SET blocked=TRUE, reason=EXCLUDED.reason, updated_at=NOW()
                        """, (image_url, reason))
                        # Match the canonical URL too, so query parameters cannot bypass a block.
                        cur.execute("SELECT source_url, image_url FROM world_pulse_articles WHERE image_url<>''")
                        matching_rows = [str(row[0]) for row in cur.fetchall() if _image_identity(str(row[1])) == _image_identity(image_url)]
                        if matching_rows:
                            cur.executemany("""UPDATE world_pulse_articles SET image_url='', image_source='none', image_credit='', image_credit_url='', image_provider_url='', image_license_url='', image_rights_checked=FALSE, image_checked_at=NULL WHERE source_url=%s""", [(story_url,) for story_url in matching_rows])
                        message = "تم إيقاف الصورة وإزالتها من الأخبار المحفوظة. / Image blocked and detached from stories."
                        _audit_admin(actor, "block_image", image_url, reason)
                        _IMAGE_ADMIN_CACHE_AT = 0.0
                    elif action == "unblock_image":
                        image_url = str(request.form.get("image_url") or "").strip()
                        cur.execute("UPDATE world_pulse_image_controls SET blocked=FALSE, updated_at=NOW() WHERE image_url=%s", (image_url,))
                        message = "تم رفع الحظر عن الصورة؛ قد يعثر عليها البحث من جديد. / Image unblocked."
                        _audit_admin(actor, "unblock_image", image_url, "")
                        _IMAGE_ADMIN_CACHE_AT = 0.0
                    else:
                        abort(400)
                conn.commit()
                _load_source_controls(force=True)
                _load_image_admin_controls(force=True)
            except HTTPException:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                logger.exception("Admin settings update failed")
                if not message:
                    message = "تعذّر حفظ التعديل. راجع سجل Render. / Failed to save settings; check Render logs."
            finally:
                conn.close()
    return render_template(
        "admin_sources.html", sources=_source_catalog_rows(), providers=_admin_provider_rows(),
        images=_admin_image_rows(), blocked_images=_admin_blocked_image_rows(),
        csrf_token=session.get("admin_csrf", ""), message=message,
        licensed_domains=sorted(_configured_licensed_domains()),
    )


@app.get("/search")
def search_news():
    _maybe_start_refresh()
    lang = current_language()
    query = _clean_text(request.args.get("q", ""), 160).strip()
    category = _clean_text(request.args.get("category", "all"), 40).lower()
    if category not in CATEGORY_NAMES and category != "all":
        category = "all"
    if not query:
        return redirect(url_for("index", lang=lang))

    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in _all_live_articles():
        if row.get("is_demo") or not _article_source_is_enabled(row):
            continue
        if category != "all" and row.get("category") != category:
            continue
        score = _search_text_match(query, row)
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("published_at") or pair[1].get("fetched_at") or datetime(1970, 1, 1, tzinfo=timezone.utc)), reverse=True)
    rows = [row for _score, row in ranked[:24]]

    # If the local archive cannot answer, query current sources. A failed match in one
    # language must not prevent trying the other language; translate only the search terms.
    if len(rows) < 4:
        categories = [category] if category != "all" else list(CATEGORY_NAMES)
        seen = {str(row.get("source_url") or "") for row in rows}

        def collect_ranked_live(search_query: str, search_lang: str) -> list[tuple[int, dict[str, Any]]]:
            discovered: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=min(8, len(categories) or 1)) as pool:
                futures = [pool.submit(_search_feed_task, search_query, cat, search_lang) for cat in categories]
                for future in as_completed(futures):
                    try:
                        _cat, _language, items = future.result()
                        discovered.extend(items)
                    except Exception:
                        logger.debug("Live search worker failed for %s/%s", search_lang, search_query, exc_info=True)
            ranked_items: list[tuple[int, dict[str, Any]]] = []
            for raw in discovered:
                source_url = str(raw.get("source_url") or "")
                if not source_url or source_url in seen:
                    continue
                score = _search_text_match(search_query, {
                    "title_ar": raw.get("original_title"), "title_en": raw.get("original_title"),
                    "summary_ar": raw.get("original_summary"), "summary_en": raw.get("original_summary"),
                    "source_name": raw.get("source_name"),
                })
                if score:
                    raw["slug"] = _slug_for_url(source_url)
                    ranked_items.append((score, raw))
                    seen.add(source_url)
            ranked_items.sort(key=lambda pair: pair[0], reverse=True)
            return ranked_items

        query_for_current_lang = _query_for_language(query, lang)
        filtered = collect_ranked_live(query_for_current_lang, lang)
        if len(rows) + len(filtered) < 4:
            other_lang = "en" if lang == "ar" else "ar"
            query_for_other_lang = _query_for_language(query, other_lang)
            fallback_results = collect_ranked_live(query_for_other_lang, other_lang)
            filtered.extend(fallback_results)
            filtered.sort(key=lambda pair: pair[0], reverse=True)
        fresh = [item for _score, item in filtered[:16]]
        if fresh:
            translations = _translate_batch(fresh)
            for idx, raw in enumerate(fresh):
                translated = translations.get(idx, {})
                raw["image_search_title"] = translated.get("title_en", "") or raw.get("original_title", "")
            # Keep live-search latency bounded while giving the top search results images when available.
            image_candidates = fresh[:min(6, MAX_IMAGE_LOOKUPS_PER_REFRESH)]
            if image_candidates:
                _enrich_article_images(image_candidates)
                _avoid_repeated_news_photos(image_candidates)
            prepared = []
            for idx, raw in enumerate(fresh):
                article_data = _base_article(raw)
                if idx in translations:
                    article_data.update(translations[idx])
                    article_data["ai_enriched"] = True
                article_data["read_minutes"] = _reading_minutes(article_data)
                prepared.append(article_data)
                _MEMORY_ARTICLES[article_data["source_url"]] = article_data
            _db_upsert_many(prepared)
            rows.extend(prepared)
            rows = rows[:24]

    stories = [_normalise_story(row, lang) for row in rows]
    return render_template(
        "index.html", page="home", stories=stories, all_story_count=len(stories),
        active_category=category, breaking_story=None, related_stories=[], article=None,
        search_query=query, is_search=True,
    )


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
        search_query="",
        is_search=False,
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
    with _IMAGE_DIAGNOSTICS_LOCK:
        image_diagnostics = dict(_IMAGE_DIAGNOSTICS)
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
        "image_diagnostics": image_diagnostics,
        "image_backfill_per_refresh": MAX_IMAGE_BACKFILL_PER_REFRESH,
        "image_lookups_per_refresh": MAX_IMAGE_LOOKUPS_PER_REFRESH,
        "enabled_source_domains": sum(len(_effective_source_domains(cat, language)) for cat in CATEGORY_NAMES for language in ("ar", "en")),
        "source_control_panel_configured": bool(ADMIN_USERNAME and ADMIN_PASSWORD),
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
