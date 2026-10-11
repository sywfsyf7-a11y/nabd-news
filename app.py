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

# 🌐 الاتصال بقاعدة بيانات Supabase الدائمة
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        return None
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
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

init_db()

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

def get_hd_image(cat_key):
    col = CATEGORY_HD_COLLECTIONS.get(cat_key, CATEGORY_HD_COLLECTIONS["world"])
    return random.choice(col)

def detect_category_smart(title, summary):
    text = f"{title} {summary}".lower()
    if any(k in text for k in ["ترامب", "بوتين", "بايدن", "حكومة", "رئيس", "انتخابات", "سلطة", "trump", "biden", "putin", "election", "politics"]):
        return "politics"
    if any(k in text for k in ["اقتصاد", "دولار", "أسواق", "نفط", "تضخم", "أسهم", "economy", "market", "dollar", "stocks", "oil"]):
        return "economy"
    if any(k in text for k in ["تكنولوجيا", "ذكاء اصطناعي", "جوجل", "أبل", "هاتف", "tech", "ai", "google", "apple"]):
        return "tech"
    if any(k in text for k in ["لعبة", "جيمنج", "بلايستيشن", "gaming", "playstation", "xbox"]):
        return "gaming"
    if any(k in text for k in ["كرة", "مباراة", "دوري", "sports", "football", "match"]):
        return "sports"
    if any(k in text for k in ["فضاء", "علماء", "طب", "science", "space", "health"]):
        return "science"
    return "world"

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    if lang == "ar":
        return f"{minutes} دقائق قراءة" if minutes > 1 else "دقيقة قراءة واحدة"
    return f"{minutes} min read"

def generate_detailed_fallback_content(raw_title, lang):
    if lang == "ar":
        return f"""تتابع الصحافة العالمية باهتمام بالغ التطورات الأخيرة المرتبطة بـ "{raw_title}". وتشير التقارير الميدانية والتحليلات السياسية إلى أن هذا الحدث يفتح الباب أمام قراءات متعددة لتبعاته المستقبلية على الصعيد الإقليمي والدولي.

وقد عبر المراقبون عن ضرورة رصد ردود الفعل الرسمية وغير الرسمية للوقوف على تداعيات الموقف بدقة. ومن المتقب أن تشهد الأيام القادمة مستجدات إضافية ترسم ملامح جديدة للتعامل مع هذا الملف."""
    else:
        return f"""Global media outlets are closely tracking the unfolding events regarding "{raw_title}". Field reports and political analysis indicate that this development opens the door for wide-ranging perspectives on its long-term regional and international impacts.

Observers emphasize the necessity of monitoring official and unofficial reactions to accurately evaluate the situation. Further updates are expected in the coming days."""

