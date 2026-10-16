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

The article-level Ask-Me AI question panel and `/api/ask` endpoint are removed. Gemini is used for bilingual editorial briefs; Gemini-generated news imagery is disabled in production so generated artwork cannot be mistaken for documentary photography.

## Image sourcing
The Openverse API adapter and item-level licence validator live in `image_sources.py`, separate from the Flask routes and database logic; the app injects its scoring, URL-safety and HTTP helpers for deterministic tests.


The image pipeline derives short, topic-specific queries from story headlines and available RSS context. It checks Wikimedia Commons and Openverse first, then the Library of Congress, NASA for relevant topics, and manually approved press-kit assets. Every external image must include item-level source-page and licence provenance; an API result or provider name alone is not enough. Pexels and Unsplash are inactive in production.

Gemini-generated images are disabled in production. If no image passes item-level rights checks, Arabic pages use the brand-owned `static/A.jpg` asset and English pages use `static/E.jpg`. These fallback assets are not presented as documentary photographs. The article's image URL, source, creator/credit, provider page and licence link remain stored with the article in Supabase; the retry/freshness timer does not delete those records. Failed searches for missing photos are retried after 1 hour by default.

API access and a free-to-view website do not mean an image is universally copyright-free. Follow each provider's current terms, item-level licence, attribution rules, hotlinking requirements and any third-party privacy, publicity, trademark or copyright rights. Human review is still required for commercial publication.

## Environment variables
- `FLASK_SECRET_KEY`: random session secret.
- `SUPABASE_POOLER_URL` or `DATABASE_URL`: PostgreSQL/Supabase connection.
- `GEMINI_API_KEY`: private key for editorial summaries and optional images; never commit it to GitHub.
- `GEMINI_MODEL`: text model (default `gemini-3.8-flash`).
- `GEMINI_IMAGE_MODEL`: image model (default `gemini-nano-banana-2.1`).
- `GEMINI_IMAGE_GENERATION_ENABLED=false`, `MAX_GEMINI_IMAGES_PER_REFRESH=0`, `MAX_GEMINI_IMAGES_PER_24H=0`: production uses reusable licensed image records or A/E brand fallbacks, not generated pseudo-documentary imagery. `GEMINI_429_COOLDOWN_MINUTES=60` and `GEMINI_TRANSIENT_ERROR_COOLDOWN_MINUTES=10` keep text-generation retries bounded while headline discovery can continue if Gemini is unavailable.
- `NEWS_AUTO_FETCH=true`, `NEWS_SCHEDULER_ENABLED=true`, `NEWS_REFRESH_MINUTES=30`, `NEWS_RETRY_MINUTES=10`, `NEWS_SCHEDULER_POLL_SECONDS=30`, `MAX_ARTICLES_PER_REFRESH=24`, `MAX_ARTICLES_PER_CATEGORY=3`: an elected Gunicorn worker starts a recurring background scheduler on the first live request and checks cadence independently of later homepage visits. OS locks prevent multiple scheduler leaders and overlapping refreshes on the same Render instance.
- `RSS_TIMEOUT_SECONDS=6`, `RSS_BATCH_TIMEOUT_SECONDS=20`: per-feed timeout and maximum wait for a complete RSS discovery batch. If some feeds hang, the app proceeds with completed feed results rather than holding the entire news refresh indefinitely.
- `IMAGE_ENRICHMENT_BATCH_TIMEOUT_SECONDS=65`: overall maximum time for each batch of concurrent external photo searches. Each story searches open catalogues concurrently before falling back to NASA/press-kit/stock API sources, reducing the chance of timing out before alternatives are tried. News are saved first; if photo providers stall, completed matches are stored and older safe images are preserved for unfinished items so the news-refresh lock is released promptly.
- `MAX_IMAGE_LOOKUPS_PER_REFRESH=24`, `IMAGE_RETRY_AFTER_HOURS=1`, and `IMAGE_CACHE_MAX_AGE_HOURS=24` (up to eight existing articles are rechecked in a regular refresh): per-refresh photo lookup budget, retry interval for missing images, and freshness window for existing photo matches. The freshness window does not delete stored records or force every image to change when no better result exists.
- Pexels and Unsplash API adapters remain isolated for tests but are intentionally excluded from active production image search. The live pipeline does not depend on `PEXELS_API_KEY` or `UNSPLASH_ACCESS_KEY`.
- `CONTENT_LICENSE_APPROVED_DOMAINS`: only after source-specific rights review, with permission evidence retained.
- `ADMIN_PANEL_PASSWORD`: enables `/admin/login`, `/admin/monitor`, and `/admin/sources`; use a strong password. The protected monitoring page reports safe database state, Gemini cooldown and image search/storage probes without exposing secrets.
- `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: optional contact delivery.


### Supabase URL compatibility
The application normalizes the configured shared Supabase pooler URL before passing it to `psycopg2`: it uses the Transaction Pooler port `6543` for shared pooler hosts, removes the Prisma-only `pgbouncer` URI flag, and trims accidental whitespace around the database name. This does not repair an invalid password or project-specific pooler username; those must match the connection details in Supabase Dashboard → Connect. Never publish the connection URL or password.


## Image sourcing
Images are selected by searching title phrases that combine distinct headline terms with RSS-excerpt context. Wikimedia Commons and Openverse are tried first with explicit item-level reuse checks; when that query has no match, the shorter headline is retried against open catalogues. Library of Congress, NASA, and approved press-kit sources follow when relevant. The active production chain does not rely on Pexels or Unsplash APIs. Photographer attribution, item page, provider, and licence link are retained. If no suitable, rights-checked photo is found, the site uses the brand-owned `static/A.jpg` or `static/E.jpg` fallback according to article language.

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

The automated test suite covers language/source enforcement, Openverse licence filtering (CC0/PDM/CC BY/CC BY-SA), attribution metadata, inactive stock-provider exclusion, title/context query variants, image relevance scoring, image fallback rendering, and NASA/Commons rights policy. Live credentials, the production database, external API quotas and the actual rights status of individual images cannot be certified by unit tests alone; monitor `/api/news-status`, `/admin/monitor` and Render logs.

### Scheduled refresh and connection guardrails

The web service has a per-worker PostgreSQL connection concurrency cap (`DB_MAX_CONCURRENT_CONNECTIONS`, default 3; maximum 6) and a bounded wait (`DB_CONNECTION_WAIT_SECONDS`, default 2). With two Gunicorn workers and the default cap, application code opens at most six DB connections concurrently in that web-service instance. Every checked-out connection is closed in a `finally` block and releases its slot. This is a concurrency guard, not a substitute for using the Supabase Transaction Pooler URL on the configured pooler port.

The public `/api/news-status` endpoint reports cached database health instead of issuing a separate `SELECT 1` connection on every poll. The protected admin monitor keeps an active database probe for diagnostics.

For reliable scheduled triggering independent of homepage visits, `trigger_news_refresh.py` can be run by a Render Cron Job every 30 minutes with:

- Command: `python trigger_news_refresh.py`
- Schedule: `*/30 * * * *` (Render schedules are in UTC).
- `NEWS_REFRESH_TARGET_URL=https://nabd-news.onrender.com`
- `NEWS_REFRESH_WEBHOOK_TOKEN`: the same random value (at least 32 characters) set on the web service and the Cron Job.

