# World Pulse / نبض العالم

A bilingual news portal that discovers real stories from publisher sources, creates short Arabic/English editorial briefs from the available source metadata, links to the original report, and attempts to find a topic-relevant image with recorded reuse information.

## Live deployment
- Website: https://nabd-news.onrender.com/
- Hosting: Render Python web service, connected to the `main` branch with automatic deploys.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --workers 2 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app`
- Health endpoint: `/healthz`; non-secret news/image readiness: `/api/news-status`.

## Global news coverage
The catalog has 259 category/language assignments across 166 distinct source domains, arranged across politics, economy, technology, gaming, sports, science, culture and world news. It includes Arabic and English publisher sources separately, with additional Middle Eastern, European, North American, Asian and science/sports/game outlets. The catalog is curated and expandable; it cannot truthfully claim to include every news publisher worldwide.

Google News RSS is used only to discover headlines, short excerpts and source links. The site verifies the discovered publisher host against the category/language allowlist and filters headline-language mismatches. Restricted publishers remain blocked unless a rights review supports enabling them. See `SOURCES.md` for the full list and rights policy.

## Editorial briefs, not fabricated reporting
Gemini receives the source headline and a short RSS excerpt to prepare a bilingual title, summary and brief. The prompt prohibits invented names, dates, places, numbers, quotes, causes, motives, outcomes and unsupported background. If an excerpt is thin, the correct output is a concise brief and a link to the source—not generic filler. AI summaries can still be wrong or incomplete, so readers should follow the original publisher for detail and verification.

The article-level Ask-Me AI question panel and `/api/ask` endpoint are removed. Bilingual article summarization and the optional Gemini illustration feature are separate and remain available.

## Image sourcing
Eligible imagery is tried in this order: topic-specific Gemini illustration (if configured and within quota), eligible Wikimedia Commons media (CC0 / Public Domain / CC BY only), rights-filtered Library of Congress photo records, manually approved press-kit assets, and official Pexels/Unsplash API results when keys are configured. Provider, item/credit URL and licence/item record are stored where supplied.

When no suitable image passes the checks, the fallback is `static/A.jpg` for Arabic-origin stories and `static/E.jpg` for English-origin stories, regardless of which language UI is open. The app does not treat publisher thumbnails, Google News thumbnails or image-search results as free-to-use assets.

API access and a free-to-view website do not mean an image is universally copyright-free. Follow each provider's current terms, item-level licence, attribution rules, hotlinking requirements and any third-party privacy, publicity, trademark or copyright rights. Human review is still required for commercial publication.

## Environment variables
- `FLASK_SECRET_KEY`: random session secret.
- `SUPABASE_POOLER_URL` or `DATABASE_URL`: PostgreSQL/Supabase connection.
- `GEMINI_API_KEY`: private key for editorial summaries and optional images; never commit it to GitHub.
- `GEMINI_MODEL`: text model (default `gemini-3.8-flash`).
- `GEMINI_IMAGE_MODEL`: image model (default `gemini-nano-banana-2.1`).
- `GEMINI_IMAGE_GENERATION_ENABLED=true`, `MAX_GEMINI_IMAGES_PER_REFRESH=3`, `MAX_GEMINI_IMAGES_PER_24H=8`: image-generation controls; generation may require a paid/eligible API tier.
- `NEWS_AUTO_FETCH=true`, `NEWS_REFRESH_MINUTES=15`, `MAX_ARTICLES_PER_REFRESH=32`, `MAX_ARTICLES_PER_CATEGORY=5`: news ingestion controls.
- `UNSPLASH_ACCESS_KEY`, `PEXELS_API_KEY`: optional official image API credentials.
- `CONTENT_LICENSE_APPROVED_DOMAINS`: only after source-specific rights review, with permission evidence retained.
- `ADMIN_PANEL_PASSWORD`: enables `/admin/login` and `/admin/sources`; use a strong password.
- `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: optional contact delivery.

## Routes
- `/`: latest news, language choice and category filters
- `/search?q=...`: search indexed stories
- `/article/<slug>`: bilingual brief, image attribution and original source link
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/healthz`
- `/robots.txt`, `/sitemap.xml`, `/news-sitemap.xml`
- `/media/generated/<image_id>`
- `/admin/sources` (admin login required)

## Run locally and test
```bash
pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
```

The automated test suite covers language/source enforcement and key image-sourcing logic. Live credentials, the production database, external API quotas and actual image rights cannot be certified by unit tests alone; monitor `/api/news-status` and Render logs.