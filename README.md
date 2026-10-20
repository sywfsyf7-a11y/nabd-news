# Nabd News / نبض نيوز

A bilingual news portal that discovers real stories from publisher sources, creates short Arabic/English editorial briefs from the available source metadata, links to the original report, and attempts to find a topic-relevant image with recorded reuse information.

## Live deployment
- Website: https://nabd-news.onrender.com/
- Hosting: Render Python web service, connected to the `main` branch with automatic deploys.
- Build command: `npm install --no-audit --no-fund && npm run build:css && pip install -r requirements.txt`
- Start command: `gunicorn --workers 2 --threads 4 --timeout 90 --bind 0.0.0.0:$PORT app:app`
- Frontend styles: production uses the checked-in compiled `static/css/site.css`; developers/CI can regenerate it with `npm run build:css`. Pages load local CSS rather than Tailwind's browser-side Play CDN.
- Health endpoint: `/healthz`; non-secret news/image readiness: `/api/news-status`.

## Global news coverage
The source catalog is intentionally curated across politics, economy, technology, gaming, sports, science, culture and world news. Both Arabic-origin and English-origin stories can appear together on either interface; category filters apply to both. A complete, quality-checked translation is used when available. Otherwise the story remains in its source language, visibly labelled as Arabic or English, rather than being shown as a bad or fabricated translation. Headline-only or too-thin records link directly to the original publisher instead of producing a low-value article page.

Google News RSS is the discovery transport, not the publisher attribution. Queries are restricted to the curated category/language publisher lists; the system resolves and stores the original publisher URL where it can verify the destination. Discovery runs every 15 minutes. Inclusion in the allowlist does not guarantee that a publisher returns a new story in every scan. BBC, Al Jazeera, Reuters, Associated Press, TechCrunch, ESPN, ScienceDaily, The Guardian and The Athletic are headline-and-source-link-only by default unless a rights review documents permission. The service does not scrape full publisher articles to rewrite them, does not scrape Al Jazeera pages, and does not copy restricted article text or images. Attribution alone does not grant a content or image licence. See `SOURCES.md` for the rights policy.

## Publishing cadence and resilience

The background scheduler publishes **at most one new story every five minutes**. RSS discovery runs every 15 minutes, adds a bounded batch of eligible candidates, resolves Google News redirects to the original allowlisted publisher where possible, and stores the pending queue in Supabase so a restart does not reset it. Each publishing tick handles one story and permits at most two Gemini calls (a bounded fallback if the first model fails); image discovery is time-bounded and runs after the story is saved. Older articles and stored licensed images are not deleted by queue processing or repair timers.

## Editorial briefs, not fabricated reporting
Gemini receives the source headline and a short RSS excerpt to prepare an original bilingual title, executive summary and details. The editorial prompt requires an independent synthesis rather than synonym-swapping or line-by-line paraphrase, prohibits invented names, dates, places, numbers, quotes, causes, motives, outcomes and unsupported background, and asks for distinct details only when supported by the excerpt. If the source is headline-only or too thin, the article links directly to the publisher instead of creating a low-value internal page. AI summaries can still be wrong or incomplete, so readers should follow the original publisher for detail and verification.

The article-level Ask-Me AI question panel and `/api/ask` endpoint are removed. Gemini is used for bilingual editorial briefs; Gemini-generated news imagery is disabled in production so generated artwork cannot be mistaken for documentary photography.

## Image sourcing
The Openverse API adapter and item-level licence validator live in `image_sources.py`, separate from the Flask routes and database logic; the app injects its scoring, URL-safety and HTTP helpers for deterministic tests.


The image pipeline derives short, topic-specific queries from each headline and available source excerpt. It checks Wikimedia Commons, Openverse and the Library of Congress. Culture stories can also search the Art Institute of Chicago, The Met and Cleveland Museum of Art (CC0 records only); Wellcome Collection is searched for science/culture images with an item-level CC0 or CC BY licence; NASA is limited to relevant science/space/Earth stories, and press-kit assets require a separately reviewed approval manifest. Every selected image must pass item-level rights checks and keep its source page, creator credit and exact licence. Photos presented as evidence for a specific news event require a stricter 0.40 story-relevance score; the lower 0.26 threshold applies only to clearly labelled category-themed illustrative images, never as documentary evidence. Weakly related results are rejected so the site uses a clearly labelled topic-specific SVG illustration instead of a misleading photo. Unsplash and Pexels APIs are not used. Approved images are validated, optimized and cached in Supabase.

