# Nabd News Public Mobile API v1

The API is additive: the existing website pages, routes, newsroom pipeline, and publishing cadence are not changed by these endpoints. Public endpoints return UTF-8 JSON. Date-times use ISO 8601 UTC with a trailing `Z`.

Base URL: `https://nabd-news.onrender.com`

## General behavior

- Public GET responses are cached by the server for 60 seconds.
- Public GET endpoints are limited to 120 requests per minute per IP; device POST/DELETE endpoints are limited to 20 per minute. The internal sender is limited to 5 per minute. Limits are lightweight per-process memory windows and reset on a restart.
- `per_page` defaults to 20 and accepts integers from 1 to 50. `page` defaults to 1 and must be a positive integer.
- `lang` must be `ar` or `en`. For list/search routes it is required. For an individual article it is optional; when omitted, the story's source language is used. The `lang` in an Article is the actual language of the title and summary returned, which may differ from the requested preference when a permitted translation is unavailable.
- Unknown categories and invalid parameters return HTTP 400 with `{"error":{"code":"invalid_parameter","message":"..."}}`. Missing articles return HTTP 404 as JSON. Rate limit responses use HTTP 429.
- Results use the same source allowlist, language integrity, hidden/demo-story, publisher rights, and headline-only policies as the website. No endpoint returns full publisher article text. The API returns the on-site headline and our short summary only.
- `headline_only: true` means a publisher is available only as a headline and source link under the current policy (for example, certain BBC and Al Jazeera entries). Such records have `summary: null`, `ai_generated: false`, and no image. Mobile clients should open `source_url` directly.
- `image` is returned only when the stored image has validated licence data, source-page provenance, and relevance metadata. It is `null` for local illustrations, unverified photos, or incomplete provenance. This avoids treating an illustrative graphic as a documentary photo or returning an image without reuse evidence.

## Article response shape

All article endpoints return this object inside the list `items` array or directly for article detail:

```json
{
  "slug": "story-0123456789abcdef01",
  "title": "A concise editorial headline",
  "summary": "A short summary prepared for Nabd News from permitted source material.",
  "category_slug": "technology",
  "category_label": "Technology",
  "lang": "en",
  "source_name": "Example Publisher",
  "source_url": "https://publisher.example/news/story",
  "published_at": "2026-10-27T06:00:00Z",
  "read_minutes": 2,
  "headline_only": false,
  "ai_generated": true,
  "image": {
    "url": "https://images.example.org/photo.jpg",
    "credit": "Photographer Name",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_page_url": "https://images.example.org/items/photo"
  }
}
```

The example image is illustrative schema only; real responses use verified record data or `null`. For headline-only items, `summary` is `null`, `ai_generated` is false, and `image` is null. The API does not provide the article's long body.

## Endpoints

### 1. `GET /api/v1/categories`

Returns the eight configured categories as an array.

Example:

```json
[
  {"slug":"politics","label_ar":"سياسة","label_en":"Politics"},
  {"slug":"economy","label_ar":"اقتصاد","label_en":"Economy"},
  {"slug":"technology","label_ar":"تكنولوجيا","label_en":"Technology"},
  {"slug":"gaming","label_ar":"جيمنج","label_en":"Gaming"},
  {"slug":"sports","label_ar":"رياضة","label_en":"Sports"},
  {"slug":"science","label_ar":"علوم","label_en":"Science"},
  {"slug":"culture","label_ar":"ثقافة","label_en":"Culture"},
  {"slug":"world","label_ar":"أخبار العالم","label_en":"World"}
]
```

### 2. `GET /api/v1/articles?lang=ar|en&category=<slug>&page=1&per_page=20`

Returns newest first:

```json
{
  "items": [],
  "page": 1,
  "per_page": 20,
  "has_more": false
}
```

`category` is optional and must be one of the eight category slugs. The source-language policy is shared with the website, so the API can include Arabic and English source stories in one returned list; each item reports its actual `lang`.

### 3. `GET /api/v1/articles/<slug>?lang=ar|en`

Returns one Article object. The `lang` query is optional; when absent, the record's original language is selected. A missing or policy-ineligible story returns JSON 404.

### 4. `GET /api/v1/search?q=<text>&lang=ar|en&page=1&per_page=20`

Requires `q` between 2 and 160 characters and a valid `lang`. Uses the website's existing database search helper and the same published-story policy. The response shape is the same as the articles-list response. The search helper returns up to its existing 100-result search window; paging applies within that window.

### 5. `POST /api/v1/devices`

Registers a device or updates its settings using token upsert. Send a JSON object:

