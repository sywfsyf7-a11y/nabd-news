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
