from datetime import datetime, timedelta
import json
import os
from flask import Flask, jsonify, render_template_string, request, send_from_directory
import feedparser
import google.generativeai as genai

app = Flask(__name__)

API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
  genai.configure(api_key=API_KEY)

NEWS_CACHE = {"ar": {"time": None, "data": []}, "en": {"time": None, "data": []}}
NEWS_ARCHIVE = {"ar": [], "en": []}

# 🌐 مصادر RSS متعددة ومتخصصة لتغطية (السياسة، الاقتصاد، التكنولوجيا، الجيمنج، والعلوم)
RSS_SOURCES = {
    "ar": [
        "http://feeds.bbci.co.uk/arabic/rss.xml",  # أخبار عامة وسياسة واقتصاد
    ],
    "en": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",  # أخبار العالم
        "http://feeds.bbci.co.uk/news/technology/rss.xml",  # تكنولوجيا وذكاء اصطناعي
        "http://feeds.bbci.co.uk/news/business/rss.xml",  # مال وأعمال واقتصاد
        "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",  # علوم وفضاء وبيئة
        (
            "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"
        ),  # فن وثقافة وترفيه
    ],
}

CATEGORY_NAMES = {
    "world": {"ar": "🌍 أخبار العالم", "en": "🌍 World News"},
    "politics": {"ar": "🏛️ سياسة ودبلوماسية", "en": "🏛️ Politics"},
    "economy": {"ar": "📈 اقتصاد وأسواق", "en": "📈 Economy"},
    "tech": {"ar": "💻 تكنولوجيا وذكاء اصطناعي", "en": "💻 Tech & AI"},
    "gaming": {"ar": "🎮 ألعاب وجيمنج", "en": "🎮 Gaming"},
    "sports": {"ar": "⚽ رياضة عالمية", "en": "⚽ Sports"},
    "science": {"ar": "🧬 علوم وفضاء", "en": "🧬 Science"},
    "culture": {"ar": "🎬 ثقافة وفن", "en": "🎬 Culture"},
}


def process_with_gemini(feed_entries, lang):
  model = genai.GenerativeModel("gemini-1.5-flash")
  processed = []

  # نأخذ عينة من الأخبار المتنوعة من كل المصادر
  for idx, entry in enumerate(feed_entries[:12]):
    raw_title = entry.get("title", "")
    raw_summary = entry.get("summary", "")
    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")

    prompt = f"""
        You are an expert news editor and classifier. Process this article for target language '{lang}':
        Raw Title: {raw_title}
        Raw Summary: {raw_summary}

        Strict Rules:
        1. "title": Catchy, professional news headline in language '{lang}'.
        2. "summary": A concise 2-sentence summary highlighting key facts.
        3. "content": Write 3 FULL paragraphs of detailed background analysis and story context in '{lang}'. DO NOT repeat or copy sentences from summary. Dive straight into new details.
        4. "category": Select the MOST ACCURATE single lowercase category from this exact list based on the article topic: 
           [world, politics, economy, tech, gaming, sports, science, culture]. 
           (Note: Assign tech/AI to 'tech', video games/gaming to 'gaming', art/movies/entertainment to 'culture', space/science to 'science', money/business to 'economy').

        Output ONLY valid JSON format:
        {{"id": {idx + 1}, "title": "Headline", "summary": "Short Summary", "content": "Paragraph 1\\n\\nParagraph 2\\n\\nParagraph 3", "category": "category_name"}}
        """

    try:
      response = model.generate_content(
          prompt, request_options={"timeout": 6}
      )
      clean_text = (
          response.text.replace("```json", "").replace("```", "").strip()
      )
      data = json.loads(clean_text)
      data["time"] = f"{day_str} - {now_str}"
      data["category"] = data.get("category", "world").lower().strip()
      processed.append(data)
    except Exception:
      continue  # تخطي أي خبر يواجه خطأ بالمعالجة لضمان سرعة السيرفر

  return processed


def fetch_and_process_news(lang="ar"):
  now = datetime.now()
  if (
      NEWS_CACHE[lang]["time"]
      and (now - NEWS_CACHE[lang]["time"]) < timedelta(minutes=1)
      and NEWS_CACHE[lang]["data"]
  ):
    return NEWS_CACHE[lang]["data"]

  all_entries = []
  # سحب الأخبار من جميع المصادر المتاحة للغة المحددة
  for url in RSS_SOURCES.get(lang, RSS_SOURCES["ar"]):
    try:
      feed = feedparser.parse(url)
      all_entries.extend(feed.entries)
    except Exception:
      pass

  try:
    articles = process_with_gemini(all_entries, lang)
  except Exception:
    articles = NEWS_CACHE[lang]["data"] or []

  if articles:
    if NEWS_CACHE[lang]["data"]:
      for old_art in NEWS_CACHE[lang]["data"]:
        if old_art not in NEWS_ARCHIVE[lang]:
          NEWS_ARCHIVE[lang].append(old_art)
    NEWS_CACHE[lang]["time"] = now
    NEWS_CACHE[lang]["data"] = articles

  return articles


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
    article = next(
        (a for a in NEWS_ARCHIVE[lang] if a["id"] == article_id), None
    )

  if not article:
    return "الخبر غير موجود", 404

  cat_key = str(article.get("category", "world")).lower().strip()
  cat_display = CATEGORY_NAMES.get(cat_key, {}).get(
      lang, CATEGORY_NAMES["world"][lang]
  )

  html_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ article.title }} | العالم اليوم</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 font-sans text-gray-900">
        <header class="bg-slate-900 text-white p-4 border-b border-slate-800">
            <div class="container mx-auto flex justify-between items-center">
                <a href="/" class="text-2xl font-black text-blue-500">العالم اليوم</a>
                <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-bold">
                    {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                </a>
            </div>
        </header>
        <main class="container mx-auto px-4 py-10 max-w-4xl">
            <div class="bg-white rounded-2xl shadow-lg border border-gray-200 p-8">
                <span class="bg-blue-100 text-blue-800 text-xs font-bold px-3 py-1.5 rounded-full inline-block mb-3">
                    {{ cat_display }}
                </span>
                
                <h1 class="text-3xl font-black mb-4 text-slate-900 leading-snug">{{ article.title }}</h1>
                
                <div class="text-xs text-gray-500 pb-6 mb-6 border-b border-gray-100 flex items-center gap-2">
                    <span>🕒 {{ article.time }}</span> • <span>الفريق الإخباري الذكي</span>
                </div>
                
                <div class="text-gray-700 text-lg leading-relaxed space-y-6">
                    <div class="bg-blue-50 p-5 rounded-xl border-r-4 border-blue-600">
                        <h4 class="text-xs font-bold text-blue-700 mb-1 uppercase tracking-wider">{{ 'الملخص التنفيذي' if lang == 'ar' else 'Executive Summary' }}</h4>
                        <p class="font-semibold text-gray-900 text-base leading-snug">{{ article.summary }}</p>
                    </div>

                    <div class="whitespace-pre-line text-slate-800 leading-8 text-base">
                        {{ article.content }}
                    </div>
                </div>
            </div>
        </main>
    </body>
    </html>
    """
  return render_template_string(
      html_template, article=article, lang=lang, cat_display=cat_display
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
