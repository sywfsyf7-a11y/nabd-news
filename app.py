"""World Pulse / نبض العالم
A small Flask news portal with expanded RSS ingestion, deep editorial Gemini analysis,
PostgreSQL persistence, and external AI fallback links.
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
AI_ANSWER_MAX_TOKENS = max(150, min(800, int(os.getenv("AI_ANSWER_MAX_TOKENS", "500"))))

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

# Expanded Direct RSS Feeds for massive source coverage
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
        ("Investing RSS", "https://www.investing.com/rss/news.rss", "en"),
    ],
    "technology": [
        ("TechCrunch", "https://techcrunch.com/feed/", "en"),
        ("The Verge", "https://www.theverge.com/rss/index.xml", "en"),
        ("AIT News", "https://aitnews.com/feed/", "ar"),
        ("عالم التقنية", "https://www.tech-wd.com/wd/feed/", "ar"),
        ("Wired", "https://www.wired.com/feed/rss", "en"),
    ],
    "gaming": [
        ("IGN", "https://www.ign.com/rss/v2/articles/feed", "en"),
        ("GameSpot", "https://www.gamespot.com/feeds/mashup/", "en"),
        ("Arab Hardware", "https://arabhardware.net/feed", "ar"),
        ("Saudi Gamer", "https://saudigamer.com/feed/", "ar"),
        ("Polygon", "https://www.polygon.com/rss/index.xml", "en"),
    ],
    "sports": [
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml", "en"),
        ("ESPN", "https://www.espn.com/espn/rss/news", "en"),
        ("FilGoal", "https://www.filgoal.com/rss/news", "ar"),
        ("Sky Sports", "https://www.skysports.com/rss/12040", "en"),
    ],
    "science": [
        ("NASA", "https://www.nasa.gov/feed/", "en"),
        ("Space.com", "https://www.space.com/feeds/all", "en"),
        ("Scientific American", "https://www.scientificamerican.com/feed/", "en"),
        ("Live Science", "https://www.livescience.com/feeds/all", "en"),
    ],
    "culture": [
        ("Literary Hub", "https://lithub.com/feed/", "en"),
        ("Al Jazeera Culture", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
        ("Artsy", "https://www.artsy.net/rss", "en"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "en"),
        ("Euronews", "https://www.euronews.com/rss?level=theme&name=news", "en"),
        ("Reuters World", "https://www.reutersagency.com/feed/?best-regions=middle-east&post_type=best", "en"),
    ],
}

PUBLISHER_SEARCH_FEEDS = {
    "politics": [
        ("Global News Agencies", "site:reuters.com OR site:apnews.com OR site:afp.com", "en"),
        ("Arabic Political Outlets", "site:alarabiya.net OR site:aljazeera.net OR site:skynewsarabia.com", "ar"),
    ],
    "economy": [
        ("Financial Outlets", "site:bloomberg.com OR site:wsj.com OR site:reuters.com", "en"),
        ("Arabic Financial News", "site:asharqbusiness.com OR site:mubasher.info", "ar"),
    ],
    "technology": [
        ("Tech Publishers", "site:theverge.com OR site:techcrunch.com OR site:wired.com", "en"),
    ],
    "gaming": [
        ("Gaming Media", "site:ign.com OR site:gamespot.com OR site:polygon.com", "en"),
    ],
    "sports": [
        ("Sports Networks", "site:espn.com OR site:skysports.com OR site:goal.com", "en"),
    ],
    "science": [
        ("Science News", "https://news.google.com/rss/search?q=science+discovery", "en"),
    ],
    "culture": [
        ("Culture Outlets", "site:artsy.net OR site:lithub.com", "en"),
    ],
    "world": [
        ("World News Feed", "site:bbc.com OR site:cnn.com OR site:euronews.com", "en"),
    ],
}

CATEGORY_IMAGES = {key: "" for key in CATEGORY_NAMES}

SAMPLE_STORIES = [
    {
        "category": "politics", "slug": "sample-politics", "source_url": "",
        "title_ar": "كيف تؤثر التحولات الجيوسياسية على استقرار الأسواق العالمية؟",
        "title_en": "How geopolitical shifts impact global market stability",
        "summary_ar": "تحليل شامل لأبعاد القرارات السياسية الدولية وكيف تتشابك خيوط الدبلوماسية مع الاقتصاد العالمي الحديث.",
        "summary_en": "Comprehensive analysis of international political decisions and their entanglement with the modern global economy.",
        "content_ar": "تتطلب قراءة الأحداث السياسية المعاصرة تجاوز مجرد نقل العناوين السريعة إلى تفكيك المصالح المتبادلة للأطراف الفاعلة.\n\n### الخلفية والسياق التاريخي\nتشير التقارير الدبلوماسية إلى أن التحالفات الدولية تمر بمرحلة إعادة صياغة جذرية، مما ينعكس مباشرة على حركة التجارة وسلاسل الإمداد العالمية.\n\n### الأبعاد والتداعيات المتوقعة\n1. إعادة توجيه الاستثمارات نحو الأسواق الأكثر استقراراً.\n2. تنشيط اتفاقيات التجارة الثنائية كبديل للتكتلات الكبرى.\n3. تصاعد أهمية الأمن السيبراني وحماية البنى التحتية الحيوية.\n\nالخلاصة أن فهم المشهد السياسي الحالي يعين صانعي القرار والمحللين على استشراف مسارات المستقبل بوعي تام.",
        "content_en": "Understanding contemporary political events requires looking beyond quick headlines to dissect the mutual interests of active stakeholders.",
    },
    {
        "category": "economy", "slug": "sample-economy", "source_url": "",
        "title_ar": "استراتيجيات التضخم والأسواق المالية: قراءة في مستقبل النمو",
        "title_en": "Inflation strategies and financial markets: Outlook on future growth",
        "summary_ar": "قراءة تحليلية لقرارات البنوك المركزية الكبرى وتأثيرات أسعار الفائدة على توجيه محفظة الاستثمارات الفردية والمؤسسية.",
        "summary_en": "Analytical review of major central bank decisions and interest rate impacts on investment portfolios.",
        "content_ar": "تشهد الأسواق المالية العالمية حالة من ترقب سياسات البنوك المركزية وسط تحديات التضخم المستمرة وسلاسل الإمداد.\n\n### مؤشرات الأداء الاقتصادي\n- معدلات التضخم الأساسية وأثرها على القدرة الشرائية.\n- توجهات أسواق الأسهم والعملات الرقمية والذهب.\n- استراتيجيات تقليل المخاطر للمستثمرين الأفراد والشركات الكبرى.\n\nيُعد الإلمام بهذه المعطيات ركيزة أساسية لاتخاذ قرارات مالية سليمة ومدروسة.",
        "content_en": "Global financial markets are closely watching central bank policies amidst ongoing inflation challenges.",
    },
    {
        "category": "technology", "slug": "sample-technology", "source_url": "",
        "title_ar": "مستقبل الذكاء الاصطناعي التوليدي: أين تقف الشركات الكبرى؟",
        "title_en": "The future of generative AI: Where do major tech giants stand?",
        "summary_ar": "استعراض لأحدث ابتكارات نماذج اللغات الكبرى وتأثيراتها العملاقة على قطاعات العمل، الإنتاجية، والأمن السيبراني.",
        "summary_en": "Reviewing the latest LLM innovations and their massive impacts on productivity and cybersecurity.",
        "content_ar": "تتسابق الشركات التقنية الكبرى لدمج قدرات الذكاء الاصطناعي في كافة المنتجات والخدمات الرقمية.\n\n### التحولات في بيئة العمل\nأدى التطور المتسارع للخوارزميات إلى إعادة هندسة مهام برمجية وتحليلية كاملة، مما زاد من كفاءة الإنتاج وفتح باباً واسعاً للنقاش حول أمن البيانات وحقوق الملكية الفكرية.",
        "content_en": "Major tech companies are racing to integrate AI capabilities into digital products.",
    },
    {
        "category": "gaming", "slug": "sample-gaming", "source_url": "",
        "title_ar": "صناعة ألعاب الفيديو في 2026: أبعاد التطوير والإصدارات الكبرى",
        "title_en": "Video game industry in 2026: Development dimensions and major releases",
        "summary_ar": "نظرة متعمقة على اتجاهات صناعة الألعاب، تقنيات العرض الحديثة، وأهم الإصدارات المنتظرة لهذا العام.",
        "summary_en": "Deep dive into gaming industry trends, rendering tech, and anticipated releases.",
        "content_ar": "تشهد صناعة الألعاب الإلكترونية تطورات تقنية هائلة على مستوى محركات الرسومات وسرد القصص التفاعلي.\n\n### عناصر التجربة الناجحة\n- ابتكار آليات اللعب الجماعي وسد فجوات المنصات المختلفة (Cross-play).\n- تعزيز الاهتمام بالقصة العميقة وتصاميم عوالم اللعب المفتوحة.\n- دعم منشئي المحتوى ومجتمعات اللاعبين العالمية.",
        "content_en": "The gaming industry is witnessing massive technical evolution.",
    },
    {
        "category": "sports", "slug": "sample-sports", "source_url": "",
        "title_ar": "تحليل الأداء الرقمي في الرياضة الحديثة: كيف تُصنع الانتصارات؟",
        "title_en": "Digital performance analysis in modern sports: How victories are engineered",
        "summary_ar": "كيف غيرت البيانات والإحصاءات المتقدمة وجه المنافسات الرياضية الكبرى في كرة القدم وغيرها.",
        "summary_en": "How advanced data and statistics transformed major sports competitions.",
        "content_ar": "لم تعد الرياضة تعتمد فقط على المهارة الفطرية، بل أصبحت تعتمد على تحليلات البيانات اللحظية والذكاء الاصطناعي لرفع كفاءة اللاعبين وإصاباتهم.",
        "content_en": "Sports no longer rely solely on innate skill, but on real-time data analytics.",
    },
    {
        "category": "science", "slug": "sample-science", "source_url": "",
        "title_ar": "اكتشافات الفضاء العميق: ماذا تخبرنا تلسكوبات الجيل الجديد؟",
        "title_en": "Deep space discoveries: What new generation telescopes reveal",
        "summary_ar": "رحلة استكشافية حول أحدث صور وأرصاد الفضاء وأثرها على فهمنا لنشأة الكون.",
        "summary_en": "An exploratory journey into the latest space observations and their impact on understanding the universe.",
        "content_ar": "تواصل المراصد الفضائية الحديثة تقديم رؤى مذهلة عن المجرات البعيدة والكواكب القابلة للحياة.",
        "content_en": "Modern space observatories continue to provide staggering insights.",
    },
    {
        "category": "culture", "slug": "sample-culture", "source_url": "",
        "title_ar": "السينما والفنون الرقمية: إعادة تعريف التذوق الفني عالمياً",
        "title_en": "Cinema and digital arts: Redefining global artistic taste",
        "summary_ar": "كيف تساهم المنصات الرقمية في نشر الثقافات وتنوع الفنون عبر القارات.",
        "summary_en": "How digital platforms contribute to spreading cultures and diversifying arts.",
        "content_ar": "أتاحت المنصات الرقمية وصول الأعمال المستقلة والسينما العالمية لجمهور أوسع متخطية الحدود التقليدية.",
        "content_en": "Digital platforms have enabled independent works to reach wider audiences.",
    },
    {
        "category": "world", "slug": "sample-world", "source_url": "",
        "title_ar": "الاستدامة البيئية والتنمية المستدامة: تحديات المستقبل القريب",
        "title_en": "Environmental sustainability and global development: Near-future challenges",
        "summary_ar": "متابعة لأحدث المبادرات الدولية لمواجهة التغير المناخي وحماية الموارد المائية والطاقة المتجددة.",
        "summary_en": "Tracking latest international initiatives addressing climate change and renewable energy.",
        "content_ar": "تتطلب التحديات البيئية الراهنة تعاوناً دولياً عاجلاً واعتماد حلول الطاقة النظيفة للحفاظ على كوكب الأرض.",
        "content_en": "Current environmental challenges demand urgent international cooperation.",
    },
]

# PostgreSQL Database Setup
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
                LIMIT 300
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Could not read news from PostgreSQL")
        return []
    finally:
        conn.close()

def _db_search_articles(query: str, limit: int = 100) -> list[dict[str, Any]] | None:
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
    params.append(max(1, min(int(limit), 200)))
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
            %(title_ar)s, %(title_en)s, %(summary_ar)s, %(summary_en)s, %(content_ar)s, %(content_en)s,
            %(published_at)s, NOW(), %(read_minutes)s, %(original_language)s, FALSE
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

# RSS, Image Search & Gemini Processing
_REFRESH_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_REFRESHING = False
_LAST_REFRESH_ATTEMPT = 0.0
_LAST_REFRESH_SUCCESS = 0.0
_MEMORY_ARTICLES: dict[str, dict[str, Any]] = {}
_LAST_REFRESH_AT: datetime | None = None
_LAST_REFRESH_STATE = "idle"
_LAST_REFRESH_ERROR = ""

def _clean_text(value: Any, limit: int = 3500) -> str:
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

def _search_commons_image(title: str) -> dict[str, str]:
    title = _clean_text(title, 240)
    if not title:
        return {}
    params = {
        "action": "query", "generator": "search", "gsrsearch": title,
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": 1200,
        "format": "json", "formatversion": 2,
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    request_obj = Request(url, headers={"User-Agent": "WorldPulseNews/2.0 (copyright safe image search)"})
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
                "image_url": str(image_url), "image_source": "wikimedia_safe",
                "image_credit": artist or "Wikimedia Commons",
                "image_credit_url": page_url, "image_license_url": raw_license_url or page_url,
                "image_license_name": license_name, "image_checked_at": datetime.now(timezone.utc),
            }
    except Exception:
        pass
    return {}

def _resolve_article_image(raw: dict[str, Any]) -> dict[str, str]:
    search_title = str(raw.get("image_search_title") or raw.get("original_title") or "")
    commons = _search_commons_image(search_title)
    if commons:
        return commons
    return {
        "image_url": "", "image_source": "none", "image_credit": "",
        "image_credit_url": "", "image_license_url": "", "image_license_name": "",
        "image_checked_at": datetime.now(timezone.utc),
    }

def _parse_any_rss(feed_url: str, category: str, lang: str, default_source: str) -> tuple[str, str, list[dict[str, Any]]]:
    request_obj = Request(feed_url, headers={"User-Agent": "WorldPulseNews/2.0"})
    try:
        with urlopen(request_obj, timeout=RSS_TIMEOUT_SECONDS) as response:
            raw = response.read(2_000_000)
        feed = feedparser.parse(raw)
        items: list[dict[str, Any]] = []
        for entry in feed.entries[:14]:
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
                "original_title": title, "original_summary": _clean_text(summary_raw, 1200),
                "published_at": _parse_published(entry), "original_language": lang,
            })
        return category, lang, items
    except Exception:
        return category, lang, []

def _collect_rss_articles() -> list[dict[str, Any]]:
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
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = []
        futures.extend(pool.submit(lambda c=c, l=l: _parse_any_rss(f"https://news.google.com/rss/search?q={quote(CATEGORY_QUERIES[c][l])}&hl={'ar' if l=='ar' else 'en'}", c, l, "Google News")) for c in CATEGORY_NAMES for l in ("ar", "en"))
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
        "read_minutes": 2,
        "original_language": original_lang,
        "is_demo": False,
        "fetched_at": datetime.now(timezone.utc),
    }

def _translate_batch(raw_articles: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    if not raw_articles or not GEMINI_API_KEY or genai is None or types is None:
        return {}
    
    result: dict[int, dict[str, str]] = {}
    chunk_size = 4
    for start_idx in range(0, len(raw_articles), chunk_size):
        chunk = raw_articles[start_idx:start_idx + chunk_size]
        payload = [
            {
                "index": start_idx + i,
                "category": article["category"],
                "title": article.get("original_title", "")[:350],
                "source": article.get("source_name", "")[:100],
                "excerpt": article.get("original_summary", "")[:1000],
            }
            for i, article in enumerate(chunk)
        ]
        prompt = f"""You are the senior executive editorial desk for World Pulse. Create deep, highly detailed, and analytical journalistic articles in Modern Standard Arabic and neutral international English based on these inputs.
