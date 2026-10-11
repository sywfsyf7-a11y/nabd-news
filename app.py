from datetime import datetime
import json
import os
import math
import random
import psycopg2
from flask import Flask, jsonify, render_template_string, request, send_from_directory
import feedparser
import google.generativeai as genai

app = Flask(__name__)

API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
    except Exception:
        pass

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode='require', connect_timeout=5)
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def init_db():
    try:
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                lang TEXT,
                title TEXT,
                summary TEXT,
                content TEXT,
                category TEXT,
                image TEXT,
                time TEXT,
                read_time TEXT,
                UNIQUE(lang, title)
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Init DB Error: {e}")

# عدم إيقاف السيرفر في حال فشل الاتصال المبدئي
try:
    init_db()
except Exception:
    pass

CATEGORY_NAMES = {
    "world": {"ar": "🌍 أخبار العالم", "en": "🌍 World News"},
    "politics": {"ar": "🏛️ سياسة ودبلوماسية", "en": "🏛️ Politics & Diplomacy"},
    "economy": {"ar": "📈 اقتصاد وأسواق", "en": "📈 Economy & Markets"},
    "tech": {"ar": "💻 تكنولوجيا وذكاء اصطناعي", "en": "💻 Tech & AI"},
    "gaming": {"ar": "🎮 ألعاب وجيمنج", "en": "🎮 Gaming"},
    "sports": {"ar": "⚽ رياضة عالمية", "en": "⚽ Global Sports"},
    "science": {"ar": "🧬 علوم وفضاء", "en": "🧬 Science & Space"},
    "culture": {"ar": "🎬 ثقافة وفن وترفيه", "en": "🎬 Culture & Arts"}
}

MULTI_SOURCES = {
    "ar": [
        "http://feeds.bbci.co.uk/arabic/rss.xml",
        "https://www.aljazeera.net/aljazeerarss/a7c18663-7311-4224-b77e-d960b077f092/73d0e1b4-532f-45ef-b135-bfd3d2cf8712",
        "https://arabic.rt.com/rss/"
    ],
    "en": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://www.eurogamer.net/feed/news",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
    ]
}

CATEGORY_HD_COLLECTIONS = {
    "politics": ["https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1920&q=90"],
    "world": ["https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1920&q=90"],
    "economy": ["https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1920&q=90"],
    "tech": ["https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1920&q=90"],
    "gaming": ["https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1920&q=90"],
    "sports": ["https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1920&q=90"],
    "science": ["https://images.unsplash.com/photo-1507668077129-56e32842fceb?auto=format&fit=crop&w=1920&q=90"],
    "culture": ["https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1920&q=90"]
}

def get_hd_image(cat_key):
    col = CATEGORY_HD_COLLECTIONS.get(cat_key, CATEGORY_HD_COLLECTIONS["world"])
    return random.choice(col)

def detect_category_smart(title, summary):
    text = f"{title} {summary}".lower()
    if any(k in text for k in ["ترامب", "بوتين", "بايدن", "حكومة", "رئيس", "انتخابات", "trump", "biden", "putin", "election"]):
        return "politics"
    if any(k in text for k in ["اقتصاد", "دولار", "أسواق", "نفط", "تضخم", "economy", "market", "dollar"]):
        return "economy"
    if any(k in text for k in ["تكنولوجيا", "ذكاء اصطناعي", "جوجل", "أبل", "tech", "ai", "google", "apple"]):
        return "tech"
    if any(k in text for k in ["لعبة", "جيمنج", "بلايستيشن", "gaming", "playstation", "xbox", "nintendo", "steam"]):
        return "gaming"
    if any(k in text for k in ["كرة", "مباراة", "دوري", "sports", "football", "match"]):
        return "sports"
    if any(k in text for k in ["فضاء", "علماء", "طب", "science", "space"]):
        return "science"
    return "world"

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    return f"{minutes} دقائق قراءة" if lang == "ar" else f"{minutes} min read"

def generate_detailed_fallback_content(raw_title, lang):
    if lang == "ar":
        return f"تتابع الصحافة العالمية باهتمام بالغ التطورات الأخيرة المرتبطة بـ '{raw_title}'. وتشير التقارير الميدانية إلى أن هذا الحدث يفتح الباب أمام قراءات متعددة لتبعاته المستقبلية."
    return f"Global media outlets are closely tracking the unfolding events regarding '{raw_title}'."

def save_article_to_db(art):
    try:
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO articles (lang, title, summary, content, category, image, time, read_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lang, title) DO NOTHING
        '', (art['lang'], art['title'], art['summary'], art['content'], art['category'], art['image'], art['time'], art['read_time']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Save Article DB Error: {e}")

def get_articles_from_db(lang):
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cursor = conn.cursor()
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM articles WHERE lang = %s ORDER BY id DESC', (lang,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        articles = []
        for row in rows:
            articles.append({
                "id": row[0], "lang": row[1], "title": row[2], "summary": row[3],
                "content": row[4], "category": row[5], "image": row[6], "time": row[7], "read_time": row[8]
            })
        return articles
    except Exception as e:
        print(f"Get Articles DB Error: {e}")
        return []

def fetch_and_process_news(lang="ar"):
    existing = get_articles_from_db(lang)
    if existing and len(existing) >= 8:
        return existing

    sources = MULTI_SOURCES.get(lang, MULTI_SOURCES["ar"])
    all_entries = []
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed and hasattr(feed, 'entries'):
                all_entries.extend(feed.entries[:5])
        except Exception:
            pass

    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")
    fetched_articles = []

    for entry in all_entries[:12]:
        raw_title = entry.get("title", "خبر عاجل")
        raw_summary = entry.get("summary", "تغطية إخبارية مستمرة.")
        smart_cat = detect_category_smart(raw_title, raw_summary)
        hd_image = get_hd_image(smart_cat)
        detailed_content = generate_detailed_fallback_content(raw_title, lang)

        art = {
            "id": random.randint(1000, 9999),
            "lang": lang,
            "title": raw_title,
            "summary": raw_summary,
            "content": detailed_content,
            "category": smart_cat,
            "image": hd_image,
            "time": f"{day_str} - {now_str}",
            "read_time": calculate_read_time(detailed_content, lang)
        }

        save_article_to_db(art)
        fetched_articles.append(art)

    db_arts = get_articles_from_db(lang)
    return db_arts if db_arts else fetched_articles

@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/api/news")
def get_news():
    lang = request.args.get("lang", "ar")
    articles = fetch_and_process_news(lang)
    return jsonify({"lang": lang, "articles": articles})

@app.route("/api/archive")
def get_archive():
    lang = request.args.get("lang", "ar")
    articles = get_articles_from_db(lang)
    return jsonify({"lang": lang, "archive": articles})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
