from datetime import datetime, timedelta
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_newsroom_pro_v2 (
                id SERIAL PRIMARY KEY,
                lang TEXT,
                title TEXT,
                summary TEXT,
                content TEXT,
                category TEXT,
                image TEXT,
                time TEXT,
                read_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

SPECIALIZED_SOURCES = {
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
    "politics": ["https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1200&q=80"],
    "world": ["https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&q=80"],
    "economy": ["https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?auto=format&fit=crop&w=1200&q=80"],
    "tech": ["https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=1200&q=80"],
    "gaming": ["https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=80"],
    "sports": ["https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80", "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&q=80"],
    "science": ["https://images.unsplash.com/photo-1507668077129-56e32842fceb?auto=format&fit=crop&w=1200&q=80"],
    "culture": ["https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1200&q=80"]
}

def get_dynamic_news_image(cat_key, used_set):
    collection = CATEGORY_HD_COLLECTIONS.get(cat_key, CATEGORY_HD_COLLECTIONS["world"])
    available = [img for img in collection if img not in used_set]
    if not available:
        available = collection
    chosen = random.choice(available)
    used_set.add(chosen)
    return chosen

def detect_category_smart(title, summary):
    text = f"{title} {summary}".lower()
    if any(k in text for k in ["ترامب", "بوتين", "بايدن", "حكومة", "رئيس", "وزير", "انتخابات", "حرب", "سياسة", "trump", "biden", "putin", "president", "election", "war", "politics"]):
        return "politics"
    if any(k in text for k in ["اقتصاد", "دولار", "أسواق", "نفط", "تضخم", "أسهم", "بنك", "economy", "market", "dollar", "stocks", "bank", "oil"]):
        return "economy"
    if any(k in text for k in ["تكنولوجيا", "ذكاء اصطناعي", "جوجل", "أبل", "مايكروسوفت", "هاتف", "tech", "ai", "google", "apple", "microsoft"]):
        return "tech"
    if any(k in text for k in ["لعبة", "جيمنج", "بلايستيشن", "إكس بوكس", "gaming", "playstation", "xbox", "game", "esports"]):
        return "gaming"
    if any(k in text for k in ["كرة", "مباراة", "دوري", "فريق", "لاعب", "sports", "football", "match", "league"]):
        return "sports"
    if any(k in text for k in ["فضاء", "علماء", "كوكب", "طب", "علاج", "science", "space", "nasa", "health"]):
        return "science"
    return "world"

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    return f"{minutes} دقائق قراءة" if lang == "ar" else f"{minutes} min read"

def generate_detailed_fallback_content(raw_title, raw_summary, lang):
    if lang == "ar":
        return f"{raw_summary}\n\nتتابع وسائل الإعلام والتغطيات الصحفية عن كثب تفاصيل المستجدات المرتبطة بـ '{raw_title}'. وتشير التقييمات الأولية إلى أن هذا الحدث يمثل تطوراً لافتاً ضمن سياق الأحداث الجارية، مع توقع صدور تقارير إضافية قريباً."
    return f"{raw_summary}\n\nMedia outlets are closely following the unfolding details regarding '{raw_title}'. Initial assessments indicate a significant development within the current context."

def save_article_to_db(art):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_newsroom_pro_v2 (lang, title, summary, content, category, image, time, read_time)
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
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time, created_at FROM ai_newsroom_pro_v2 WHERE lang = %s ORDER BY id DESC', (lang,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        articles = []
        for row in rows:
            articles.append({
                "id": row[0], "lang": row[1], "title": row[2], "summary": row[3],
                "content": row[4], "category": row[5], "image": row[6], "time": row[7], "read_time": row[8], "created_at": row[9]
            })
        return articles
    except Exception as e:
        print(f"DB Fetch Error: {e}")
        return []

def fetch_and_process_news(lang="ar"):
    articles = get_articles_from_db(lang)
    
    # إذا كانت القواعد فيها أخبار ولم تمضِ 30 دقيقة، نرجعها فوراً
    if articles and len(articles) >= 5:
        last_time = articles[0].get("created_at")
        if last_time and (datetime.now() - last_time) < timedelta(minutes=30):
            return articles

    sources = SPECIALIZED_SOURCES.get(lang, SPECIALIZED_SOURCES["ar"])
    all_entries = []
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed and hasattr(feed, 'entries'):
                all_entries.extend(feed.entries[:3])
        except Exception:
            pass

    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")
    used_images = set()

    for entry in all_entries[:10]:
        raw_title = entry.get("title", "خبر عاجل")
        raw_summary = entry.get("summary", "تغطية إخبارية مستمرة.")
        
        # تنظيف الـ HTML إن وجد في الملخص
        if "<" in raw_summary and ">" in raw_summary:
            import re
            raw_summary = re.sub('<[^<]+?>', '', raw_summary)

        smart_cat = detect_category_smart(raw_title, raw_summary)
        hd_image = get_dynamic_news_image(smart_cat, used_images)
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

        # محاولة التحسين بـ Gemini لكل خبر بشكل سريع
        if API_KEY:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"Act as Chief Editor. Rewrite this news for '{lang}'. Title: {raw_title}. Summary: {raw_summary}. Return strict JSON with keys: title, summary, content, category."
                response = model.generate_content(prompt, request_options={"timeout": 3})
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

        # حفظ الخبر في قاعدة بيانات Supabase فوراً
        save_article_to_db(art)

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
    articles = get_articles_from_db(lang)
    article = next((a for a in articles if a["id"] == article_id), None)

    if not article:
        return "الخبر غير موجود / Article Not Found", 404

    recommended = [a for a in articles if a["category"] == article["category"] and a["id"] != article_id][:3]

    cat_key = str(article.get("category", "world")).lower().strip()
    cat_display = CATEGORY_NAMES.get(cat_key, {}).get(lang, CATEGORY_NAMES["world"][lang])
    site_title = "العالم اليوم" if lang == "ar" else "Global Today"

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
            <article class="bg-white dark:bg-slate-900 rounded-3xl shadow-2xl overflow-hidden border border-slate-200 dark:border-slate-800 mb-12">
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
                    <div class="text-xs text-slate-500 dark:text-slate-400 pb-6 mb-8 border-b border-slate-100 dark:border-slate-800 flex justify-between items-center">
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

            {% if recommended %}
            <div class="mt-12">
                <h3 class="text-xl font-bold mb-6 border-r-4 border-blue-600 pr-3">{{ 'أخبار ذات صلة قد تعجبك:' if lang == 'ar' else 'Recommended Stories:' }}</h3>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {% for rec in recommended %}
                    <div class="bg-white dark:bg-slate-900 rounded-2xl shadow-md border border-slate-100 dark:border-slate-800 overflow-hidden flex flex-col justify-between">
                        <div class="relative h-40 w-full">
                            <img src="{{ rec.image }}" class="w-full h-full object-cover" alt="Rec">
                        </div>
                        <div class="p-4 flex flex-col justify-between flex-grow">
                            <h4 class="font-bold text-sm mb-2 line-clamp-2">{{ rec.title }}</h4>
                            <a href="/article/{{ rec.id }}?lang={{ lang }}" class="text-blue-600 dark:text-blue-400 text-xs font-bold hover:underline mt-2 inline-block">
                                {{ 'اقرأ المزيد ←' if lang == 'ar' else 'Read More →' }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
        </main>
        <script>
            window.onscroll = function() {
                const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
                const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
                const scrolled = (winScroll / height) * 100;
                document.getElementById("readingProgress").style.width = scrolled + "%";
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, article=article, lang=lang, cat_display=cat_display, site_title=site_title, recommended=recommended)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
