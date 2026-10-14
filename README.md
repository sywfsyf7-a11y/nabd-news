# World Pulse / نبض العالم

A bilingual Flask news portal with PostgreSQL/Supabase persistence, domain-focused Google News RSS discovery, Gemini editorial briefs and Q&A, source attribution, image license checks, search, legal pages and a branded fallback image.

## Render

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --workers 1 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app`
- Optional Render Cron Job command: `python app.py --refresh-news`, schedule `*/15 * * * *`.

## Required/optional Render environment variables

- `FLASK_SECRET_KEY`: long random session secret.
- `SUPABASE_POOLER_URL`: Supabase **Session pooler** URI; preferred for Render IPv4. Keep it secret.
- `DATABASE_URL`: optional fallback if `SUPABASE_POOLER_URL` is unset.
- `GEMINI_API_KEY`: secret API key; never commit to GitHub.
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash`.
- `GEMINI_TIMEOUT_SECONDS`: default `20`.
- `NEWS_AUTO_FETCH=true`; `NEWS_REFRESH_MINUTES=15`; `MAX_ARTICLES_PER_REFRESH=24`; `MAX_ARTICLES_PER_CATEGORY=4`.
- `AI_QUESTIONS_ENABLED=true`; `AI_QUESTIONS_PER_HOUR=5`; `AI_ANSWER_MAX_TOKENS=350`.
- `UNSPLASH_ACCESS_KEY` and `PEXELS_API_KEY` (optional; use only official APIs, follow their API guidelines and provide required photographer/platform attribution).
- `CONTENT_LICENSE_APPROVED_DOMAINS`: optional comma-separated domains only after reviewing their current terms for this site's intended commercial/editorial use or obtaining written permission. Do not set this just to bypass the protection gate.
- `CONTACT_EMAIL=syfsywf86@gmail.com`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` (optional; enables form-to-email sending. Without these, the form opens the visitor's email application).
- `ADMIN_PANEL_PASSWORD` (optional; when set, enables `/admin/login` and `/admin/sources`; use a strong unique password. `ADMIN_PASSWORD` remains a backwards-compatible alias in app.py).
- `SITE_URL` (recommended canonical site origin, e.g. your Render domain).

## News sources and copyright safeguards

The eight sections maintain separate Arabic and English publisher-domain allowlists. Each query is restricted to its configured domains; results outside the list or with a headline in the wrong language are rejected. Pages show stories only when the original source language matches that page. Publisher domains are persisted so display-time filtering can also apply. Google News RSS is used only for headline/excerpt/link discovery; Google News images and publisher thumbnails are not reused. Items from the configured license-required publishers (BBC, Reuters, AP News, TechCrunch, ESPN, ScienceDaily, The Guardian and Al Jazeera) are skipped unless their domain has been reviewed and explicitly configured through `CONTENT_LICENSE_APPROVED_DOMAINS`. This gate is an operational safeguard, not legal advice or a universal permission list: check each publisher's current RSS/API/AI and commercial reuse terms before monetization.

New stories are published only if Gemini creates valid bilingual editorial text from the short discovery metadata. The prompt prohibits copying source sentences, invented facts, unsupported causal claims or pretending the source article was read. AI text should still receive human editorial review; automated rewriting alone does not guarantee original value or AdSense acceptance. Google can reject replicated or scaled low-value content.

## Images

Publisher article/RSS/Open Graph thumbnails are not reused. The app tries, in order, Commons images under Public Domain Mark, CC0 or CC BY (with creator/license attribution), manually approved press-kit assets, and official Pexels/Unsplash API results if keys are configured. It never treats an image shown in Google News as public-domain or reusable merely because Google News displays it. Local fallback images use `static/A.jpg` for originally Arabic stories and `static/E.jpg` for originally English stories, regardless of the current interface language. Pexels and Unsplash attributions include the photographer and provider link; comply with current API rules, including direct use of Unsplash API image URLs. The uploaded World Pulse graphic at `static/world-pulse-placeholder.jpg` is shown as a fallback whenever no safe/relevant image is found or an image fails to load.

A metadata API check cannot guarantee the legal status of an image. Review the original file/license page before commercial use; model/personality/trademark/privacy rights may exist separately. The fallback graphic is supplied by the site owner and is labelled CC0 in the image itself; keep evidence that you have rights to use it.

## Routes

- `/` latest news and category filters
- `/search?q=...` searchable article database
- `/article/<slug>` editorial story and Q&A
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/api/ask`, `/healthz`
- `/robots.txt`, `/sitemap.xml`
- `/admin/sources` with `ADMIN_PANEL_PASSWORD` set

## Local run

```bash
pip install -r requirements.txt
python app.py
```

Validation performed for this package: Python syntax compilation, Jinja template parsing, and mocked Google News RSS publisher/language allowlist checks passed. The Flask application was not fully run with its real dependencies, and live Supabase, Gemini, external APIs and Render deployment were not tested in this session. Configure secrets in Render only.
