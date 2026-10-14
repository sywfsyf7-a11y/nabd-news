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
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash` for bilingual editorial summaries and Q&A.
- `GEMINI_TIMEOUT_SECONDS`: default `20`.
- `GEMINI_IMAGE_MODEL`: defaults to `gemini-nano-banana-2.1` for image generation using the same `GEMINI_API_KEY`.
- `GEMINI_IMAGE_GENERATION_ENABLED=true` enables AI-generated editorial illustrations.
- `MAX_GEMINI_IMAGES_PER_REFRESH=3` and `MAX_GEMINI_IMAGES_PER_24H=8` bound generation cost; set lower or to `0` to disable generation.
- `GEMINI_IMAGE_TIMEOUT_SECONDS=75` limits the image-generation request time.
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

For a new story that needs an image, World Pulse first attempts to generate an original 16:9 editorial illustration using the configured Gemini image model. The prompt is assembled from the verified headline, short source excerpt, category and original language. It asks for clean vector/infographic artwork, minimal localized headline text, a World Pulse brand footer, generic icons rather than copied third-party logos, and no invented facts or statistics. A generated visual is an illustration, not documentary evidence.

Generation uses the existing `GEMINI_API_KEY`, but uses `GEMINI_IMAGE_MODEL` separately from the text model. It is quota-limited by default to 3 attempts per refresh and 8 generated images per rolling 24 hours. Native image generation may require a paid/eligible API tier and can incur charges. Failures, missing model access, exhausted quota, or unavailable database storage cause the app to fall back to the existing sources below.

The generated image bytes and the prompt used are stored persistently in the PostgreSQL/Supabase database, not on Render's temporary filesystem. The image is served from `/media/generated/<id>`. Existing fallback providers remain in order: eligible Wikimedia Commons images, manually approved press-kit assets, then configured official Pexels/Unsplash API results. Those provider results retain credit/license details. Google News is used only for news discovery, never as an image provider.

When no suitable image is generated or found, the templates use `static/A.jpg` for Arabic-origin stories and `static/E.jpg` for English-origin stories, independent of the current page language. The same image fallback is used for article Open Graph metadata. Remove/review a published image from `/admin/sources`.

AI-generated images are not a guarantee of copyright clearance or legal safety. The prompt deliberately avoids third-party brand logos and recognisable copyrighted characters, but review output before commercial use, particularly if a generated image resembles a real person, trademark, distinctive product design or protected artwork. Review Google's current API/terms/pricing and keep the daily cap appropriate for your budget.

## Routes

- `/` latest news and category filters
- `/search?q=...` searchable article database
- `/article/<slug>` editorial story and Q&A
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/api/ask`, `/healthz`
- `/robots.txt`, `/sitemap.xml`, `/news-sitemap.xml`, `/media/generated/<image_id>`
- `/admin/sources` and `/admin/login` with `ADMIN_PANEL_PASSWORD` set

## Local run

```bash
pip install -r requirements.txt
python app.py
```

The repository CI runs Python byte-compilation and focused unit tests for source/language enforcement and image search matching. The live Supabase database, Gemini credentials, external image APIs, SMTP configuration and Render deployment still need production smoke tests after deploying. Never commit API keys or SMTP credentials to GitHub.

If Gemini Q&A is disabled or fails, check `/api/news-status` for non-secret readiness information (key configured, SDK availability, active model, provider setup and the last Gemini error type), then inspect Render server logs. The app keeps verified source-language headlines available if Gemini editing is temporarily unavailable. The current default model is `gemini-3.8-flash`; if your Render variable overrides `GEMINI_MODEL`, confirm the selected model is enabled for your API key.