Gemini-generated news photographs are disabled in production. If no photo passes item-level rights checks and topic relevance, the site serves a small, locally generated SVG illustration matched to the story section and title. It is visibly labeled as editorial illustration, not documentary photography, and avoids substituting the old A/E placeholders. Licensed image bytes are stored in the `world_pulse_catalogued_images` Supabase table (optimized JPEGs, with the story's original source, creator/credit and exact licence URL kept in `world_pulse_articles`). Failed and legacy A/E placeholder image searches are retried after 1 hour by default; the retry timer does not delete records.

API access and a free-to-view website do not mean an image is universally copyright-free. Follow each provider's current terms, item-level licence, attribution rules, hotlinking requirements and any third-party privacy, publicity, trademark or copyright rights. Human review is still required for commercial publication.

## Environment variables
- `FLASK_SECRET_KEY`: random session secret.
- `SUPABASE_POOLER_URL` or `DATABASE_URL`: PostgreSQL/Supabase connection.
- `GEMINI_API_KEY`: private key for editorial summaries and optional images; never commit it to GitHub.
- `GEMINI_MODEL=gemini-3.5-flash-lite`: primary model. Failover order is `gemini-3.8-flash`, then `gemini-3.1-flash-lite` if a model returns `429`, transient `5xx`, malformed JSON, or an incomplete response. The SDK uses `HttpRetryOptions(attempts=1)` so hidden retries cannot multiply calls. The publishing scheduler handles at most one new queued story per five-minute tick. When eligible source material is available, the same compact editorial request also repairs one previously published article with thin or repeated details; headline-only and other restricted sources are skipped. `MAX_GEMINI_API_CALLS_PER_REFRESH=2` allows a bounded fallback attempt for the small request; each model has its own persisted cooldown. If all configured models fail or the project quota is exhausted, the site preserves the original publisher headline/excerpt rather than inventing details, and eligible stories can be enriched on a later retry.
- `GEMINI_IMAGE_MODEL`: image model (default `gemini-nano-banana-2.1`).
- `GEMINI_IMAGE_GENERATION_ENABLED=false`, `MAX_GEMINI_IMAGES_PER_REFRESH=0`, `MAX_GEMINI_IMAGES_PER_24H=0`: production uses reusable, rights-checked source photos or distinct topic-specific SVG editorial art when no photo is found, not generated pseudo-documentary imagery. `GEMINI_429_COOLDOWN_MINUTES=60` and `GEMINI_TRANSIENT_ERROR_COOLDOWN_MINUTES=10` keep text-generation retries bounded while headline discovery can continue if Gemini is unavailable.
- `NEWS_AUTO_FETCH=true`, `NEWS_SCHEDULER_ENABLED=true`, `NEWS_REFRESH_MINUTES=5`, `NEWS_RETRY_MINUTES=5`, `NEWS_DISCOVERY_REFRESH_MINUTES=15`, `MAX_ARTICLES_PER_REFRESH=1`, `MAX_PENDING_NEWS_CANDIDATES=60`, `MAX_QUEUE_ADDITIONS_PER_DISCOVERY=3`, `NEWS_SCHEDULER_POLL_SECONDS=30`: the elected scheduler publishes at most one new queued story every five minutes, when an eligible story is waiting. RSS discovery runs every 15 minutes and adds at most three new candidates per scan, aligned with the three five-minute publication slots in that window; stale higher overrides are capped in code. The pending headline/source metadata queue is persisted in Supabase `world_pulse_runtime_state`, so it survives Render restarts. No fictional filler is generated when no suitable news exists. OS locks prevent overlapping refresh jobs on the same instance.
- `RSS_TIMEOUT_SECONDS=6`, `RSS_BATCH_TIMEOUT_SECONDS=35`: per-feed timeout and maximum wait for an RSS discovery scan. Discovery rotates through groups of four eligible publisher domains, querying two groups per category and native language every 15 minutes; results are added to a small Supabase-backed pending queue. The regular five-minute publisher handles a single queued story rather than issuing a full RSS fan-out on every tick. If some feeds hang, the app proceeds with completed feed results.
- `IMAGE_ENRICHMENT_BATCH_TIMEOUT_SECONDS=65`: overall maximum time for each batch of concurrent external photo searches. Each story searches Openverse, Wikimedia Commons, and the Library of Congress concurrently. Culture stories additionally search the Art Institute of Chicago and The Met public-domain catalogues; these do not run for unrelated sections. NASA and approved press-kit sources remain topic- or approval-gated. Eligible results are ranked using item-level title/description/keyword relevance, and query variants include headline and publisher-excerpt terms. `IMAGE_DOWNLOAD_TIMEOUT_SECONDS=10` separately bounds caching validated licensed images in Supabase. News are saved first; one bounded image pass then handles the new story and, when selected, one repaired archive story. The code does not launch a second provider-search pass in the same publishing tick.
- `MAX_IMAGE_LOOKUPS_PER_REFRESH=2` (also configured in `render.yaml`), `IMAGE_RETRY_AFTER_HOURS=1`, and `IMAGE_CACHE_MAX_AGE_HOURS=6` (code default unless a Render environment override is set): per-tick photo lookup budget, retry interval for missing/legacy placeholder rows, and metadata freshness window for existing external matches. Each publishing tick prioritises the new queued story and attempts one relevant, rights-checked photo; older-image backfill runs in bounded batches when the publication queue is idle, while the same publishing tick's image pass can also refresh the image for the article being repaired. Image search does not run on ordinary page views. The freshness window never deletes stored article or image records. The provider-group deadline now allows bounded time for response decoding and relevance scoring beyond the HTTP timeout; it is capped at 15 seconds.
- `CONTENT_LICENSE_APPROVED_DOMAINS`: only after source-specific rights review, with permission evidence retained.
- `ADMIN_PANEL_PASSWORD`: enables the protected admin workspace, including `/admin/articles`, `/admin/monitor`, and `/admin/sources`; use a strong password. The protected monitoring page reports safe database state, Gemini cooldown and image search/storage probes without exposing secrets.
- `MAX_IMAGE_UPLOAD_BYTES=52428800`: per-image admin upload limit in bytes (50 MiB by default, configurable up to 100 MiB). This removes the old 2 MiB rejection threshold. Only the protected admin image-upload route gets the larger request allowance; public endpoints retain the small default body limit.
- `MAX_SOURCE_IMAGE_BYTES=20971520`: maximum original licensed image download considered for durable caching (20 MiB by default, configurable up to 50 MiB). Accepted images are validated and resized/re-encoded for web delivery; image caching no longer rejects an image solely because the optimized copy is larger than 2 MiB. Image pixel dimensions and image formats remain validated for safety.
- `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: optional contact delivery.


### Supabase URL compatibility
The application normalizes the configured shared Supabase pooler URL before passing it to `psycopg2`: it uses the Transaction Pooler port `6543` for shared pooler hosts, removes the Prisma-only `pgbouncer` URI flag, and trims accidental whitespace around the database name. This does not repair an invalid password or project-specific pooler username; those must match the connection details in Supabase Dashboard → Connect. Never publish the connection URL or password.


## Image sourcing
Images are selected by searching headline keywords plus source-excerpt context. Wikimedia Commons, Openverse and the Library of Congress use item-level licence checks. Culture stories can additionally use the Art Institute of Chicago and The Met when an individual record explicitly marks the object public domain. NASA is used only for relevant science/space/Earth stories; press-kit assets require item-specific pre-approval. A found photo is validated, resized to web-friendly dimensions, optimized and cached in Supabase so article cards do not depend on third-party hotlink availability. Original licensed files can be larger than 2 MiB; storage no longer rejects the optimized copy simply because it crosses that old threshold. The original source, creator and licence link are retained. When no suitable photo is found, the UI uses a lightweight language-specific SVG brand fallback; these placeholders are not represented as documentary photographs.

## Article reading experience
Article pages include a prominent original-source link, strict native-source-language routing, clear labeling for AI-generated illustrative images, a compact source/timestamp/language metadata panel, and a sticky related-stories column on wide screens. Source attribution and licence links remain visible when provided.

## Routes
- `/`: latest news, language choice and category filters
- `/search?q=...`: search indexed stories
- `/article/<slug>`: bilingual brief, image attribution and original source link
- `/page/privacy`, `/page/terms`, `/page/about`, `/contact`
- `/api/news-status`, `/api/refresh`, `/healthz`
- `/robots.txt`, `/sitemap.xml`, `/news-sitemap.xml`
- `/media/catalogued/<image_id>` (persistent, optimized source images from Wikimedia/Openverse/LOC/Art Institute of Chicago/The Met/NASA/approved press kits)
- `/media/generated/<image_id>`
- `/admin/monitor` (admin login required; safe database, Gemini and image diagnostic dashboard)
- `/admin/sources` (admin login required)

## Run locally and test
```bash
npm install --no-audit --no-fund
npm run build:css
pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
```

The automated test suite covers language/source enforcement, Openverse licence filtering (CC0/PDM/CC BY/CC BY-SA), attribution metadata, inactive stock-provider exclusion, title/context query variants, image relevance scoring, image fallback rendering, and NASA/Commons rights policy. Live credentials, the production database, external API quotas and the actual rights status of individual images cannot be certified by unit tests alone; monitor `/api/news-status`, `/admin/monitor` and Render logs.

### Scheduled refresh and connection guardrails

The web service has a per-worker PostgreSQL connection concurrency cap (`DB_MAX_CONCURRENT_CONNECTIONS`, default 3; maximum 6) and a bounded wait (`DB_CONNECTION_WAIT_SECONDS`, default 2). With two Gunicorn workers and the default cap, application code opens at most six DB connections concurrently in that web-service instance. Every checked-out connection is closed in a `finally` block and releases its slot. This is a concurrency guard, not a substitute for using the Supabase Transaction Pooler URL on the configured pooler port.

The public `/api/news-status` endpoint reports cached database health instead of issuing a separate `SELECT 1` connection on every poll. The protected admin monitor keeps an active database probe for diagnostics. The shared template polls status every two minutes only while the tab is visible and never reloads a page just because a background refresh completed; the manual refresh button still reloads when the visitor explicitly requests a refresh.

The GitHub Actions workflow `.github/workflows/world-pulse-automation.yml` runs regression tests after relevant code changes and wakes the live homepage twice an hour (at minutes 7 and 37 UTC). The request initializes the guarded in-process scheduler, and the workflow reads `/api/news-status` to report a safe runtime snapshot. This is a no-extra-service-cost wake-up path, not a direct authenticated refresh command; keep `NEWS_SCHEDULER_ENABLED=true` for it to work. Scheduled GitHub Actions can be delayed, so this complements rather than replaces the application scheduler.

For a direct authenticated refresh trigger independent of homepage visits, `trigger_news_refresh.py` can alternatively be run by a Render Cron Job every 30 minutes with:

- Command: `python trigger_news_refresh.py`
- Schedule: `*/30 * * * *` (Render schedules are in UTC).
- `NEWS_REFRESH_TARGET_URL=https://nabd-news.onrender.com`
- `NEWS_REFRESH_WEBHOOK_TOKEN`: the same random value (at least 32 characters) set on the web service and the Cron Job.

The trigger uses HTTPS and sends the token only in an Authorization header. The web app's `POST /api/internal/refresh` endpoint is disabled until a valid token is configured and returns a non-disclosing response for incorrect tokens. The Cron Job does not need the Supabase URL or Gemini API key.

Once the Cron Job is created and verified, set `NEWS_SCHEDULER_ENABLED=false` on the web service so the in-process scheduler does not compete with the external schedule. Keep it enabled when no external scheduler is configured. Creating a Render Cron Job may incur a separate recurring charge; the code path alone does not create or enable that paid service.


### Fast article navigation

The sorted and deduplicated display pool is cached for up to 60 seconds per interface. Article navigation uses that warm cache when available; on a cold cache, it looks up the clicked story directly by its indexed slug before building a related-stories list. A bounded archive repair pass corrects missing source-domain metadata and resolves old Google News redirect URLs without changing article slugs or deleting rows. The homepage feed uses separate indexed Arabic and English slices, each bounded to the newest 120 eligible stories, then combines those slices in memory instead of ranking the entire permanent archive on each cache miss. The process-memory article working set is capped at 180 recent rows; Supabase remains the permanent archive. These are performance caches only; they do not delete persisted article records.

### Persistent storage versus temporary cache
Article records and image URLs, source attribution, provider links, licence metadata, and image-check timestamps are stored in the Supabase PostgreSQL table `world_pulse_articles`. The short-lived in-process article cache is only a performance optimization and is invalidated after database writes. The image freshness window controls when the app repeats external image searches; it does not expire or delete the database records. The protected admin image-refresh action bypasses that freshness window for up to 24 existing articles, prioritizes missing/legacy placeholder images, clears the current worker's short-lived display cache, and writes successful replacements and their cached image bytes back to Supabase while preserving any safe, reusable prior image if no better match is found.


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

The read-only archive audit checks source URL/domain consistency, language and category assignment, body/summary duplication, missing and stale images, item-level image licences, cached image blobs, and legacy placeholders; it reruns every 30 minutes to track repair progress. Image and source-link repairs run in bounded batches; old-image revalidation is scheduled during the less frequent discovery cycle rather than competing with every page request. The production workflow verifies the exact deployed commit, the health endpoint, both language homepages, database connectivity, sampled article/image routes, and a light four-worker HTTP load test that records p50/p95 latency and response sizes.
