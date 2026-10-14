# World Pulse / نبض العالم

## Deploy on Render
1. Push this folder's files to a Git repository. Keep `app.py` at the repository root and `index.html` inside `templates/`.
2. Create a PostgreSQL database in Supabase and copy its Session Pooler connection string into Render as `SUPABASE_POOLER_URL` (or use `DATABASE_URL`). Keep SSL required.
3. Keep `FLASK_SECRET_KEY` set to a long random secret.
4. **Recommended for full publishing:** set `GEMINI_API_KEY` and either `SUPABASE_POOLER_URL` or `DATABASE_URL` in Render Environment. If Gemini is unavailable, the site can still display real, attributed RSS headlines with a short teaser and a clear note that AI editorial enrichment is unavailable; it does not invent sample news. If PostgreSQL is unavailable, results are only cached in the current worker and are not reliably persistent, so restore the database URL as soon as possible.
5. Never commit API keys to Git or put them in HTML.
6. For the contact form, configure `SMTP_HOST`, `SMTP_PORT` (usually 587), `SMTP_USERNAME`, `SMTP_PASSWORD`, and optionally `SMTP_FROM`.
7. Set `SITE_URL` to your public HTTPS origin for the sitemap.
8. Optional: create a Render Cron Job with command `python app.py --refresh-news` to refresh feeds independently of web traffic.

## News sourcing and copyright safeguards
- The collector runs two Google News RSS discovery passes per category and language: a broad query and a query focused on the source domains listed in `CATEGORY_SOURCE_DOMAINS`.
- The application does **not** poll the named publishers' own RSS endpoints and does **not** fetch or scrape their full article pages. It uses the headline, source attribution, original link and a short discovery excerpt (maximum 500 characters) as input for editorial drafting.
- Gemini is prompted to write original, attributed briefs, not to copy source sentences or pretend that a short excerpt supports an investigation. If Gemini fails or returns an incomplete draft, the system can show only the real headline and a short RSS teaser with an explicit preliminary-brief note; it does not present that item as AI-enriched reporting.
- Publisher terms vary. A source's appearance in `CATEGORY_SOURCE_DOMAINS` is a discovery preference, **not** permission to republish its content. The current conservative gate skips items whose source is identifiable as BBC, Reuters, AP News, TechCrunch, ESPN, ScienceDaily, The Guardian or Al Jazeera, pending suitable permission/licensing. Before adding direct syndication or changing this gate, check the exact current publisher terms and obtain written permission where required. Keep the source name and a prominent link to the original story.
- Do not re-publish full feed summaries verbatim or add publisher text/images without an applicable licence. The code avoids reusing images from publisher RSS or `og:image` metadata because these do not themselves establish reuse rights.
- Images are never accepted from publisher RSS thumbnails or `og:image` metadata alone. The current provider order and attribution requirements are documented below under **Image sourcing and rights safeguards**.
- A technical safeguard lowers copyright risk but cannot guarantee legal compliance in every jurisdiction or with every publisher's contractual terms. Review the terms of the exact sources you use and seek licensing/legal advice before monetizing content at scale.

## Publisher source catalog
The automatic source-domain filters are configured in `CATEGORY_SOURCE_DOMAINS` in `app.py`; each category has Arabic and English source domains. This is a source-discovery map, not a redistribution licence. Some named publishers remain visible in the code for reference but are excluded automatically by the rights gate above until appropriate permission is established.

## Editorial quality and backfill
- Demo/sample story cards are disabled and the static sample story data is not used by live routes. Empty feeds produce an empty state and diagnostic status endpoint, not fake news.
- The refresh process asks Gemini for Arabic and English original reporting briefs with a useful executive summary, factual details from available source material, restrained context, and explicit unknowns where relevant.
- The editorial model does not claim to read publisher article pages or independently verify stories. Headlines and brief RSS excerpts may not contain enough evidence for a long report; in those cases, content should remain short rather than inventing detail.
- Previously stored real articles are not hidden only because their body is short. A short or unenriched item is clearly labelled as a preliminary RSS brief, while the source link remains available. A small number of thin stored articles are reprocessed each refresh when Gemini is available.
- AI assistance does not replace human fact-checking. Review important claims, attribution, categories and context before relying on the content.

## Important
- No code can guarantee Google AdSense approval. Approval depends on the published site's actual usefulness, originality, user experience, policy compliance, traffic quality and Google's review.
- If a publisher's terms do not allow the intended commercial use, remove it from the automatic source search or obtain a suitable licence; merely linking or giving credit is not a substitute for permission when permission is required.
- Rotate any API key that has been shared in chat or placed in source code. Use environment variables only.

## Admin dashboard: sources and image licensing review

Set `ADMIN_PANEL_PASSWORD` to a long, unique password in Render Environment. The panel is available at `/admin/sources` and the login page at `/admin/login`; if the environment variable is missing, these routes return 404. The panel stores source/provider enablement in the Supabase `world_pulse_controls` table, so toggles survive redeploys. It can disable configured news domains, disable image providers, remove existing images from a disabled provider, and remove an individual article image after review. The admin session uses HTTP-only, SameSite cookies and CSRF tokens for changes.

