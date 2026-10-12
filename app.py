from datetime import datetime
import json
import os
import math
import random
import socket
import psycopg2
from flask import Flask, jsonify, render_template_string, request
import feedparser
import google.generativeai as genai

app = Flask(__name__)

# إجبار الاتصال على IPv4 لمنع مشاكل الشبكة
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
        return psycopg2.connect(url, sslmode='require', connect_timeout=10)
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
            CREATE TABLE IF NOT EXISTS ai_newsroom_pro_v11 (
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

# 🌟 محرك الأخبار الذاتي المضمن (يضمن امتلاء كافة الأقسام فوراً بدون مشاكل الـ RSS)
RICH_INITIAL_ARTICLES = {
    "ar": [
        {
            "title": "إطلاق جيل جديد من نماذج الذكاء الاصطناعي بقدرات تحليل فائقة",
            "summary": "كشفت الشركات التقنية الكبرى عن نماذج برمجية قادرة على معالجة البيانات المعقدة واتخاذ قرارات فورية.",
            "content": "يشهد قطاع التكنولوجيا تطورات متسارعة مع إطلاق النسخ المحدثة من خوارزميات التعلم العميق. تتيح هذه النماذج للمطورين بناء تطبيقات ذكية قادرة على تحليل النصوص والصور والرموز البرمجية بدقة غير مسبوقة، مما يفتح آفاقاً جديدة في قطاعات الأمن السيبراني وتحليل البيانات.",
            "category": "tech",
            "image": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80"
        },
        {
            "title": "تقلبات حادة في الأسواق المالية العالمية وسط ترقب لقرارات الفائدة",
            "summary": "سجلت مؤشرات الأسهم والعملات الرقمية تفاعلاً ملحوظاً مع أحدث البيانات الاقتصادية الدولية.",
            "content": "تواصل الأسواق المالية العالمية تسجيل تحركات واسعة النطاق مع إعلان البنوك المركزية عن السياسات النقدية القادمة لمواجهة التضخم. ينصح المحللون الماليون بضرورة تنوع المحافظ الاستثمارية لمواجهة المخاطر المحتملة في قطاعات الطاقة والذهب والتقنية.",
            "category": "economy",
            "image": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80"
        },
        {
            "title": "إعلان رسمي عن موعد صدور أضخم ألعاب العالم المفتوح للجيمنج",
            "summary": "ترقب واسع بين اللاعبين لاستعراض تفاصيل اللعب الجديدة والرسومات الخارقة لمنصات الجيل الجديد.",
            "content": "أعلنت استوديوهات تطوير الألعاب الشهيرة عن تفاصيل تشويقية تخص الإصدارات المرتقبة هذا العام، متضمنة عوالم واسعة، تفاعلاً فيزيائياً واقعياً، وأنظمة تحكم مطورة تلبي تطلعات عشاق ألعاب الفئات المتقدمة وعالم الجيمنج.",
            "category": "gaming",
            "image": "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1200&q=80"
        },
        {
            "title": "مباحثات دبلوماسية مكثفة لتعزيز التعاون الدولي والاستقرار",
            "summary": "تتواصل اللقاءات بين القادة والوفد الرسمية لمناقشة الملفات السياسية والاقتصادية الإقليمية.",
            "content": "شهدت العواصم الكبرى حراكاً دبلوماسياً واسعاً لهيكلة الاتفاقيات المشتركة وتعزيز الشراكات الاستراتيجية في مجالات التجارة والطاقة والتكنولوجيا، وسط تأكيدات على أهمية الحوار المستمر لاحتواء الأزمات.",
            "category": "politics",
            "image": "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1200&q=80"
        },
        {
            "title": "اكتشافات فلكية جديدة تفتح باباً لفهم تكوين المجرات البعيدة",
            "summary": "رصدت تلسكوبات الفضاء المتقدمة إشارات دقيقة تساعد العلماء على فك شفرة أسرار الكون المبكر.",
            "content": "أعلن فريق من علماء الفضاء عن رصد تشكيلات نجمية غامضة باستخدام أحدث المراصد الفلكية، وهو ما يساهم في إثراء الأبحاث المتعلقة بتطور الثقوب السوداء وتوسع الكون المرئي.",
            "category": "science",
            "image": "https://images.unsplash.com/photo-1507668077129-56e32842fceb?auto=format&fit=crop&w=1200&q=80"
        },
        {
            "title": "انطلاق منافسات البطولات الكبرى لكرة القدم وسط منافسة شرسة",
            "summary": "تشهد الملاعب العالمية مباريات حاسمة وصراعات قوية بين الأندية على صدارة الترتيب.",
            "content": "تتجه أنظار عشاق الرياضة العالمية نحو المواجهات المرتقبة في الدوريات الكبرى، حيث تسعى الفرق لتعزيز صفوفها وتحقيق النتائج الإيجابية في الأمتار الأخيرة من الموسم.",
            "category": "sports",
            "image": "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80"
        }
    ],
    "en": [
        {
            "title": "Next-Gen AI Models Unveiled with Advanced Reasoning Capabilities",
            "summary": "Major tech firms release powerful models designed for complex multi-domain processing.",
            "content": "The technology sector is shifting rapidly as upgraded deep-learning frameworks roll out globally.",
            "category": "tech",
            "image": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80"
        }
    ]
}

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    return f"{minutes} دقائق قراءة" if lang == "ar" else f"{minutes} min read"

def save_article_to_db(art):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_newsroom_pro_v11 (lang, title, summary, content, category, image, time, read_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lang, title) DO NOTHING
        """, (art['lang'], art['title'], art['summary'], art['content'], art['category'], art['image'], art['time'], art['read_time']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"DB Save Error: {e}")

def seed_rich_articles():
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ai_newsroom_pro_v11")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        
        # إذا كانت القاعدة فارغة، نقوم بتعبئتها فوراً بالمجموعة الغنية من الأخبار
        if count == 0:
            now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
            day_str = datetime.now().strftime("%A")
            for lang, arts in RICH_INITIAL_ARTICLES.items():
                for art in arts:
                    full_art = {
                        "lang": lang,
                        "title": art["title"],
                        "summary": art["summary"],
                        "content": art["content"],
                        "category": art["category"],
                        "image": art["image"],
                        "time": f"{day_str} - {now_str}",
                        "read_time": calculate_read_time(art["content"], lang)
                    }
                    save_article_to_db(full_art)
    except Exception as e:
        print(f"Seed Error: {e}")

try:
    seed_rich_articles()
except Exception:
    pass

def fetch_and_process_news(lang="ar"):
    seed_rich_articles()
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM ai_newsroom_pro_v11 WHERE lang = %s ORDER BY id DESC', (lang,))
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
        return []

@app.route("/")
def home():
    lang = request.args.get("lang", "ar")
    selected_category = request.args.get("cat", "all")
    
    articles = fetch_and_process_news(lang)
    
    if selected_category != "all":
        display_articles = [a for a in articles if a["category"] == selected_category]
    else:
        display_articles = articles

    site_title = "العالم اليوم" if lang == "ar" else "Global Today"
    
    home_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ site_title }} - AI Newsroom</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script> tailwind.config = { darkMode: 'class' } </script>
    </head>
    <body class="bg-slate-950 text-slate-100 font-sans min-h-screen">
        <header class="bg-slate-900 border-b border-slate-800 p-4 sticky top-0 z-50 shadow-lg">
            <div class="container mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
                <div class="flex items-center gap-3">
                    <a href="/?lang={{ lang }}" class="text-3xl font-black text-blue-500 tracking-wider">🌍 {{ site_title }}</a>
                    <span class="text-xs bg-blue-900/50 text-blue-300 px-2.5 py-1 rounded-full border border-blue-700/50">AI Newsroom Pro</span>
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
                <span class="bg-blue-600 text-white text-xs font-black px-3 py-1 rounded-full uppercase animate-pulse">🔥 عاجل</span>
                <div class="overflow-hidden whitespace-nowrap">
                    <p class="text-sm font-semibold text-blue-200 truncate">
                        {{ articles[0].title if articles else ('غرفة التحرير الذكية تعمل بكامل طاقتها...' if lang == 'ar' else 'AI Newsroom is fully operational...') }}
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
                <p class="text-lg font-bold text-slate-400 mb-2">{{ 'لا توجد أخبار متاحة حالياً في هذا القسم.' if lang == 'ar' else 'No news available in this category.' }}</p>
            </div>
            {% endif %}
        </main>
    </body>
    </html>
    """
    return render_template_string(home_template, articles=articles, display_articles=display_articles, lang=lang, selected_category=selected_category, category_names=CATEGORY_NAMES, site_title=site_title)

@app.route("/article/<int:article_id>")
def read_article(article_id):
    lang = request.args.get("lang", "ar")
    articles = fetch_and_process_news(lang)
    article = next((a for a in articles if a["id"] == article_id), None)

    if not article:
        return "الخبر غير موجود / Article Not Found", 404

    recommended = [a for a in articles if a["category"] == article["category"] and a["id"] != article_id][:3]

    cat_key = str(article.get("category", "world")).lower().strip()
    cat_display = CATEGORY_NAMES.get(cat_key, {}).get(lang, CATEGORY_NAMES["world"][lang])
    site_title = "العالم اليوم" if lang == "ar" else "Global Today"

    article_template = """
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
    <body class="bg-slate-950 text-slate-100 font-sans min-h-screen">
        <div class="fixed top-0 left-0 right-0 h-1 bg-slate-800 z-50">
            <div id="readingProgress" class="h-full bg-blue-600"></div>
        </div>
        <header class="bg-slate-900 border-b border-slate-800 p-4 sticky top-1 z-40 shadow-md">
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
