# World Pulse update notes

## What changed
- Separated all eight news sections into explicit Arabic and English publisher-domain allowlists.
- Restricted Google News RSS queries to the configured domains for each section and language.
- Rejected stories whose publisher is not allowlisted or whose headline language does not match the requested feed language.
- Saved each original publisher domain in the articles table and added a safe schema migration for existing databases.
- Filtered Arabic and English pages/search results by the story’s original source language and allowlisted publisher.
- Made `static/A.jpg` the fallback for originally Arabic stories and `static/E.jpg` the fallback for originally English stories, independent of the currently selected interface language.
- Kept Google News RSS as a story-discovery mechanism only; Google News thumbnails and publisher thumbnails are not treated as reusable images.
- Retained the licensed image pipeline: filtered Wikimedia Commons, manually approved press-kit assets, and Pexels/Unsplash APIs when keys are configured.
- Added working source and image-provider toggles to `/admin/sources`, CSRF tokens for admin actions, and a remove-image action.
- Standardized the documented admin environment variable to `ADMIN_PANEL_PASSWORD`, while retaining `ADMIN_PASSWORD` as a compatibility alias.
- Documented sources and rights safeguards in `SOURCES.md` and `README.md`.

## Configuration reminders
- Set a strong `ADMIN_PANEL_PASSWORD` in the hosting environment to enable the admin panel.
- Set `SUPABASE_POOLER_URL` or `DATABASE_URL` for persisted source controls and articles. Without a working database, source toggles cannot be saved.
- Set `PEXELS_API_KEY` and/or `UNSPLASH_ACCESS_KEY` only if you intend to enable those APIs.
- Add a publisher to `CONTENT_LICENSE_APPROVED_DOMAINS` only after reviewing the particular terms/licence or receiving the necessary written permission. This is not a way to bypass rights restrictions.
- Keep `approved_presskit_images.json` limited to assets whose intended use has actually been verified. It is empty by default.

## Validation and limits
Python syntax compilation, Jinja template parsing, policy checks, and mocked RSS allowlist/language checks passed. Real Flask dependencies, Supabase/PostgreSQL connectivity, Gemini, provider API keys, and the live Render deployment were not available for end-to-end validation in this environment. The changes are packaged in this ZIP and have not been pushed to GitHub.


## Reliability and launch-readiness follow-up
- Improved Commons, Pexels and Unsplash query relevance, and recorded image-search outcomes without exposing credentials.
- Added bounded retry/backfill for existing articles with missing images; only reusable provider/licence metadata is saved, and A/E remain the fallback.
- Kept verified source-language headlines available if Gemini editorial enrichment is temporarily unavailable, and logged Gemini failure types.
- Added non-secret Gemini and image-provider diagnostics to `/api/news-status`.
- Implemented actual SMTP contact delivery and made contact-form status truthful when email delivery is not configured or fails.
- Replaced placeholder about/privacy/terms pages; added article JSON-LD, canonical/hreflang/social metadata, current-article sitemap URLs and a 48-hour news sitemap.
- Added CSRF protection and cooldowns for manual refresh/Q&A endpoints, baseline response security headers, and Render public-port binding.
- Added GitHub Actions syntax/policy tests.

Security note: any API key disclosed in chat should be revoked and replaced. Configure the replacement only in the hosting secret settings; never add it to source code or Git history.


## Gemini image generation
- Added a separate Gemini image model setting powered by the existing `GEMINI_API_KEY`, with category-aware, source-language-aware prompts for original vector/infographic news illustrations.
- Added daily/per-refresh image generation caps; default limits are three image attempts per refresh and eight per rolling 24 hours.
- Store optimized generated JPEGs and the prompt in PostgreSQL/Supabase so image URLs survive Render restarts and deployments.
- Serve generated images through `/media/generated/<image_id>`; generated-image URLs are converted to absolute URLs for Open Graph, Twitter and JSON-LD metadata.
- Try AI generation first for new or otherwise unillustrated eligible stories, then fall back to the existing Commons, approved press-kit, Pexels and Unsplash sources. If every provider fails, retain the Arabic/English local fallback graphics.
- Add a Gemini provider toggle in the source/image admin panel and safe generation status/configuration details to `/api/news-status`.
- AI image output is credited as generated illustration, not represented as a stock-photo licence or a guarantee of copyright clearance.