The source panel does not grant copyright permissions. Sources flagged by the conservative publisher licence gate remain excluded from automated article processing until permission is obtained, even if a domain appears in the catalogue. Keep `ADMIN_PANEL_PASSWORD` secret and rotate it if exposed.

## Required and optional environment variables
Required:
- `GEMINI_API_KEY` — enables Gemini editorial drafting; if missing, article refresh fails visibly instead of publishing examples.
- `SUPABASE_POOLER_URL` or `DATABASE_URL` — PostgreSQL persistence. If neither is configured or the database cannot be reached, new stories are not published as transient worker memory.
- `FLASK_SECRET_KEY` — persistent Flask session signing key.
- `ADMIN_PANEL_PASSWORD` — required to enable the protected source/licence dashboard.

Optional:
- `GEMINI_MODEL` — Gemini model name.
- `NEWS_REFRESH_MINUTES` — refresh interval, default 15 minutes.
- `NEWS_AUTO_FETCH` — disable automatic fetch with `false` if using a separate cron job.
- `MAX_ARTICLES_PER_REFRESH` — target number of stories per refresh, capped by application settings.
- `MAX_ARTICLES_PER_CATEGORY` — per-category collection limit.
- `MAX_IMAGE_LOOKUPS_PER_REFRESH` — maximum article image lookup jobs per refresh across configured providers (default 8 to keep free-tier API traffic modest).

## Image sourcing and rights safeguards

Images are resolved in this order: **(1)** Wikimedia Commons, but only when machine-readable metadata identifies Public Domain, CC0 or a plain CC BY licence (not BY-SA, NC or ND); **(2)** the local `approved_presskit_images.json` allowlist; **(3)** Pexels API when `PEXELS_API_KEY` is configured; **(4)** Unsplash API when `UNSPLASH_ACCESS_KEY` is configured; **(5)** the site's CSS placeholder. If a provider does not return a relevant result or its metadata is incomplete, the article keeps the placeholder instead of grabbing a publisher thumbnail or a random Google Images result.

### Optional photo APIs

- `UNSPLASH_ACCESS_KEY` — an access key for the official Unsplash API. The implementation uses the image URL returned by the API unchanged and links the photographer and photo page with Unsplash referral parameters. Follow the current Unsplash API guidelines and apply for production access if required.
- `PEXELS_API_KEY` — an existing Pexels API key. The photo credit links the photographer and the photo page, and links to the Pexels licence. Pexels requires a prominent link back to Pexels for API usage and asks developers to credit photographers when possible.
- `IMAGE_CACHE_MAX_AGE_HOURS` — maximum age before a cached image result is resolved again; default 168 hours (7 days).
- `MAX_IMAGE_LOOKUPS_PER_REFRESH` and `IMAGE_SEARCH_TIMEOUT_SECONDS` — control the amount and timeout of image lookup work.

An API key does not mean every image may be used in every context. Avoid implying that an illustrative stock photo depicts the actual event, and use the caption `Illustrative image` for automatically found images. The searcher does not use a publisher's RSS thumbnail or `og:image` just because it is publicly visible.

### Official press kits (NASA, companies, public agencies)

The application does not scrape arbitrary pressrooms or automatically treat NASA/company imagery as public domain. Exact image-specific rights and third-party credits can differ. Instead, manually review and add only items where the specific source's current terms or written permission allow your intended commercial use to `approved_presskit_images.json`. Start from this structure:

```json
[
  {
    "approved_for_commercial_use": true,
    "category": "science",
    "keywords": ["artemis", "moon", "rocket"],
    "description": "Approved image related to the Artemis program",
    "image_url": "https://example.gov/path/to/image.jpg",
    "image_page_url": "https://example.gov/media/asset-page",
    "credit": "Agency / photographer as specified by the source",
    "credit_url": "https://example.gov/media/asset-page",
    "license_name": "Exact permission/licence reviewed by the site owner",
    "license_url": "https://example.gov/terms-or-permission-page"
  }
]
```

This is an example schema only: **do not copy these example URLs into production**. Add a real item only after checking the image-specific terms, attribution and any third-party restrictions. The manifest is a manual approval list, not a licence checker.

### Fallback and presentation

The former fixed Unsplash stock URLs have been removed from default/category placeholders. If no approved, relevant asset is found, the site shows its own CSS-generated `WP` placeholder (no external image asset). Captions show the contributor/provider and licence/terms link where available, and automatically found images are labelled as illustrative. This lowers risk but cannot guarantee that every image is free of claims; licences, personality/privacy rights, trademarks and news context may require case-by-case review.

### Official provider documentation

- Wikimedia Commons API and image licensing metadata: https://commons.wikimedia.org/wiki/Commons:API/MediaWiki and https://commons.wikimedia.org/wiki/Commons:Machine-readable_data
- Unsplash API guidelines and hotlinking: https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines and https://help.unsplash.com/en/articles/2511271-guideline-hotlinking-images
- Pexels API usage and attribution: https://www.pexels.com/api/documentation/
- NASA image/media usage guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/

NASA says much of its content is usable editorially, but also states that third-party copyrighted materials may appear on its site, NASA branding is restricted, and identifiable people can raise separate commercial-use issues. That is why NASA or other press-kit files are not automatically harvested: approve the exact asset in the local manifest only after reviewing the particular usage terms.
