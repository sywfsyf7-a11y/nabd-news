from datetime import datetime, timedelta
import json
import os
import math
import random
import re
import urllib.parse
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

# 🌐 الاتصال بقاعدة بيانات Supabase الدائمة
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles_v2 (
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
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Init DB Error: {e}")

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

CATEGORY_HD_COLLECTIONS = {
    "politics": [
        "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1920&q=90"
    ],
    "world": [
        "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=90"
    ],
    "economy": [
        "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=1920&q=90"
    ],
    "tech": [
        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=1920&q=90"
    ],
    "gaming": [
        "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1920&q=90"
    ],
    "sports": [
        "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1920&q=90",
        "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1920&q=90"
    ],
    "science": [
        "https://images.unsplash.com/photo-1507668077129-56e32842fceb?auto=format&fit=crop&w=1920&q=90"
    ],
    "culture": [
        "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1920&q=90"
    ]
}

def get_hd_image_for_news(cat_key, used_set):
    collection = CATEGORY_HD_COLLECTIONS.get(cat_key, CATEGORY_HD_COLLECTIONS["world"])
    available = [img for img in collection if img not in used_set]
    if not available:
        available = collection
    chosen = random.choice(available)
    used_set.add(chosen)
    return chosen

def detect_category_smart(title, summary):
    text = f"{title} {summary}".lower()
    politics_keywords = ["ترامب", "بوتين", "بايدن", "حكومة", "رئيس", "وزير", "انتخابات", "حرب", "عاجل", "سياسة", "trump", "biden", "putin", "president", "election", "war", "minister", "politics"]
    economy_keywords = ["اقتصاد", "دولار", "أسواق", "نفط", "تضخم", "أسهم", "بنك", "economy", "market", "dollar", "stocks", "bank", "oil"]
    tech_keywords = ["تكنولوجيا", "ذكاء اصطناعي", "جوجل", "أبل", "مايكروسوفت", "هاتف", "tech", "ai", "google", "apple", "microsoft"]
    gaming_keywords = ["لعبة", "جيمنج", "بلايستيشن", "إكس بوكس", "gaming", "playstation", "xbox", "game", "esports"]
    sports_keywords = ["كرة", "مباراة", "دوري", "فريق", "لاعب", "sports", "football", "match", "league"]
    science_keywords = ["فضاء", "علماء", "كوكب", "طب", "علاج", "science", "space", "nasa", "health"]
    
    if any(k in text for k in politics_keywords): return "politics"
    if any(k in text for k in economy_keywords): return "economy"
    if any(k in text for k in tech_keywords): return "tech"
    if any(k in text for k in gaming_keywords): return "gaming"
    if any(k in text for k in sports_keywords): return "sports"
    if any(k in text for k in science_keywords): return "science"
    return "world"

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    if lang == "ar":
        return f"{minutes} دقائق قراءة" if minutes > 1 else "دقيقة قراءة واحدة"
    return f"{minutes} min read"

def generate_detailed_fallback_content(raw_title, raw_summary, lang):
    if lang == "ar":
        return f"تتابع وسائل الإعلام والتغطيات الصحفية عن كثب تفاصيل المستجدات المرتبطة بـ '{raw_title}'. وتشير التقييمات الأولية إلى أن هذا الحدث يمثل تطوراً لافتاً ضمن سياق الأحداث الجارية."
    return f"Media outlets are closely following the unfolding details regarding '{raw_title}'. Initial assessments indicate that this event marks a significant development."

def save_article_to_db(art):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO articles_v2 (lang, title, summary, content, category, image, time, read_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lang, title) DO NOTHING
        """, (art['lang'], art['title'], art['summary'], art['content'], art['category'], art['image'], art['time'], art['read_time']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"DB Save Error: {e}")

def get_articles_from_db(lang):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM articles_v2 WHERE lang = %s ORDER BY id DESC', (lang,))
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
        print(f"DB Fetch Error: {e}")
        return []

def process_with_gemini(feed_entries, lang):
    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")
    used_images = set()

    for entry in feed_entries[:8]:
        raw_title = entry.get("title", "خبر عاجل")
        raw_summary = entry.get("summary", "تغطية إخبارية مستمرة.")
        smart_cat = detect_category_smart(raw_title, raw_summary)
        hd_image = get_hd_image_for_news(smart_cat, used_images)
        detailed_content = generate_detailed_fallback_content(raw_title, raw_summary, lang)

        art = {
            "lang": lang,
            "title": raw_title,
            "summary": raw_summary,
            "content": detailed_content,
            "category": smart_cat,
            "image": hd_image,
            "time": f"{day_str} - {now_str}",
            "read_time": calculate_read_time(detailed_content, lang)
        }

        if API_KEY:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"""
                Process this news for target language '{lang}':
                Title: {raw_title}
                Summary: {raw_summary}
                Return strict JSON:
                {{"title": "...", "summary": "...", "content": "...", "category": "world|politics|economy|tech|gaming|sports|science|culture"}}
                """
                response = model.generate_content(prompt, request_options={"timeout": 4})
                clean_text = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_text)
                art["title"] = data.get("title", raw_title)
                art["summary"] = data.get("summary", raw_summary)
                art["content"] = data.get("content", detailed_content)
                cat = str(data.get("category", smart_cat)).lower().strip()
                art["category"] = cat if cat in CATEGORY_NAMES else smart_cat
                art["read_time"] = calculate_read_time(art["content"], lang)
            except Exception:
                pass

        save_article_to_db(art)

    return get_articles_from_db(lang)

def fetch_and_process_news(lang="ar"):
    existing = get_articles_from_db(lang)
    if existing and len(existing) >= 6:
        return existing

    sources = ["http://feeds.bbci.co.uk/arabic/rss.xml"] if lang == "ar" else ["http://feeds.bbci.co.uk/news/world/rss.xml"]
    all_entries = []
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed and hasattr(feed, 'entries'):
                all_entries.extend(feed.entries)
        except Exception:
            pass

    if all_entries:
        process_with_gemini(all_entries, lang)

    return get_articles_from_db(lang)

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

@app.route("/article/<int:article_id>")
def read_article(article_id):
    lang = request.args.get("lang", "ar")
    conn = get_db_connection()
    if not conn:
        return "Database Error", 500
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM articles_v2 WHERE id = %s', (article_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return "الخبر غير موجود / Article Not Found", 404

        article = {
            "id": row[0], "lang": row[1], "title": row[2], "summary": row[3],
            "content": row[4], "category": row[5], "image": row[6], "time": row[7], "read_time": row[8]
        }
        
        cat_key = str(article.get("category", "world")).lower().strip()
        cat_display = CATEGORY_NAMES.get(cat_key, {}).get(lang, CATEGORY_NAMES["world"][lang])
        site_title = "العالم اليوم" if lang == "ar" else "Global Today"

        # قالب صفحة قراءة الخبر المدمج
        html_template = """
        <!DOCTYPE html>
        <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ article.title }} | {{ site_title }}</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script> tailwind.config = { darkMode: 'class' } </script>
            <style> #readingProgress { width: 0%; transition: width 0.1s ease-out; } </style>
        </head>
        <body class="bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans transition-colors duration-300">
            <div class="fixed top-0 left-0 right-0 h-1 bg-gray-200 dark:bg-slate-800 z-50">
                <div id="readingProgress" class="h-full bg-blue-600"></div>
            </div>
            <header class="bg-slate-900 border-b border-slate-800 text-white p-4 sticky top-1 z-40 shadow-md">
                <div class="container mx-auto flex justify-between items-center">
                    <a href="/" class="text-2xl font-black text-blue-500 tracking-wide">{{ site_title }}</a>
                    <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-bold transition">
                        {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                    </a>
                </div>
            </header>
            <main class="container mx-auto px-4 py-10 max-w-4xl">
                <article class="bg-white dark:bg-slate-900 rounded-3xl shadow-2xl overflow-hidden border border-slate-200 dark:border-slate-800">
                    <div class="relative h-96 w-full bg-slate-800">
                        <img src="{{ article.image }}" alt="Article" class="w-full h-full object-cover">
                        <div class="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/40 to-transparent"></div>
                        <div class="absolute bottom-6 right-6 left-6 text-white">
                            <span class="bg-blue-600 text-white text-xs font-extrabold px-3 py-1.5 rounded-full uppercase inline-block mb-3 shadow">
                                {{ cat_display }}
                            </span>
                            <h1 class="text-2xl md:text-4xl font-black leading-snug drop-shadow-md">{{ article.title }}</h1>
                        </div>
                    </div>
                    <div class="p-8 md:p-12">
                        <div class="text-xs text-slate-500 dark:text-slate-400 pb-6 mb-8 border-b border-slate-100 dark:border-slate-800 flex justify-between">
                            <span>🕒 {{ article.time }}</span>
                            <span class="bg-blue-50 dark:bg-slate-800 text-blue-600 font-bold px-2.5 py-0.5 rounded-md">⏱️ {{ article.read_time }}</span>
                        </div>
                        <div class="text-slate-800 dark:text-slate-200 text-lg leading-relaxed space-y-8">
                            <div class="bg-blue-50/80 dark:bg-slate-800/80 p-6 rounded-2xl border-r-4 border-blue-600 shadow-sm">
                                <h4 class="text-xs font-bold text-blue-600 mb-2 uppercase">{{ 'الملخص التنفيذي' if lang == 'ar' else 'Summary' }}</h4>
                                <p class="font-semibold text-base leading-relaxed">{{ article.summary }}</p>
                            </div>
                            <div class="whitespace-pre-line text-slate-700 dark:text-slate-300 leading-9 text-lg">
                                {{ article.content }}
                            </div>
                        </div>
                    </div>
                </article>
            </main>
        </body>
        </html>
        """
        return render_template_string(html_template, article=article, lang=lang, cat_display=cat_display, site_title=site_title)
    except Exception as e:
        return f"Error: {e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
# 🖼️ نظام جلب الصور الذكي المرتبط بمحتوى الخبر
def get_dynamic_news_image(title, summary, category):
    query_text = f"{title} {summary}".lower()
    
    # قاموس كلمات مفتاحية لجلب صور حقيقية ومعبرة من Unsplash بناءً على مضمون الخبر
    if any(k in query_text for k in ["ترامب", "بوتين", "بايدن", "رئيس", "حكومة", "انتخابات", "politics", "president"]):
        return "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1200&q=80"
    elif any(k in query_text for k in ["اقتصاد", "أسواق", "دولار", "أسهم", "بنك", "economy", "market", "stocks"]):
        return "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80"
    elif any(k in query_text for k in ["تكنولوجيا", "ذكاء اصطناعي", "جوجل", "أبل", "هاتف", "tech", "ai", "google", "apple"]):
        return "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80"
    elif any(k in query_text for k in ["لعبة", "جيمنج", "بلايستيشن", "gaming", "playstation", "xbox", "game"]):
        return "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1200&q=80"
    elif any(k in query_text for k in ["كرة", "مباراة", "دوري", "sports", "football", "match", "league"]):
        return "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80"
    elif any(k in query_text for k in ["فضاء", "علماء", "ناسا", "science", "space", "nasa"]):
        return "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80"
    
    # صور عامة عالية الدقة ومتنوعة حسب التصنيف في حال عدم وجود كلمة مفتاحية محددة
    default_collections = {
        "politics": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1200&q=80",
        "economy": "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=1200&q=80",
        "tech": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=1200&q=80",
        "gaming": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=80",
        "sports": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=80",
        "world": "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1200&q=80"
    }
    return default_collections.get(category, default_collections["world"])
