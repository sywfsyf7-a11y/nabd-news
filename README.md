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
The Openverse API adapter and item-level licence validator live in `image_sources.py`, separate from the Flask routes and database logic; the app injects its scoring, URL-safety and HTTP helpers for deterministic tests.


The image pipeline searches short, topic-specific phrases derived from each story headline across Wikimedia Commons and Openverse, then checks the Library of Congress, NASA when the topic fits, and manually approved press kits. If those sources do not produce a suitable result, the pipeline can query Pexels and Unsplash using their official photo-search APIs when the corresponding API keys are configured. Photographer attribution, the original photo page, the provider, and the licence link are retained for display. If no suitable photo is found, a bounded Gemini illustration may be generated separately; if that is unavailable too, the page shows a topic-specific local SVG illustration rather than a generic placeholder.

Only when no suitable sourced image is found, the site may generate a topic-specific 16:9 Gemini editorial illustration, within the configured limits. A generated illustration is labelled as illustrative content and is not documentary evidence. The CI suite also checks local SVG fallback safety and the BBC/Al Jazeera headline-only policy.

When no appropriate sourced or generated image is available, the site creates a distinct local 16:9 SVG editorial visual, with a category-specific palette and motif and the story headline rendered safely into the image. This is clearly labelled as editorial art, not documentary photography. The artwork's palette, decorative accents and motif angle vary deterministically by story, so fallback cards do not all repeat the same graphic. Failed image searches are retried after 1 hour by default rather than waiting a week. The old `static/A.jpg` and `static/E.jpg` placeholders are no longer the news-card or article-hero fallback. The CI suite compiles the Jinja news template and checks the SVG route's output and title escaping. Publisher page thumbnails, Google News thumbnails and generic image-search results are not treated as free-to-use assets.

API access and a free-to-view website do not mean an image is universally copyright-free. Follow each provider's current terms, item-level licence, attribution rules, hotlinking requirements and any third-party privacy, publicity, trademark or copyright rights. Human review is still required for commercial publication.

## Environment variables
- `FLASK_SECRET_KEY`: random session secret.
- `SUPABASE_POOLER_URL` or `DATABASE_URL`: PostgreSQL/Supabase connection.
- `GEMINI_API_KEY`: private key for editorial summaries and optional images; never commit it to GitHub.
- `GEMINI_MODEL`: text model (default `gemini-3.8-flash`).
- `GEMINI_IMAGE_MODEL`: image model (default `gemini-nano-banana-2.1`).
- `GEMINI_IMAGE_GENERATION_ENABLED=true`, `MAX_GEMINI_IMAGES_PER_REFRESH=1`, `MAX_GEMINI_IMAGES_PER_24H=4`, `GEMINI_429_COOLDOWN_MINUTES=60`, `GEMINI_TRANSIENT_ERROR_COOLDOWN_MINUTES=10`: conservative image-generation caps; the text pipeline pauses on 429 quota errors or temporary Gemini 5xx failures rather than retrying every batch in the same refresh. News/image sourcing continues using source-language headlines while Gemini is unavailable.
- `NEWS_AUTO_FETCH=true`, `NEWS_REFRESH_MINUTES=30`, `NEWS_RETRY_MINUTES=10`, `MAX_ARTICLES_PER_REFRESH=24`, `MAX_ARTICLES_PER_CATEGORY=3`: news refresh cadence and ingestion caps. A shared worker lock prevents duplicate concurrent refreshes on the same Render instance.
- `MAX_IMAGE_LOOKUPS_PER_REFRESH=24`, `IMAGE_RETRY_AFTER_HOURS=1` (up to six older missing-image records are checked in each refresh cycle): per-refresh photo lookup budget and retry interval for articles that have no suitable image.
- `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`: optional secret API keys for title-keyword photo search on Pexels and Unsplash. Set these in Render → Environment, never in source control. These providers are tried only after the earlier open-licence/archive sources fail; without a key, each provider is skipped. Pexels currently reports that new API-key issuance is paused, so an existing key may be needed.
- `CONTENT_LICENSE_APPROVED_DOMAINS`: only after source-specific rights review, with permission evidence retained.
- `ADMIN_PANEL_PASSWORD`: enables `/admin/login`, `/admin/monitor`, and `/admin/sources`; use a strong password. The protected monitoring page reports safe database state, Gemini cooldown and image search/storage probes without exposing secrets.
- `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: optional contact delivery.


### Supabase URL compatibility
The application normalizes the configured shared Supabase pooler URL before passing it to `psycopg2`: it uses the Transaction Pooler port `6543` for shared pooler hosts, removes the Prisma-only `pgbouncer` URI flag, and trims accidental whitespace around the database name. This does not repair an invalid password or project-specific pooler username; those must match the connection details in Supabase Dashboard → Connect. Never publish the connection URL or password.


## Image sourcing
Images are selected by searching short, relevant phrases from the story headline. Wikimedia Commons and Openverse are tried first with explicit item-level reuse checks; Library of Congress, NASA, and approved press-kit sources follow when relevant. If none returns a suitable match, Pexels and Unsplash can be queried through their official APIs when their API keys are present and their admin controls are enabled. Attribution and photo-page links are retained; Unsplash URLs returned by its API are hotlinked as required by its API guidelines. If no suitable photo is found, the site uses a bounded AI illustration or a distinct local 16:9 editorial SVG, not a generic A.jpg/E.jpg fallback.

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

The automated test suite covers language/source enforcement, Openverse licence filtering (CC0/PDM/CC BY/CC BY-SA), attribution metadata, Pexels/Unsplash API request headers, title-keyword matching and attribution, image fallback rendering and NASA/Commons rights policy. Live credentials, the production database, external API quotas and the actual rights status of individual images cannot be certified by unit tests alone; monitor `/api/news-status`, `/admin/monitor` and Render logs.

### Persistent storage versus temporary cache
Article records and image URLs, source attribution, provider links, licence metadata, and image-check timestamps are stored in the Supabase PostgreSQL table `world_pulse_articles`. The short-lived in-process article cache is only a performance optimization and is invalidated after database writes. The image freshness window controls when the app repeats external image searches; it does not expire or delete the database records. The protected admin image-refresh action bypasses that freshness window for up to 12 recent articles, clears the current worker's short-lived display cache, and writes successful replacements back to Supabase while preserving the existing image if no suitable replacement is found.