def save_article_to_db(art):
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO articles (lang, title, summary, content, category, image, time, read_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lang, title) DO NOTHING
        ''', (art['lang'], art['title'], art['summary'], art['content'], art['category'], art['image'], art['time'], art['read_time']))
        conn.commit()
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        cursor.close()
        conn.close()

def get_articles_from_db(lang):
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
            "id": row[0],
            "lang": row[1],
            "title": row[2],
            "summary": row[3],
            "content": row[4],
            "category": row[5],
            "image": row[6],
            "time": row[7],
            "read_time": row[8]
        })
    return articles

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

    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")

    for entry in all_entries[:10]:
        raw_title = entry.get("title", "خبر عاجل")
        raw_summary = entry.get("summary", "تغطية إخبارية مستمرة.")
        smart_cat = detect_category_smart(raw_title, raw_summary)
        hd_image = get_hd_image(smart_cat)
        detailed_content = generate_detailed_fallback_content(raw_title, lang)

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
    cursor = conn.cursor()
    cursor.execute('SELECT id, lang, title, summary, content, category, image, time, read_time FROM articles WHERE id = %s', (article_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return "الخبر غير موجود / Article Not Found", 404

    article = {
        "id": row[0],
        "lang": row[1],
        "title": row[2],
        "summary": row[3],
        "content": row[4],
        "category": row[5],
        "image": row[6],
        "time": row[7],
        "read_time": row[8]
    }
    
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
        <script>
            tailwind.config = { darkMode: 'class' }
        </script>
        <style>
            #readingProgress { width: 0%; transition: width 0.1s ease-out; }
        </style>
    </head>
    <body class="bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 font-sans transition-colors duration-300">
        
        <div class="fixed top-0 left-0 right-0 h-1 bg-gray-200 dark:bg-slate-800 z-50">
            <div id="readingProgress" class="h-full bg-blue-600"></div>
        </div>

        <header class="bg-slate-900 border-b border-slate-800 text-white p-4 sticky top-1 z-40 shadow-md">
            <div class="container mx-auto flex justify-between items-center">
                <a href="/" class="text-2xl font-black text-blue-500 tracking-wide">{{ site_title }}</a>
                <div class="flex items-center gap-3">
                    <button onclick="toggleDarkMode()" id="themeBtn" class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs font-bold rounded-lg border border-slate-700 transition">
                        <span id="themeIcon">🌙</span> <span id="themeText">{{ 'الليلي' if lang == 'ar' else 'Dark' }}</span>
                    </button>
                    <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-bold transition">
                        {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                    </a>
                </div>
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
                    <div class="text-xs text-slate-500 dark:text-slate-400 pb-6 mb-8 border-b border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-4">
                        <div class="flex items-center gap-3">
                            <span>🕒 {{ article.time }}</span> • 
                            <span class="bg-blue-50 dark:bg-slate-800 text-blue-600 dark:text-blue-400 font-bold px-2.5 py-0.5 rounded-md">⏱️ {{ article.read_time }}</span>
                        </div>
                        
                        <button onclick="toggleAudio()" id="audioBtn" class="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-full text-xs font-bold shadow transition">
                            <span id="audioIcon">🔊</span> <span id="audioText">{{ 'استمع للخبر' if lang == 'ar' else 'Listen Article' }}</span>
                        </button>
                    </div>
                    
                    <div class="text-slate-800 dark:text-slate-200 text-lg leading-relaxed space-y-8">
                        <div class="bg-blue-50/80 dark:bg-slate-800/80 p-6 rounded-2xl border-r-4 border-blue-600 shadow-sm">
                            <h4 class="text-xs font-bold text-blue-600 dark:text-blue-400 mb-2 uppercase tracking-wider">{{ 'الملخص التنفيذي' if lang == 'ar' else 'Executive Summary' }}</h4>
                            <p id="summaryText" class="font-semibold text-slate-900 dark:text-slate-100 text-base leading-relaxed">{{ article.summary }}</p>
                        </div>

                        <div>
                            <h3 class="text-lg font-bold text-slate-900 dark:text-slate-100 mb-4 border-b border-slate-100 dark:border-slate-800 pb-2">
                                {{ 'تفاصيل وتغطية إخبارية شاملة:' if lang == 'ar' else 'Comprehensive Detailed Coverage:' }}
                            </h3>
                            <div id="fullArticleContent" class="whitespace-pre-line text-slate-700 dark:text-slate-300 leading-9 text-lg font-normal">
                                {{ article.content }}
                            </div>
                        </div>
                    </div>

                    <div class="mt-12 pt-6 border-t border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-4">
                        <span class="text-xs font-bold text-slate-500 dark:text-slate-400">{{ 'شارك الخبر مع أصدقائك:' if lang == 'ar' else 'Share this story:' }}</span>
                        <div class="flex items-center gap-2">
                            <button onclick="shareWhatsApp()" class="bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-90">WhatsApp</button>
                            <button onclick="shareX()" class="bg-slate-800 text-white px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-90">X / Twitter</button>
                            <button onclick="copyArticleLink()" class="bg-slate-200 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-90">🔗 {{ 'نسخ الرابط' if lang == 'ar' else 'Copy Link' }}</button>
                        </div>
                    </div>
                </div>
            </article>
        </main>

        <script>
            let speechUtterance = null;
            let isSpeaking = false;

            function getBestVoice(targetLang) {
                const voices = window.speechSynthesis.getVoices();
                if (!voices || voices.length === 0) return null;
                const langPrefix = targetLang === 'ar' ? 'ar' : 'en';
                const bestVoice = voices.find(v => v.lang.startsWith(langPrefix) && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Online')));
                if (bestVoice) return bestVoice;
                return voices.find(v => v.lang.startsWith(langPrefix)) || null;
            }

            function toggleAudio() {
                if ('speechSynthesis' in window) {
                    if (isSpeaking) {
                        window.speechSynthesis.cancel();
                        isSpeaking = false;
                        document.getElementById('audioText').innerText = "{{ 'استمع للخبر' if lang == 'ar' else 'Listen Article' }}";
                        document.getElementById('audioIcon').innerText = "🔊";
                    } else {
                        const title = "{{ article.title }}";
                        const summary = document.getElementById('summaryText').innerText;
                        const content = document.getElementById('fullArticleContent').innerText;
                        const fullText = `${title}. ${summary}. ${content}`;

                        speechUtterance = new SpeechSynthesisUtterance(fullText);
                        const targetLang = "{{ 'ar' if lang == 'ar' else 'en' }}";
                        speechUtterance.lang = targetLang === 'ar' ? 'ar-SA' : 'en-US';
                        speechUtterance.rate = 0.95;

                        const bestVoice = getBestVoice(targetLang);
                        if (bestVoice) speechUtterance.voice = bestVoice;

                        speechUtterance.onend = () => {
                            isSpeaking = false;
                            document.getElementById('audioText').innerText = "{{ 'استمع للخبر' if lang == 'ar' else 'Listen Article' }}";
                            document.getElementById('audioIcon').innerText = "🔊";
                        };

                        window.speechSynthesis.speak(speechUtterance);
                        isSpeaking = true;
                        document.getElementById('audioText').innerText = "{{ 'إيقاف الصوت' if lang == 'ar' else 'Stop Audio' }}";
                        document.getElementById('audioIcon').innerText = "⏹️";
                    }
                } else {
                    alert("المتصفح لا يدعم القراءة الصوتية.");
                }
            }

            window.onscroll = function() {
                const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
                const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
                const scrolled = (winScroll / height) * 100;
                document.getElementById("readingProgress").style.width = scrolled + "%";
            };

            function toggleDarkMode() {
                document.documentElement.classList.toggle('dark');
                const isDark = document.documentElement.classList.contains('dark');
                localStorage.setItem('theme', isDark ? 'dark' : 'light');
                updateThemeUI(isDark);
            }

            function updateThemeUI(isDark) {
                document.getElementById('themeIcon').innerText = isDark ? '☀️' : '🌙';
                document.getElementById('themeText').innerText = isDark ? 'نهاري' : 'ليلي';
            }

            if (localStorage.getItem('theme') === 'dark') {
                document.documentElement.classList.add('dark');
                updateThemeUI(true);
            }

            function shareWhatsApp() {
                window.open(`https://api.whatsapp.com/send?text=${encodeURIComponent(document.title + ' ' + window.location.href)}`, '_blank');
            }
            function shareX() {
                window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(document.title)}&url=${encodeURIComponent(window.location.href)}`, '_blank');
            }
            function copyArticleLink() {
                navigator.clipboard.writeText(window.location.href);
                alert("تم نسخ رابط الخبر بنجاح!");
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, article=article, lang=lang, cat_display=cat_display, site_title=site_title)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
