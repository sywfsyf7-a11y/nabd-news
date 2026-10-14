# World Pulse / نبض العالم

A bilingual Flask news portal with PostgreSQL/Supabase persistence, domain-focused Google News RSS discovery, Gemini editorial briefs and Q&A, source attribution, image license checks, search, legal pages and a branded fallback image.

## Render

- Build command: `pip install -r requirements.txt`
- Start command (also configured in `render.yaml`): `gunicorn --workers 2 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app`
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
- `CONTACT_EMAIL`: contact inbox (defaults to the configured site email).
- `SMTP_HOST`, `SMTP_PORT` (default `587`), `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL`: optional mail-server settings for direct contact form delivery.
- `SMTP_USE_SSL=true` for SSL SMTP (normally port `465`); otherwise `SMTP_STARTTLS=true` is used by default (normally port `587`). Without SMTP, the contact page gives a direct email link and does not falsely report delivery.
- `ADMIN_PANEL_PASSWORD` (optional; when set, enables `/admin/login` and `/admin/sources`; use a strong unique password. `ADMIN_PASSWORD` remains a backwards-compatible alias in the app.)
- `SITE_URL` (recommended canonical site origin, e.g. your Render domain).

## News sources and copyright safeguards

The eight news sections have separate publisher allowlists for Arabic and English. Discovery requests to Google News RSS are constrained to the configured publisher domains; the parser verifies the publisher's domain and rejects wrong-language headlines before the story is stored. If every eligible source for a category/language is disabled or blocked, that feed returns no stories rather than switching to unrestricted discovery. Publisher controls are available at `/admin/sources`.

A publisher link, RSS result, or attribution is **not** a licence to republish an article or its thumbnail. The app does not use Google News images. Review each publisher's current RSS, AI, commercial and republication terms before enabling sources for a monetized site. Rights-gated sources are excluded unless the configured licence-approval list explicitly permits them; that safeguard is not legal advice or a guarantee that a permission covers every use.

Stories are written as bilingual editorial summaries from limited discovery metadata, not as copies of source articles. Automated generation can still make errors or provide insufficient original value; editorial review is necessary and no code change guarantees acceptance by advertising or search platforms.

## Images

Publisher thumbnails and Open Graph images are not reused. The app uses eligible Wikimedia Commons images with supported public-domain/CC0/CC BY licences, manually reviewed press-kit assets from `approved_presskit_images.json`, and optional official Pexels or Unsplash API results when their keys are configured and the provider is enabled. Required attribution and the original image/license page are retained when available. Google News is used only for discovery, never as the image provider.

When no eligible image is available, the templates use `static/A.jpg` for Arabic-origin stories and `static/E.jpg` for English-origin stories, independent of which language page the visitor is viewing. The same rule is used for article Open Graph image metadata. Remove or replace a reused image from the admin page at `/admin/sources`.

An API result does not by itself guarantee the legal status of an image. Review the original file/license page for commercial use, and consider separate personality, trademark, privacy and other rights. Keep permission records for all approved press-kit assets.

## Routes

- `/` latest news and category filters
- `/search?q=...` searchable article database
- `/article/<slug>` editorial story and Q&A
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/api/ask`, `/healthz`
- `/robots.txt`, `/sitemap.xml`, `/news-sitemap.xml`
- `/admin/sources` and `/admin/login` with `ADMIN_PANEL_PASSWORD` set

## Local run

```bash
pip install -r requirements.txt
python app.py
```

The repository CI runs Python byte-compilation and focused unit tests for source/language enforcement and image search matching. The live Supabase database, Gemini credentials, external image APIs, SMTP configuration and Render deployment still need production smoke tests after deploying. Never commit API keys or SMTP credentials to GitHub.

If Gemini Q&A is disabled or fails, check `/api/news-status` for non-secret readiness information (key configured, SDK availability, active model, provider setup and the last Gemini error type), then inspect Render server logs. The app keeps verified source-language headlines available if Gemini editing is temporarily unavailable. The current default model is `gemini-3.8-flash`; if your Render variable overrides `GEMINI_MODEL`, confirm the selected model is enabled for your API key.
