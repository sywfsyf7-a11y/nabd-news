from datetime import datetime
import json
import os
import random
import socket
import psycopg2
from flask import Flask, render_template_string, request
import google.generativeai as genai

app = Flask(__name__)

# إجبار الاتصال على IPv4 لمنع مشاكل السحابة
old_getaddrinfo = socket.getaddrinfo
def force_ipv4_getaddrinfo(*args, **kwargs):
    responses = old_getaddrinfo(*args, **kwargs)
    return [r for r in responses if r[0] == socket.AF_INET]
socket.getaddrinfo = force_ipv4_getaddrinfo

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
        print(f"DB Error: {e}")
        return None

def init_db():
    try:
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_newsroom_v15 (
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

DEFAULT_FALLBACK_ARTICLES = {
    "ar": [
        {
            "id": 1,
            "title": "تطورات متسارعة في تقنيات الذكاء الاصطناعي وأنظمة الحوسبة المتقدمة",
            "summary": "تسعى كبرى الشركات التقنية لدمج نماذج التعلم العميق في البنى التحتية الرقمية لتعزيز الأمان والسرعة.",
            "content": "تشهد الأسواق التقنية العالمية طفرة غير مسبوقة بفضل انتشار الأدوات البرمجية المدارة بالذكاء الاصطناعي. تساهم هذه الابتكارات في تسهيل تحليل البيانات الضخمة، ودعم منصات الأمن السيبراني في رصد الثغرات والتصدي لها بفاعلية.",
            "category": "tech",
            "image": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80",
            "time": "اليوم - تحديث مستمر",
            "read_time": "3 دقائق قراءة"
        },
        {
            "id": 2,
            "title": "تحركات حذرة في الأسواق المالية بالتزامن مع ترقب مؤشرات التضخم",
            "summary": "تتفاعل أسواق العملات والأسهم مع التحديثات الاقتصادية الجديدة والقرارات النقدية الدولية.",
            "content": "تواصل المؤسسات المالية دراسة تأثير تقلبات أسعار الفائدة على قطاعات الاستثمار المختلفة، وسط توصيات الخبراء بضرورة تنويع الأصول لتقليل المخاطر.",
            "category": "economy",
            "image": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80",
            "time": "اليوم - تحديث مستمر",
            "read_time": "4 دقائق قراءة"
        },
        {
            "id": 3,
            "title": "إعلان رسمي عن تفاصيل وعروض إصدارات ألعاب الجيل الجديد",
            "summary": "يترقب عشاق ألعاب الفيديو الإطلاقات الضخمة هذا العام مع تحسينات جبارة في الجرافيك وعوالم اللعب.",
            "content": "كشفت استوديوهات التطوير الكبرى عن لمحات تشويقية لأبرز العناوين القادمة، متضمنة آليات تفاعل فيزيائي متطورة وقصص استثنائية.",
            "category": "gaming",
            "image": "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1200&q=80",
            "time": "اليوم - تحديث مستمر",
            "read_time": "3 دقائق قراءة"
        }
    ],
    "en": [
        {
            "id": 1,
            "title": "Rapid Advancements in Artificial Intelligence and Computing",
            "summary": "Major tech firms integrate deep learning models to secure digital infrastructures.",
            "content": "Global tech markets are witnessing a surge in AI-driven tools that streamline big data analysis and enhance cybersecurity resilience.",
            "category": "tech",
            "image": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80",
            "time": "Today - Live Update",
            "read_time": "3 min read"
        }
    ]
}

def get_articles(lang="ar"):
    conn = get_db_connection()
    if not conn:
        return DEFAULT_FALLBACK_ARTICLES.get(lang, DEFAULT_FALLBACK_ARTICLES["ar"])
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM ai_newsroom_v15 WHERE lang = %s ORDER BY id DESC', (lang,))
        rows = cursor.fetchall()
        
        if not rows:
            # تعبئة قاعدة البيانات افتراضياً لضمان عدم ظهور موقع فارغ أبداً
            for item in DEFAULT_FALLBACK_ARTICLES.get(lang, DEFAULT_FALLBACK_ARTICLES["ar"]):
                cursor.execute("""
                    INSERT INTO ai_newsroom_v15 (lang, title, summary, content, category, image, time, read_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lang, title) DO NOTHING
                """, (lang, item['title'], item['summary'], item['content'], item['category'], item['image'], item['time'], item['read_time']))
            conn.commit()
            cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM ai_newsroom_v15 WHERE lang = %s ORDER BY id DESC', (lang,))
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
        print(f"Fetch Error: {e}")
        return DEFAULT_FALLBACK_ARTICLES.get(lang, DEFAULT_FALLBACK_ARTICLES["ar"])

@app.route("/")
def home():
    lang = request.args.get("lang", "ar")
    selected_category = request.args.get("cat", "all")
    
    articles = get_articles(lang)
    
    if selected_category != "all":
        display_articles = [a for a in articles if a["category"] == selected_category]
    else:
        display_articles = articles

    site_title = "نبض العالم" if lang == "ar" else "World Pulse"
    breaking_label = "🔥 عاجل" if lang == "ar" else "🔥 BREAKING"
    top_breaking_news = articles[0]["title"] if articles else ("تغطية حية مستمرة..." if lang == "ar" else "Live continuous coverage...")

    home_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ site_title }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 font-sans min-h-screen">
        <header class="bg-slate-900 border-b border-slate-800 p-4 sticky top-0 z-50 shadow-lg">
            <div class="container mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
                <div class="flex items-center gap-3">
                    <a href="/?lang={{ lang }}" class="text-3xl font-black text-blue-500 tracking-wider">🌍 {{ site_title }}</a>
                </div>
                <div class="flex items-center gap-3">
                    <a href="/?lang={{ 'en' if lang == 'ar' else 'ar' }}" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold transition shadow">
                        {{ 'English 🌐' if lang == 'ar' else 'عربي 🌐' }}
                    </a>
                </div>
            </div>
            <nav class="container mx-auto mt-4 flex flex-wrap gap-2 justify-center border-t border-slate-800/80 pt-3">
                <a href="/?lang={{ lang }}" class="px-3 py-1.5 rounded-lg text-xs font-bold transition {{ 'bg-blue-600 text-white' if selected_category == 'all' else 'bg-slate-800 text-slate-300 hover:bg-slate-700' }}">
                    {{ '⚡ كل الأخبار' if lang == 'ar' else '⚡ All News' }}
                </a>
                {% for key, cat in category_names.items() %}
                <a href="/?lang={{ lang }}&cat={{ key }}" class="px-3 py-1.5 rounded-lg text-xs font-bold transition {{ 'bg-blue-600 text-white' if selected_category == key else 'bg-slate-800 text-slate-300 hover:bg-slate-700' }}">
                    {{ cat[lang] }}
                </a>
                {% endfor %}
            </nav>
        </header>

        <main class="container mx-auto px-4 py-8 max-w-7xl">
            <div class="bg-blue-950/40 border border-blue-800/50 rounded-2xl p-4 mb-8 flex items-center gap-4 shadow-md">
                <span class="bg-blue-600 text-white text-xs font-black px-3 py-1 rounded-full uppercase animate-pulse">{{ breaking_label }}</span>
                <div class="overflow-hidden whitespace-nowrap w-full">
                    <p class="text-sm font-semibold text-blue-200 truncate">
                        {{ top_breaking_news }}
                    </p>
                </div>
            </div>

            <h2 class="text-xl font-black mb-6 border-r-4 border-blue-600 pr-3 flex items-center justify-between">
                <span>{{ '📰 التغطيات الإخبارية الحية' if lang == 'ar' else '📰 Live News Coverage' }}</span>
                <span class="text-xs font-normal text-slate-400">({{ display_articles|length }} {{ 'خبر متاحة' if lang == 'ar' else 'stories' }})</span>
            </h2>

            {% if display_articles %}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {% for art in display_articles %}
                <div class="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-xl flex flex-col justify-between hover:border-blue-600/50 transition duration-300">
                    <div>
                        <div class="relative h-48 w-full bg-slate-800 overflow-hidden">
                            <img src="{{ art.image }}" alt="News" class="w-full h-full object-cover hover:scale-105 transition duration-500">
                            <span class="absolute top-3 right-3 bg-blue-600 text-white text-[10px] font-black px-2.5 py-1 rounded-full shadow">
                                {{ category_names.get(art.category, {}).get(lang, art.category) }}
                            </span>
                        </div>
                        <div class="p-6">
                            <div class="text-[11px] text-slate-400 mb-2 flex justify-between">
                                <span>🕒 {{ art.time }}</span>
                                <span class="text-blue-400 font-bold">⏱️ {{ art.read_time }}</span>
                            </div>
                            <h3 class="font-black text-lg mb-3 leading-snug line-clamp-2 hover:text-blue-400 transition">{{ art.title }}</h3>
                            <p class="text-slate-400 text-sm leading-relaxed line-clamp-3 mb-4">{{ art.summary }}</p>
                        </div>
                    </div>
                    <div class="p-6 pt-0">
                        <a href="/article/{{ art.id }}?lang={{ lang }}" class="w-full block text-center bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-xl font-bold text-xs transition shadow">
                            {{ 'قراءة الخبر كاملاً ←' if lang == 'ar' else 'Read Full Story →' }}
                        </a>
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="text-center py-20 bg-slate-900/50 rounded-3xl border border-slate-800">
                <p class="text-lg font-bold text-slate-400 mb-2">{{ 'لا توجد أخبار متاحة حالياً.' if lang == 'ar' else 'No news available.' }}</p>
            </div>
            {% endif %}
        </main>
    </body>
    </html>
    """
    return render_template_string(home_template, articles=articles, display_articles=display_articles, lang=lang, selected_category=selected_category, category_names=CATEGORY_NAMES, site_title=site_title, breaking_label=breaking_label, top_breaking_news=top_breaking_news)

@app.route("/article/<int:article_id>")
def read_article(article_id):
    lang = request.args.get("lang", "ar")
    articles = get_articles(lang)
    article = next((a for a in articles if a["id"] == article_id), None)

    if not article:
        return "الخبر غير موجود / Article Not Found", 404

    recommended = [a for a in articles if a["category"] == article["category"] and a["id"] != article_id][:3]
    cat_key = str(article.get("category", "world")).lower().strip()
    cat_display = CATEGORY_NAMES.get(cat_key, {}).get(lang, CATEGORY_NAMES["world"][lang])
    site_title = "نبض العالم" if lang == "ar" else "World Pulse"

    article_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ article.title }} | {{ site_title }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 font-sans min-h-screen">
        <header class="bg-slate-900 border-b border-slate-800 p-4 sticky top-0 z-40 shadow-md">
            <div class="container mx-auto flex justify-between items-center max-w-4xl">
                <a href="/?lang={{ lang }}" class="text-2xl font-black text-blue-500 tracking-wide">{{ site_title }}</a>
                <a href="/?lang={{ lang }}" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold transition shadow">
                    {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                </a>
            </div>
        </header>
        <main class="container mx-auto px-4 py-10 max-w-4xl">
            <article class="bg-slate-900 rounded-3xl shadow-2xl overflow-hidden border border-slate-800 mb-12">
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
                    <div class="text-xs text-slate-400 pb-6 mb-8 border-b border-slate-800 flex justify-between items-center">
                        <span>🕒 {{ article.time }}</span>
                        <span class="bg-slate-800 text-blue-400 font-bold px-3 py-1 rounded-md">⏱️ {{ article.read_time }}</span>
                    </div>
                    <div class="text-slate-200 text-lg leading-relaxed space-y-8">
                        <div class="bg-slate-800/80 p-6 rounded-2xl border-r-4 border-blue-600 shadow-sm">
                            <h4 class="text-xs font-bold text-blue-400 mb-2 uppercase">{{ 'الملخص التنفيذي' if lang == 'ar' else 'Summary' }}</h4>
                            <p class="font-semibold text-base leading-relaxed">{{ article.summary }}</p>
                        </div>
                        <div class="whitespace-pre-line text-slate-300 leading-9 text-lg">
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
                    <div class="bg-slate-900 rounded-2xl shadow-md border border-slate-800 overflow-hidden flex flex-col justify-between">
                        <div class="relative h-40 w-full">
                            <img src="{{ rec.image }}" class="w-full h-full object-cover" alt="Rec">
                        </div>
                        <div class="p-4 flex flex-col justify-between flex-grow">
                            <h4 class="font-bold text-sm mb-2 line-clamp-2 text-slate-200">{{ rec.title }}</h4>
                            <a href="/article/{{ rec.id }}?lang={{ lang }}" class="text-blue-400 text-xs font-bold hover:underline mt-2 inline-block">
                                {{ 'اقرأ المزيد ←' if lang == 'ar' else 'Read More →' }}
                            </a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
        </main>
    </body>
    </html>
    """
    return render_template_string(article_template, article=article, lang=lang, cat_display=cat_display, site_title=site_title, recommended=recommended)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
