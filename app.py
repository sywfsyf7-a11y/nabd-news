from datetime import datetime, timedelta
import json
import os
from flask import Flask, jsonify, render_template_string, request, send_from_directory
import feedparser
import google.generativeai as genai

app = Flask(__name__)

# إعداد مفتاح Gemini API
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
  genai.configure(api_key=API_KEY)

NEWS_CACHE = {"ar": {"time": None, "data": []}, "en": {"time": None, "data": []}}


def process_with_gemini(feed_entries, lang):
  """معالجة خفيفة ومباشرة لمنع بطء السيرفر"""
  model = genai.GenerativeModel("gemini-1.5-flash")
  processed = []

  # أخذ أول 8 أخبار فقط لضمان السرعة وعدم استهلاك الخادم
  for idx, entry in enumerate(feed_entries[:8]):
    raw_title = entry.get("title", "")
    raw_summary = entry.get("summary", "")
    published = entry.get("published", "منذ وقت قصير")

    prompt = f"""
        تحليل خبر سريع للغة '{lang}':
        العنوان: {raw_title}
        الملخص: {raw_summary}

        المطلوب بصيغة JSON فقط:
        {{"id": {idx + 1}, "title": "عنوان جذاب مختصر", "summary": "ملخص ممتاظ من سطرين", "content": "مقال من فقرتين مفصلتين", "category": "اختر واحد فقط: [world, politics, economy, tech, gaming, sports, science, culture]"}}
        """

    try:
      # تحديد وقت استجابة سريع جداً
      response = model.generate_content(
          prompt, request_options={"timeout": 5}
      )
      clean_text = (
          response.text.replace("```json", "").replace("```", "").strip()
      )
      data = json.loads(clean_text)
      data["time"] = published
      processed.append(data)
    except Exception:
      # نظام حماية: إذا تأخر الذكاء الاصطناعي يتم اعتماد الخبر فوراً دون إيقاف الخادم
      processed.append({
          "id": idx + 1,
          "title": raw_title,
          "summary": raw_summary,
          "content": (
              f"{raw_summary}\n\nتغطية إخبارية مستمرة عبر شبكة العالم اليوم."
          ),
          "category": "world",
          "time": published,
      })

  return processed


def fetch_and_process_news(lang="ar"):
  now = datetime.now()

  # كاش لمدة ساعة كاملة لراحة السيرفر
  if (
      NEWS_CACHE[lang]["time"]
      and (now - NEWS_CACHE[lang]["time"]) < timedelta(hours=1)
      and NEWS_CACHE[lang]["data"]
  ):
    return NEWS_CACHE[lang]["data"]

  feed_url = (
      "http://feeds.bbci.co.uk/news/world/rss.xml"
      if lang == "en"
      else "http://feeds.bbci.co.uk/arabic/rss.xml"
  )

  try:
    feed = feedparser.parse(feed_url)
    articles = process_with_gemini(feed.entries, lang)
  except Exception:
    articles = NEWS_CACHE[lang]["data"] or []

  if articles:
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


@app.route("/article/<int:article_id>")
def read_article(article_id):
  lang = request.args.get("lang", "ar")
  articles = fetch_and_process_news(lang)

  article = next((a for a in articles if a["id"] == article_id), None)
  if not article:
    return "الخبر غير موجود حالياً", 404

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
                <span class="bg-blue-100 text-blue-800 text-xs font-bold px-3 py-1 rounded-full uppercase">{{ article.category }}</span>
                <h1 class="text-3xl font-black mt-4 mb-4 text-slate-900 leading-snug">{{ article.title }}</h1>
                <div class="text-xs text-gray-500 pb-6 mb-6 border-b border-gray-100 flex items-center gap-2">
                    <span>🕒 {{ article.time }}</span> • <span>الفريق الإخباري</span>
                </div>
                <div class="text-gray-700 text-lg leading-relaxed space-y-6">
                    <p class="font-semibold text-gray-900 bg-blue-50 p-4 rounded-xl border-r-4 border-blue-600">{{ article.summary }}</p>
                    <div class="whitespace-pre-line text-slate-800 leading-8">{{ article.content }}</div>
                </div>
            </div>
        </main>
    </body>
    </html>
    """
  return render_template_string(
      html_template, article=article, lang=lang
  )


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