The trigger uses HTTPS and sends the token only in an Authorization header. The web app's `POST /api/internal/refresh` endpoint is disabled until a valid token is configured and returns a non-disclosing response for incorrect tokens. The Cron Job does not need the Supabase URL or Gemini API key.

Once the Cron Job is created and verified, set `NEWS_SCHEDULER_ENABLED=false` on the web service so the in-process scheduler does not compete with the external schedule. Keep it enabled when no external scheduler is configured. Creating a Render Cron Job may incur a separate recurring charge; the code path alone does not create or enable that paid service.


### Fast article navigation

The sorted and deduplicated display pool is cached per language for a short period to avoid repeating a full article-list scan on every article click. Database writes invalidate both the database-row cache and display-pool cache. This is a performance cache only; article records remain in Supabase.

### Persistent storage versus temporary cache
Article records and image URLs, source attribution, provider links, licence metadata, and image-check timestamps are stored in the Supabase PostgreSQL table `world_pulse_articles`. The short-lived in-process article cache is only a performance optimization and is invalidated after database writes. The image freshness window controls when the app repeats external image searches; it does not expire or delete the database records. The protected admin image-refresh action bypasses that freshness window for up to 12 recent articles, clears the current worker's short-lived display cache, and writes successful replacements back to Supabase while preserving the existing image if no suitable replacement is found.


### Continuous refresh while a page stays open

The web app starts an in-process scheduler after its first request and the scheduler then checks the refresh interval in the background. The operating-system lock prevents duplicate scheduler leaders among workers on the same Render instance, but this thread cannot survive a service sleep, restart or suspension. The public `/api/news-status` endpoint reports status only; it is not the scheduler. For a schedule that must fire even without visitors, configure the separate Cron trigger described under “Scheduled refresh and connection guardrails” and disable `NEWS_SCHEDULER_ENABLED` only after that Cron Job is verified.

### Refresh reliability during Gemini quota errors
Google News RSS discovery is restricted to the most recent seven days so high-relevance older stories are less likely to crowd fresh items out of the ingestion batch. If an RSS item has no excerpt and Gemini is unavailable, the site stores a transparent source-language note directing readers to the publisher instead of inserting an empty summary that hides the headline. Gemini rate-limit and temporary server-error cooldowns are shared through Supabase so separate Gunicorn workers do not repeatedly call an unavailable model. Automatic image backfills rotate by oldest image-check time; manual image refresh waits briefly for the current news refresh lock rather than being silently discarded.


### News ingestion is no longer blocked on image-provider latency
New RSS headlines and bilingual briefs are saved to Supabase before photo search begins. External image searches are treated as a separate enrichment step; a timeout or provider quota issue can delay image replacement, but it cannot hold newly discovered headlines out of the news table. Each regular refresh also checks a small rotating batch of articles with missing images or image matches older than the configured image-cache window, keeping valid existing imagery if no suitable replacement is found.


### AI image generation disabled

Gemini image generation is disabled by default. News images are sourced from external catalogues and providers with source/reuse metadata; when no suitable result is found, the editorial fallback remains. The site does not intentionally bypass copyright or licensing restrictions.

### Context-aware image search
Photo discovery combines the most distinctive terms from a story headline with keywords from its source excerpt, then retries the headline on its own. Relevance scoring accepts a strong single-entity overlap for short, provider-ranked queries while still requiring the image itself to pass the item's licence and attribution checks. The image-enrichment batch has an overall deadline so slow providers cannot hold the news refresh lock.


### RSS discovery query performance
Google News RSS requests use compact topic queries with a seven-day freshness filter. Results are still filtered against the site's enabled publisher/category/language allowlist after retrieval; no article from an unapproved domain is published. Avoiding a very large per-query `site:domain OR site:domain...` expression keeps individual category feeds shorter and more resilient.
