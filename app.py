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

# 🖼️ صور احترافية متغيرة حسب تصنيف الخبر لتبهر القارئ
CATEGORY_IMAGES = {
    "world": "https://images.unsplash.com/photo-1521295121783-8a321d5d1ad2?w=1200",
    "politics": "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?w=1200",
    "economy": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200",
    "tech": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1200",
    "gaming": "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=1200",
    "sports": "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=1200",
    "science": "https://images.unsplash.com/photo-1507668077129-56e32842fceb?w=1200",
    "culture": "https://images.unsplash.com/photo-1485846234645-a62644f84728?w=1200",
}


def process_with_gemini(feed_entries, lang):
  model = genai.GenerativeModel("gemini-1.5-flash")
  processed = []

  for idx, entry in enumerate(feed_entries[:10]):
    raw_title = entry.get("title", "")
    raw_summary = entry.get("summary", "")
    now_str = datetime.now().strftime("%Y-%m-%d | %H:%M")
    day_str = datetime.now().strftime("%A")

    prompt = f"""
        You are an expert news writer. Process this article for target language '{lang}':
        Raw Title: {raw_title}
        Raw Summary: {raw_summary}

        Strict Rules:
        1. "title": Catchy, professional news headline in language '{lang}'.
        2. "summary": A concise 2-sentence summary highlighting key facts.
        3. "content": Write 3 FULL paragraphs of detailed background analysis and story context in '{lang}'. DO NOT repeat or copy sentences from summary. Dive straight into new details.
        4. "category": Select ONLY ONE lowercase string from this exact list: [world, politics, economy, tech, gaming, sports, science, culture].

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
      cat = data.get("category", "world").lower().strip()
      data["category"] = cat if cat in CATEGORY_IMAGES else "world"
      data["image"] = CATEGORY_IMAGES[data["category"]]
      processed.append(data)
    except Exception:
      continue

  return processed


def fetch_and_process_news(lang="ar"):
  now = datetime.now()
  if (
      NEWS_CACHE[lang]["time"]
      and (now - NEWS_CACHE[lang]["time"]) < timedelta(minutes=1)
      and NEWS_CACHE[lang]["data"]
  ):
    return NEWS_CACHE[lang]["data"]

  sources = (
      ["http://feeds.bbci.co.uk/arabic/rss.xml"]
      if lang == "ar"
      else [
          "http://feeds.bbci.co.uk/news/world/rss.xml",
          "http://feeds.bbci.co.uk/news/technology/rss.xml",
          "http://feeds.bbci.co.uk/news/business/rss.xml",
          "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
      ]
  )

  all_entries = []
  for url in sources:
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
  article_image = article.get("image", CATEGORY_IMAGES.get(cat_key, CATEGORY_IMAGES["world"]))

  html_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ article.title }} | العالم اليوم</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 font-sans text-gray-900">
        <header class="bg-slate-900 text-white p-4 border-b border-slate-800 sticky top-0 z-50">
            <div class="container mx-auto flex justify-between items-center">
                <a href="/" class="text-2xl font-black text-blue-500">Global Today</a>
                <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-bold transition">
                    {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                </a>
            </div>
        </header>

        <main class="container mx-auto px-4 py-10 max-w-4xl">
            <article class="bg-white rounded-3xl shadow-xl overflow-hidden border border-gray-100">
                <!-- صورة الخبر الفخمة والمتغيرة حسب التصنيف -->
                <div class="relative h-96 w-full">
                    <img src="{{ article_image }}" alt="Article Image" class="w-full h-full object-cover">
                    <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent"></div>
                    <div class="absolute bottom-6 right-6 left-6 text-white">
                        <span class="bg-blue-600 text-white text-xs font-bold px-3 py-1.5 rounded-full uppercase inline-block mb-3 shadow">
                            {{ cat_display }}
                        </span>
                        <h1 class="text-3xl md:text-4xl font-black leading-snug drop-shadow-md">{{ article.title }}</h1>
                    </div>
                </div>

                <div class="p-8 md:p-12">
                    <div class="text-xs text-gray-500 pb-6 mb-8 border-b border-gray-100 flex items-center gap-3">
                        <span>🕒 {{ article.time }}</span> • <span class="font-bold text-blue-600">Global Today Editorial</span>
                    </div>
                    
                    <div class="text-gray-800 text-lg leading-relaxed space-y-8">
                        <div class="bg-blue-50/70 p-6 rounded-2xl border-r-4 border-blue-600 shadow-sm">
                            <h4 class="text-xs font-bold text-blue-700 mb-2 uppercase tracking-wider">{{ 'الملخص التنفيذي' if lang == 'ar' else 'Executive Summary' }}</h4>
                            <p class="font-semibold text-gray-900 text-base leading-relaxed">{{ article.summary }}</p>
                        </div>

                        <div class="whitespace-pre-line text-slate-700 leading-9 text-lg font-normal">
                            {{ article.content }}
                        </div>
                    </div>
                </div>
            </article>
        </main>
    </body>
    </html>
    """
  return render_template_string(
      html_template,
      article=article,
      lang=lang,
      cat_display=cat_display,
      article_image=article_image,
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
