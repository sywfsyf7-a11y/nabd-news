# World Pulse / نبض العالم

A bilingual news portal that discovers real stories from publisher sources, creates short Arabic/English editorial briefs from the available source metadata, links to the original report, and attempts to find a topic-relevant image with recorded reuse information.

## Live deployment
- Website: https://nabd-news.onrender.com/
- Hosting: Render Python web service, connected to the `main` branch with automatic deploys.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --workers 2 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app`
- Health endpoint: `/healthz`; non-secret news/image readiness: `/api/news-status`.

## Global news coverage
The catalog has 270 category/language assignments across 168 distinct publisher domains, arranged across politics, economy, technology, gaming, sports, science, culture and world news. It includes Arabic and English publisher sources separately, with additional Middle Eastern, European, North American, Asian and science/sports/game outlets. The catalog is curated and expandable; it cannot truthfully claim to include every news publisher worldwide.

Google News RSS is used only to discover headlines, short excerpts and source links. The discovered publisher host is checked against the category/language allowlist. BBC (`bbc.com` / `bbc.co.uk`) and Al Jazeera Arabic/English (`aljazeera.net` / `aljazeera.com`) are present in headline-and-link-only mode by default: the site does not reuse their RSS descriptions or ask Gemini to rewrite their article body without a source-specific rights approval. CNN is included in regular category-based discovery. See `SOURCES.md` for the rights policy.

## Editorial briefs, not fabricated reporting
Gemini receives the source headline and a short RSS excerpt to prepare a bilingual title, summary and brief. The prompt prohibits invented names, dates, places, numbers, quotes, causes, motives, outcomes and unsupported background. If an excerpt is thin, the correct output is a concise brief and a link to the source—not generic filler. AI summaries can still be wrong or incomplete, so readers should follow the original publisher for detail and verification.

The article-level Ask-Me AI question panel and `/api/ask` endpoint are removed. Bilingual article summarization and the optional Gemini illustration feature are separate and remain available.

## Image sourcing

The system first searches for a topic-relevant image from Wikimedia Commons (Public Domain Mark, CC0, CC BY or CC BY-SA only, with required creator attribution), then Library of Congress photo records whose own item page explicitly marks them as public domain or having no known restrictions, then manually approved press-kit assets, and official Pexels/Unsplash APIs when their credentials are configured. Provider/item pages, photographer credit and licence details are retained where available.

Only when no suitable sourced image is found, the site may generate a topic-specific 16:9 Gemini editorial illustration, within the configured limits. A generated illustration is labelled as illustrative content and is not documentary evidence. The CI suite also checks local SVG fallback safety and the BBC/Al Jazeera headline-only policy.

When no appropriate sourced or generated image is available, the site creates a distinct local 16:9 SVG editorial visual, with a category-specific palette and motif and the story headline rendered safely into the image. This is clearly labelled as editorial art, not documentary photography. Failed image searches are retried after 12 hours by default rather than waiting a week. The old `static/A.jpg` and `static/E.jpg` placeholders are no longer the news-card or article-hero fallback. Publisher page thumbnails, Google News thumbnails and generic image-search results are not treated as free-to-use assets.

API access and a free-to-view website do not mean an image is universally copyright-free. Follow each provider's current terms, item-level licence, attribution rules, hotlinking requirements and any third-party privacy, publicity, trademark or copyright rights. Human review is still required for commercial publication.

## Environment variables
- `FLASK_SECRET_KEY`: random session secret.
- `SUPABASE_POOLER_URL` or `DATABASE_URL`: PostgreSQL/Supabase connection.
- `GEMINI_API_KEY`: private key for editorial summaries and optional images; never commit it to GitHub.
- `GEMINI_MODEL`: text model (default `gemini-3.8-flash`).
- `GEMINI_IMAGE_MODEL`: image model (default `gemini-nano-banana-2.1`).
- `GEMINI_IMAGE_GENERATION_ENABLED=true`, `MAX_GEMINI_IMAGES_PER_REFRESH=2`, `MAX_GEMINI_IMAGES_PER_24H=8`, `GEMINI_429_COOLDOWN_MINUTES=60`: bounded image-generation caps and a circuit breaker after Gemini 429 responses; generation may require a paid/eligible API tier.
- `NEWS_AUTO_FETCH=true`, `NEWS_REFRESH_MINUTES=30`, `NEWS_RETRY_MINUTES=10`, `MAX_ARTICLES_PER_REFRESH=24`, `MAX_ARTICLES_PER_CATEGORY=3`: news refresh cadence and ingestion caps. A shared worker lock prevents duplicate concurrent refreshes on the same Render instance.
- `MAX_IMAGE_LOOKUPS_PER_REFRESH=16`, `IMAGE_RETRY_AFTER_HOURS=12`: per-refresh photo lookup budget and retry interval for articles that have no suitable image.
- `UNSPLASH_ACCESS_KEY`, `PEXELS_API_KEY`: optional official image API credentials. These providers are skipped unless their keys are configured in Render.
- `CONTENT_LICENSE_APPROVED_DOMAINS`: only after source-specific rights review, with permission evidence retained.
- `ADMIN_PANEL_PASSWORD`: enables `/admin/login`, `/admin/monitor`, and `/admin/sources`; use a strong password. The protected monitoring page reports safe database state, Gemini cooldown and image search/storage probes without exposing secrets.
- `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: optional contact delivery.


### Supabase URL compatibility
The application normalizes the configured shared Supabase pooler URL before passing it to `psycopg2`: it uses the Transaction Pooler port `6543` for shared pooler hosts, removes the Prisma-only `pgbouncer` URI flag, and trims accidental whitespace around the database name. This does not repair an invalid password or project-specific pooler username; those must match the connection details in Supabase Dashboard → Connect. Never publish the connection URL or password.


## Article reading experience
Article pages include a prominent original-source link, an optional Arabic/English edition switch when both versions exist, clear labeling for AI-generated illustrative images, a compact source/timestamp/language metadata panel, and a sticky related-stories column on wide screens. Source attribution and licence links remain visible when provided.

## Routes
- `/`: latest news, language choice and category filters
- `/search?q=...`: search indexed stories
- `/article/<slug>`: bilingual brief, image attribution and original source link
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/healthz`
- `/robots.txt`, `/sitemap.xml`, `/news-sitemap.xml`
- `/media/generated/<image_id>`
- `/admin/monitor` (admin login required; safe database, Gemini and image diagnostic dashboard)
- `/admin/sources` (admin login required)

## Run locally and test
```bash
pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
```

The automated test suite covers language/source enforcement and key image-sourcing logic. A template-compilation regression test checks the news page's Jinja syntax. Live credentials, the production database, external API quotas and actual image rights cannot be certified by unit tests alone; monitor `/api/news-status` and Render logs.