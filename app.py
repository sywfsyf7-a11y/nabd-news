from datetime import datetime, timedelta
import json
import os
import math
import random
import re
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

NEWS_CACHE = {"ar": {"time": None, "data": []}, "en": {"time": None, "data": []}}
NEWS_ARCHIVE = {"ar": [], "en": []}

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

# 💎 مكتبة صور HD عالية الدقة احتياطية لكل قسم
HD_FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1507668077129-56e32842fceb?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1600&q=85",
    "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1600&q=85"
]

def extract_image_from_html(html_text):
    if not html_text:
        return None
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    if match:
        return match.group(1)
    return None

def extract_rss_image(entry):
    # 1. البحث في وسائط RSS المباشرة (media_content / media_thumbnail)
    if hasattr(entry, 'media_content') and entry.media_content:
        for mc in entry.media_content:
            if 'url' in mc:
                return mc['url']
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        for mt in entry.media_thumbnail:
            if 'url' in mt:
                return mt['url']
    # 2. البحث في الروابط المرفقة (enclosures)
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if 'url' in enc or 'href' in enc:
                return enc.get('href') or enc.get('url')
    # 3. استخراج الصورة من محتوى HTML للخبر
    summary = entry.get('summary', '')
    img_url = extract_image_from_html(summary)
    if img_url:
        return img_url
    
    content = entry.get('content', [])
    if content and isinstance(content, list):
        for c in content:
            img_url = extract_image_from_html(c.get('value', ''))
            if img_url:
                return img_url
                
    return None

def calculate_read_time(text, lang):
    words = len(text.split())
    minutes = math.ceil(words / 130) if words > 0 else 1
    if lang == "ar":
        return f"{minutes} دقائق قراءة" if minutes > 1 else "دقيقة قراءة واحدة"
    return f"{minutes} min read"

def generate_detailed_fallback_content(raw_title, raw_summary, lang):
    if lang == "ar":
        return f"""تتابع مختلف الدوائر الإخبارية تفاصيل التطورات الأخيرة المتعلقة بـ "{raw_title}"، في ظل اهتمام واسع بالتبعات المحتملة على الصعيدين المحلي والدولي.

وأفادت التقديرات بأن التحولات الجارية تتطلب قراءة دقيقة للموقف، لاسيما مع تعدد القراءات وتفاوت ردود الفعل بين الأطراف المعنية.

ومن المرتقب أن تحمل الساعات القادمة مستجدات إضافية ترسم ملامح المرحلة القادمة وتحدد مسارات التعامل مع هذا الملف."""
    else:
        return f"""Global media outlets are closely tracking the unfolding events regarding "{raw_title}", focusing on the potential implications across regional and international levels.

Analysts point out that current developments demand a careful evaluation of the situation, especially amid varying perspectives from key stakeholders.

Further updates are expected to emerge soon, shaping the trajectory of upcoming policy and public discourse."""