Return valid JSON with key "stories" containing a list of objects with: index, title_ar, title_en, summary_ar, summary_en, content_ar, content_en.
STRICT EDITORIAL REQUIREMENTS FOR ADSENSE COMPLIANCE:
- Provide rich background context, detailed multi-paragraph analysis, timeline implications, and expert insights for each story to guarantee original editorial value.
- Avoid superficial rewrites. Expand the content professionally into comprehensive reading material (at least 3-4 structured sections/paragraphs in content_ar and content_en).
- Plain text only, no Markdown formatting codes inside fields, valid JSON only.
Input JSON: {json.dumps(payload, ensure_ascii=False)}"""
        try:
            client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.35, max_output_tokens=6000),
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
                    fields[key] = _clean_text(story.get(key, ""), 5000)
                if fields.get("title_ar") and fields.get("title_en") and fields.get("summary_ar") and fields.get("summary_en"):
                    result[idx] = fields
        except Exception as exc:
            logger.warning("Gemini batch processing chunk failed: %s", exc)
            continue
    return result

def _reading_minutes(article: dict[str, Any]) -> int:
    text = " ".join(str(article.get(key, "")) for key in ("title_ar", "title_en", "summary_ar", "summary_en", "content_ar", "content_en"))
    return max(2, min(25, (len(text.split()) // 350) + 1))

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

# Helpers & Routes
def _sample_articles() -> list[dict[str, Any]]:
    result = []
    for template in SAMPLE_STORIES:
        story = dict(template)
        story.update({
            "source_name": "نبض العالم · محتوى تحليلي" if story["category"] else "World Pulse · Analytical sample",
            "image_url": CATEGORY_IMAGES[story["category"]],
            "published_at": None,
            "fetched_at": None,
            "read_minutes": 2,
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
        return "محتوى تحليلي" if lang == "ar" else "Analytical sample"
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
        article=None,
    )

@app.get("/search")
def search():
    lang = current_language()
    query = _clean_text(request.args.get("q", ""), 160)
    results: list[dict[str, Any]] = []
    db_rows = _db_search_articles(query) if query else []
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
    return render_template("index.html", page="search", stories=results, search_query=query,
        all_story_count=len(results), active_category="all", article=None)

LEGAL_PAGES = {
    "privacy": {
        "ar": ("سياسة الخصوصية", "في نبض العالم (World Pulse)، نلتزم بحماية خصوصيتك ومعالجة البيانات بأمان وفق معايير الإعلانات والمحتوى الأصلي. للتواصل: syfsywf86@gmail.com."),
        "en": ("Privacy Policy", "World Pulse respects your privacy. Contact: syfsywf86@gmail.com.")
    },
    "terms": {
        "ar": ("شروط الاستخدام", "يقدم موقع نبض العالم محتوى تحليلياً وعناوين إخبارية مع روابط لمصادرها الأصلية. للتواصل: syfsywf86@gmail.com."),
        "en": ("Terms of Service", "World Pulse provides news summaries and editorial analysis. Contact: syfsywf86@gmail.com.")
    },
    "about": {
        "ar": ("من نحن", "نبض العالم (World Pulse) منصة إخبارية رقمية متقدمة تقدم تغطيات وتحليلات عميقة في مختلف القطاعات. للتواصل: syfsywf86@gmail.com."),
        "en": ("About Us", "World Pulse is a digital news platform providing in-depth analysis. Contact: syfsywf86@gmail.com.")
    },
}

def _render_legal_page(slug: str):
    if slug not in {*LEGAL_PAGES, "contact"}:
        abort(404)
    lang = current_language()
    if slug == "contact":
        title = "اتصل بنا" if lang == "ar" else "Contact Us"
        body = "نرحب بملاحظاتكم واستفساراتكم عبر البريد الرسمي: syfsywf86@gmail.com." if lang == "ar" else "Contact us via official email: syfsywf86@gmail.com."
    else:
        title, body = LEGAL_PAGES[slug][lang]
    return render_template("index.html", page="legal", legal_slug=slug, legal_title=title, legal_body=body,
        contact_status=request.args.get("status", ""), stories=[], all_story_count=0, active_category="all", article=None)

@app.get("/page/<slug>")
def legal_page(slug: str):
    return _render_legal_page(slug)

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
    for row in _all_live_articles()[:300]:
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
    return render_template(
        "index.html",
        page="article",
        stories=[],
        all_story_count=len(pool),
        active_category="all",
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
    question = _clean_text(payload.get("question", ""), 600)
    if lang not in {"ar", "en"}:
        lang = "ar"
    if not slug or not question or len(question) < 2:
        return jsonify({"error": "question_required"}), 400
    story = _find_article(slug, lang)
    if not story:
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
    summary = str(story.get("summary", ""))[:1800]
    body = str(story.get("content", ""))[:4500]
    try:
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=json.dumps({"title": title, "summary": summary, "details": body, "question": question}, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are the senior editorial analyst for World Pulse. Provide a comprehensive, professional, and detailed analytical answer (3-5 sentences) based strictly on the provided context."
                ),
                temperature=0.3,
                max_output_tokens=350,
            ),
        )
        answer = html.unescape(str(response.text or "")).strip()
        answer = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", answer, flags=I if 'I' in globals() else re.I).strip()
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
    return render_template("index.html", page="404", stories=[], all_story_count=0,
                           active_category="all", related_stories=[], article=None), 404

if __name__ == "__main__":
    if "--refresh-news" in sys.argv:
        with _STATE_LOCK:
            _REFRESHING = True
            _LAST_REFRESH_ATTEMPT = time.monotonic()
        _refresh_news_job()
        raise SystemExit(0 if _LAST_REFRESH_STATE in {"success", "memory_only"} else 1)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