```json
{
  "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "platform": "android",
  "lang": "ar",
  "timezone": "Asia/Amman",
  "digest_enabled": true,
  "digest_hour_local": 8,
  "categories": ["technology", "gaming", "world"]
}
```

- `token` must start with `ExponentPushToken[` or `ExpoPushToken[` and end with `]`.
- `platform` is `ios` or `android`; `lang` is `ar` or `en`.
- `timezone` must be a valid IANA time-zone name.
- `digest_enabled` is boolean; `digest_hour_local` is an integer 0–23 and defaults to 8.
- `categories` is an array of known category slugs. An empty array means all categories.

Success response omits the token:

```json
{
  "registered": true,
  "platform": "android",
  "lang": "ar",
  "timezone": "Asia/Amman",
  "digest_enabled": true,
  "digest_hour_local": 8,
  "categories": ["technology", "gaming", "world"]
}
```

Before using device registration, apply `migrations/20261027_create_devices.sql` in the Supabase SQL Editor. Until the table exists, the endpoint returns HTTP 503 with `devices_migration_required`.

### 6. `DELETE /api/v1/devices`

Unregisters a device. JSON body:

```json
{"token":"ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"}
```

Response:

```json
{"deleted":true}
```

The response is `deleted: false` if that token was not registered. The token is never echoed in the response.

### 7. `GET /api/v1/digest?lang=ar|en&categories=technology,gaming`

Returns up to five stories published or fetched within the last 24 hours, skipping headline-only entries and preferring requested categories. No category preference means all categories. A maximum of two stories per category is used to diversify the digest.

```json
{
  "items": [],
  "count": 0,
  "generated_at": "2026-10-27T08:00:00Z"
}
```

This read-only endpoint is also useful for testing digest selection. It uses the same 60-second cache as the other GET routes.

### 8. `POST /internal/send-digest`

Internal server-only endpoint. Requires the `X-Digest-Token` header to match the server environment variable `DIGEST_TOKEN`. Never put this secret in a mobile app or a public repository.

The caller should trigger this endpoint approximately once an hour. It selects enabled devices whose configured local hour is current and whose digest has not been accepted for their local date. A device receives no push when fewer than three eligible stories exist. Messages are sent to the Expo Push API in batches of up to 100. The title is `نبض الصباح` for Arabic and `Morning Digest` for English. The body contains the first headline and the count of additional stories; the push data contains `{"type":"digest","slug":"..."}`.

Successful Expo tickets update `last_digest_sent_date`; `DeviceNotRegistered` tickets delete the corresponding device. A PostgreSQL advisory lock plus a local lock prevents simultaneous sender runs and a second successful run in the same hour skips already-sent devices. A process crash after Expo accepts a push but before the database update can still leave a narrow duplicate-send window; Expo push delivery is not an exactly-once transaction.

Typical response:

```json
{
  "status": "complete",
  "eligible": 4,
  "attempted": 4,
  "sent": 4,
  "removed": 0,
  "skipped": 12,
  "failed": 0
}
```

## Migration and environment setup

1. Run `migrations/20261027_create_devices.sql` in Supabase.
2. Add `DIGEST_TOKEN` in Render environment variables as a long random secret. It is server-only. No Expo access token is required for the standard Expo Push API.
3. Configure the existing scheduled GitHub Action or another trusted scheduler to call `POST /internal/send-digest` hourly, sending `X-Digest-Token` from a GitHub Actions secret. Do not hard-code the token in the workflow file.
4. Deploy the new code and test the public GET endpoints. Device registration and digest delivery require the migration and secret configuration.

## Three curl examples

Set the site base URL first:

```sh
BASE_URL="https://nabd-news.onrender.com"
```

**1. Read the newest Arabic technology stories:**

```sh
curl -sS "$BASE_URL/api/v1/articles?lang=ar&category=technology&page=1&per_page=20"
```

**2. Register or update a device** (replace the example Expo token with one returned by the mobile app):

```sh
curl -sS -X POST "$BASE_URL/api/v1/devices" \
  -H "Content-Type: application/json" \
  -d '{"token":"ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]","platform":"android","lang":"ar","timezone":"Asia/Amman","digest_enabled":true,"digest_hour_local":8,"categories":["technology","gaming"]}'
```

**3. Trigger the internal digest sender** (use the exact same secret stored in Render as `DIGEST_TOKEN`):

```sh
curl -sS -X POST "$BASE_URL/internal/send-digest" \
  -H "X-Digest-Token: $DIGEST_TOKEN"
```

For search, category lookup, article detail, and digest selection, call the URLs described above with their documented query parameters. The JSON error format is stable: `{"error":{"code":"...","message":"..."}}`.