def process_with_gemini(feed_entries, lang):
    processed = []
    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")
    used_images = set()
    categories_list = ["world", "politics", "economy", "tech", "gaming", "sports", "science", "culture"]

    for idx, entry in enumerate(feed_entries[:6]):
        raw_title = entry.get("title", "خبر عاجل")
        raw_summary = entry.get("summary", "تغطية إخبارية مستمرة ومحدثة على مدار الساعة.")
        
        # استخراج الصورة الحقيقية من الـ RSS أو استخدام صورة بديلة عالية الدقة
        rss_image = extract_rss_image(entry)
        if not rss_image or rss_image in used_images:
            available_hd = [img for img in HD_FALLBACK_IMAGES if img not in used_images]
            rss_image = random.choice(available_hd if available_hd else HD_FALLBACK_IMAGES)
        used_images.add(rss_image)

        assigned_cat = categories_list[idx % len(categories_list)]
        fallback_content = generate_detailed_fallback_content(raw_title, raw_summary, lang)
        
        fallback_item = {
            "id": idx + 1,
            "title": raw_title,
            "summary": raw_summary,
            "content": fallback_content,
            "category": assigned_cat,
            "image": rss_image,
            "time": f"{day_str} - {now_str}",
            "read_time": calculate_read_time(fallback_content, lang)
        }

        if API_KEY:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"""
                You are a professional news editor. Process this article for target language '{lang}':
                Raw Title: {raw_title}
                Raw Summary: {raw_summary}

                Strict Rules:
                1. "title": Catchy headline in '{lang}'.
                2. "summary": Concise 2-sentence executive summary.
                3. "content": Write 3 FULL detailed paragraphs providing deep background context in '{lang}'. Absolutely DO NOT copy or repeat sentences from "summary".
                4. "category": Pick ONE lowercase key from this exact list: [world, politics, economy, tech, gaming, sports, science, culture].

                Return JSON ONLY:
                {{"id": {idx + 1}, "title": "...", "summary": "...", "content": "...", "category": "category_key"}}
                """
                response = model.generate_content(prompt, request_options={"timeout": 4})
                clean_text = response.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_text)
                
                cat = str(data.get("category", assigned_cat)).lower().strip()
                data["time"] = f"{day_str} - {now_str}"
                data["category"] = cat if cat in CATEGORY_NAMES else assigned_cat
                data["image"] = rss_image
                data["read_time"] = calculate_read_time(data.get("content", ""), lang)
                processed.append(data)
            except Exception:
                processed.append(fallback_item)
        else:
            processed.append(fallback_item)

    return processed

def fetch_and_process_news(lang="ar"):
    now = datetime.now()
    if NEWS_CACHE[lang]["time"] and (now - NEWS_CACHE[lang]["time"]) < timedelta(minutes=30) and NEWS_CACHE[lang]["data"]:
        return NEWS_CACHE[lang]["data"]

    sources = ["http://feeds.bbci.co.uk/arabic/rss.xml"] if lang == "ar" else ["http://feeds.bbci.co.uk/news/world/rss.xml"]

    all_entries = []
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed and hasattr(feed, 'entries'):
                all_entries.extend(feed.entries)
        except Exception:
            pass

    articles = []
    if all_entries:
        articles = process_with_gemini(all_entries, lang)

    if articles:
        if NEWS_CACHE[lang]["data"]:
            for old_art in NEWS_CACHE[lang]["data"]:
                if old_art not in NEWS_ARCHIVE[lang]:
                    NEWS_ARCHIVE[lang].append(old_art)
        NEWS_CACHE[lang]["time"] = now
        NEWS_CACHE[lang]["data"] = articles
        return articles

    return NEWS_CACHE[lang]["data"] or []

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
    return jsonify({"lang": lang, "archive": NEWS_ARCHIVE[lang]})

@app.route("/article/<int:article_id>")
def read_article(article_id):
    lang = request.args.get("lang", "ar")
    articles = fetch_and_process_news(lang)
    article = next((a for a in articles if a["id"] == article_id), None)

    if not article:
        article = next((a for a in NEWS_ARCHIVE[lang] if a["id"] == article_id), None)

    if not article:
        return "الخبر غير موجود / Article Not Found", 404

    cat_key = str(article.get("category", "world")).lower().strip()
    cat_display = CATEGORY_NAMES.get(cat_key, {}).get(lang, CATEGORY_NAMES["world"][lang])
    article_image = article.get("image", random.choice(HD_FALLBACK_IMAGES))
    read_time = article.get("read_time", "2 min read")
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
                    <img src="{{ article_image }}" alt="Article" class="w-full h-full object-cover">
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
                            <span class="bg-blue-50 dark:bg-slate-800 text-blue-600 dark:text-blue-400 font-bold px-2.5 py-0.5 rounded-md">⏱️ {{ read_time }}</span>
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
                        speechUtterance.lang = "{{ 'ar-SA' if lang == 'ar' else 'en-US' }}";
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
    return render_template_string(html_template, article=article, lang=lang, cat_display=cat_display, article_image=article_image, read_time=read_time, site_title=site_title)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
