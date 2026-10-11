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

# ذاكرة تخزين مؤقت لتسريع الموقع
NEWS_CACHE = {"ar": {"time": None, "data": []}, "en": {"time": None, "data": []}}


def fetch_and_process_news(lang="ar"):
  now = datetime.now()
  # إذا كان هناك أخبار مخزنة وأقل من 30 دقيقة، ارجعها فوراً دون انتظار Gemini
  if (
      NEWS_CACHE[lang]["time"]
      and (now - NEWS_CACHE[lang]["time"]) < timedelta(minutes=30)
      and NEWS_CACHE[lang]["data"]
  ):
    return NEWS_CACHE[lang]["data"]

  feed_url = (
      "http://feeds.bbci.co.uk/news/rss.xml"
      if lang == "en"
      else "http://feeds.bbci.co.uk/arabic/rss.xml"
  )
  feed = feedparser.parse(feed_url)

  articles = []
  model = genai.GenerativeModel("gemini-1.5-flash")

  for idx, entry in enumerate(feed.entries[:10]):
    raw_title = entry.get("title", "")
    raw_summary = entry.get("summary", "")
    published = entry.get("published", "منذ وقت قصير")

    prompt = f"""
        أنت محرر إخباري ذكي لمنصة إخبارية عالمية. قم بتحليل الخبر التالي بـ اللغة '{lang}':
        العنوان: {raw_title}
        الملخص: {raw_summary}

        المطلوب:
        1. صغ عنواناً احترافياً وجذاباً.
        2. اكتب ملخصاً واضحاً ومثيراً من سطرين.
        3. اكتب مقالاً كاملاً ومفصلاً ومصاغاً بأسلوب حصري من 3 فقرات بناءً على الخبر.
        4. حدد التصنيف بدقة واختاره حصرياً من هذه القائمة:
           [world, politics, sports, tech, economy, culture, gaming]

        أرجع النتيجة بصيغة JSON نظيفة بدون أسطر إضافية:
        {{"id": {idx + 1}, "title": "العنوان", "summary": "الملخص", "content": "المقال الكامل من 3 فقرات", "category": "التصنيف", "time": "{published}"}}
        """

    try:
      response = model.generate_content(prompt)
      clean_text = (
          response.text.replace("```json", "").replace("```", "").strip()
      )
      data = json.loads(clean_text)
      articles.append(data)
    except Exception:
      articles.append({
          "id": idx + 1,
          "title": raw_title,
          "summary": raw_summary,
          "content": (
              f"{raw_summary}\n\nهذا الخبر تم جلبه وتغطيته عبر شبكة العالم اليوم"
              " الإخبارية بشكل آلي."
          ),
          "category": "world",
          "time": published,
      })

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
    return "الخبر غير موجود", 404

  # صفحة قراءة الخبر الداخلية الفخمة
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
                <a href="/" class="text-2xl font-black text-blue-500">العالم<span class="text-white">اليوم</span></a>
                <a href="/" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-xs font-bold">
                    {{ '← العودة للرئيسية' if lang == 'ar' else '← Back to Home' }}
                </a>
            </div>
        </header>

        <main class="container mx-auto px-4 py-10 max-w-4xl">
            <div class="bg-white rounded-2xl shadow-lg overflow-hidden border border-gray-200 p-8">
                <span class="bg-blue-100 text-blue-800 text-xs font-bold px-3 py-1 rounded-full uppercase">
                    {{ article.category }}
                </span>
                <h1 class="text-3xl font-black mt-4 mb-4 text-slate-900 leading-snug">{{ article.title }}</h1>
                <div class="text-xs text-gray-500 pb-6 mb-6 border-b border-gray-100 flex items-center gap-2">
                    <span>🕒 {{ article.time }}</span> • <span>بواسطة الفريق الإخباري الذكي</span>
                </div>
                
                <div class="text-gray-700 text-lg leading-relaxed space-y-6">
                    <p class="font-semibold text-gray-900 bg-blue-50 p-4 rounded-xl border-r-4 border-blue-600">
                        {{ article.summary }}
                    </p>
                    <div class="whitespace-pre-line text-slate-800 leading-8">
                        {{ article.content }}
                    </div>
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
