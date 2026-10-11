import json
import os
from flask import Flask, jsonify, request, send_from_directory
import feedparser
import google.generativeai as genai

app = Flask(__name__)

# إعداد مفتاح Gemini API
API_KEY = os.environ.get("GEMINI_API_KEY")
if API_KEY:
  genai.configure(api_key=API_KEY)


@app.route("/")
def home():
  return send_from_directory(".", "index.html")


@app.route("/api/news")
def get_news():
  lang = request.args.get("lang", "ar")

  # جلب الأخبار الحية حسب اللغة
  feed_url = (
      "http://feeds.bbci.co.uk/news/rss.xml"
      if lang == "en"
      else "http://feeds.bbci.co.uk/arabic/rss.xml"
  )
  feed = feedparser.parse(feed_url)

  articles = []
  model = genai.GenerativeModel("gemini-1.5-flash")

  for entry in feed.entries[:8]:
    raw_title = entry.get("title", "")
    raw_summary = entry.get("summary", "")
    link = entry.get("link", "")
    published = entry.get("published", "منذ وقت قصير")

    prompt = f"""
        أنت محرر إخباري ذكي لمنصة إخبارية عالمية. قم بتحليل الخبر التالي باللغة '{lang}':
        العنوان: {raw_title}
        الملخص: {raw_summary}

        المطلوب:
        1. صغ عنواناً احترافياً وجذاباً.
        2. اكتب ملخصاً واضحاً من سطرين.
        3. حدد التصنيف بدقة واختاره حصرياً من هذه القائمة:
           [world, politics, sports, tech, economy, culture, gaming]
           (ملاحظة: اختر gaming إذا كان الخبر متعلقاً بألعاب الفيديو، بلايستيشن، إكس بوكس، إسبورتس، أو تقنيات الألعاب).

        أرجع النتيجة بصيغة JSON نظيفة حصرياً بدون أي نصوص إضافية:
        {{"title": "العنوان", "summary": "الملخص", "category": "التصنيف", "time": "{published}"}}
        """

    try:
      response = model.generate_content(prompt)
      clean_text = (
          response.text.replace("```json", "").replace("```", "").strip()
      )
      data = json.loads(clean_text)
      data["link"] = link
      articles.append(data)
    except Exception as e:
      articles.append({
          "title": raw_title,
          "summary": raw_summary,
          "category": "world",
          "link": link,
          "time": "منذ وقت قصير",
      })

  return jsonify({"lang": lang, "articles": articles})


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
