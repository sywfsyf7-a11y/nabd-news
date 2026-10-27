"""Contract tests for the additive public mobile API and digest logic."""
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import app as world_pulse
import public_api_v1


def raw_story(slug, *, category="technology", published_at=None, headline_only=False):
    if published_at is None:
        published_at = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)
    return {
        "slug": slug,
        "source_url": f"https://example.test/{slug}",
        "source_name": "Example Publisher",
        "source_domain": "example.test",
        "category": category,
        "original_language": "en",
        "title_en": f"Headline {slug}",
        "summary_en": f"Summary of {slug}.",
        "content_en": f"Substantive editorial details for {slug} are available.",
        "title_ar": "",
        "summary_ar": "",
        "content_ar": "",
        "published_at": published_at,
        "fetched_at": published_at,
        "read_minutes": 2,
        "is_demo": False,
        "is_hidden": False,
        "_headline_only_for_test": headline_only,
    }


def fake_normalise(row, lang):
    native_lang = row.get("original_language", "en")
    headline_only = bool(row.get("_headline_only_for_test") or row.get("headline_only"))
    display_lang = native_lang
    return {
        **row,
        "title": row.get(f"title_{display_lang}") or row.get(f"title_{lang}") or "",
        "summary": row.get(f"summary_{display_lang}") or row.get(f"summary_{lang}") or "",
        "display_language": display_lang,
        "headline_only": headline_only,
        "source_only": headline_only,
        "image_url": "",
        "image_source": "none",
        "image_relevance_verified": False,
        "image_provider_url": "",
        "image_credit_url": "",
        "image_license_url": "",
        "image_credit": "",
    }


class PublicMobileApiV1Tests(unittest.TestCase):
    def setUp(self):
        with public_api_v1._API_CACHE_LOCK:
            public_api_v1._API_CACHE.clear()
        with public_api_v1._API_RATE_LOCK:
            public_api_v1._API_RATE_BUCKETS.clear()
        self.client = world_pulse.app.test_client()

    def test_categories_returns_eight_bilingual_categories_as_an_array(self):
        response = self.client.get("/api/v1/categories")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.content_type)
        data = response.get_json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 8)
        self.assertEqual(
            {entry["slug"] for entry in data},
            {"politics", "economy", "technology", "gaming", "sports", "science", "culture", "world"},
        )
        self.assertIn("label_ar", data[0])
        self.assertIn("label_en", data[0])

    def test_articles_requires_language_and_rejects_invalid_pagination_as_json(self):
        missing_lang = self.client.get("/api/v1/articles")
        self.assertEqual(missing_lang.status_code, 400)
        self.assertEqual(missing_lang.get_json()["error"]["code"], "invalid_parameter")

        bad_page_size = self.client.get("/api/v1/articles?lang=en&per_page=51")
        self.assertEqual(bad_page_size.status_code, 400)
        self.assertEqual(bad_page_size.get_json()["error"]["code"], "invalid_parameter")

        invalid_category = self.client.get("/api/v1/articles?lang=en&category=made-up")
        self.assertEqual(invalid_category.status_code, 400)
        self.assertEqual(invalid_category.get_json()["error"]["code"], "invalid_parameter")

    def test_articles_are_newest_first_paginated_and_never_return_full_body(self):
        now = datetime.now(timezone.utc)
        older = raw_story("older", published_at=now - timedelta(hours=2))
        newer = raw_story("newer", published_at=now - timedelta(hours=1))
        rows = [older, newer]
        with patch.object(world_pulse, "_db_fetch_all", return_value=rows):
            with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
                with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                    response = self.client.get("/api/v1/articles?lang=en&page=1&per_page=1")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["items"][0]["slug"], "newer")
        self.assertTrue(data["has_more"])
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["per_page"], 1)
        item = data["items"][0]
        self.assertNotIn("content", item)
        self.assertNotIn("content_en", item)
        self.assertEqual(item["source_url"], newer["source_url"])
        self.assertIsNone(item["image"])

    def test_headline_only_article_has_no_summary_or_image_and_is_not_mislabelled_ai(self):
        row = raw_story("wire", category="world")
        row["source_domain"] = "bbc.com"
        row["_headline_only_for_test"] = True
        with patch.object(world_pulse, "_db_fetch_all", return_value=[row]):
            with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
                with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                    response = self.client.get("/api/v1/articles?lang=en")
        self.assertEqual(response.status_code, 200)
        item = response.get_json()["items"][0]
        self.assertTrue(item["headline_only"])
        self.assertIsNone(item["summary"])
        self.assertFalse(item["ai_generated"])
        self.assertIsNone(item["image"])

    def test_article_detail_uses_existing_persistent_slug_lookup(self):
        row = raw_story("detail")
        with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=row) as lookup:
            with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
                with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                    response = self.client.get("/api/v1/articles/detail?lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slug"], "detail")
        lookup.assert_called_once_with("detail")

    def test_missing_article_returns_json_404(self):
        with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=None):
            response = self.client.get("/api/v1/articles/missing?lang=en")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "not_found")

    def test_search_requires_two_characters_and_returns_list_shape(self):
        short = self.client.get("/api/v1/search?q=x&lang=en")
        self.assertEqual(short.status_code, 400)
        self.assertEqual(short.get_json()["error"]["code"], "invalid_parameter")

        row = raw_story("search-hit")
        with patch.object(world_pulse, "_db_search_articles", return_value=[row]):
            with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
                with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                    response = self.client.get("/api/v1/search?q=technology&lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.get_json())
        self.assertIn("has_more", response.get_json())

    def test_device_token_and_settings_are_validated_before_database_access(self):
        with patch.object(world_pulse, "_ensure_schema") as ensure:
            bad_token = self.client.post("/api/v1/devices", json={
                "token": "not-an-expo-token", "platform": "android", "lang": "en"
            })
        self.assertEqual(bad_token.status_code, 400)
        self.assertEqual(bad_token.get_json()["error"]["code"], "invalid_token")
        ensure.assert_not_called()

        bad_zone = self.client.post("/api/v1/devices", json={
            "token": "ExponentPushToken[abcdefghijklmnop]",
            "platform": "android", "lang": "en", "timezone": "Not/AZone",
        })
        self.assertEqual(bad_zone.status_code, 400)
        self.assertEqual(bad_zone.get_json()["error"]["code"], "invalid_parameter")

        bad_hour = self.client.post("/api/v1/devices", json={
            "token": "ExponentPushToken[abcdefghijklmnop]",
            "platform": "android", "lang": "en", "digest_hour_local": 24,
        })
        self.assertEqual(bad_hour.status_code, 400)

    def test_digest_selection_skips_headline_only_and_caps_two_per_category(self):
        now = datetime.now(timezone.utc)
        rows = [
            raw_story("g1", category="gaming", published_at=now - timedelta(minutes=1)),
            raw_story("g2", category="gaming", published_at=now - timedelta(minutes=2)),
            raw_story("g3", category="gaming", published_at=now - timedelta(minutes=3)),
            raw_story("s1", category="sports", published_at=now - timedelta(minutes=4)),
            raw_story("s2", category="sports", published_at=now - timedelta(minutes=5)),
            raw_story("s3", category="sports", published_at=now - timedelta(minutes=6)),
            raw_story("headline", category="world", published_at=now - timedelta(minutes=7), headline_only=True),
            raw_story("old", category="world", published_at=now - timedelta(hours=30)),
        ]
        with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
            with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                items = public_api_v1._digest_items_from_rows(rows, "en", ["gaming"], now_utc=now)
        self.assertGreaterEqual(len(items), 3)
        self.assertLessEqual(len(items), 5)
        self.assertEqual(items[0]["category_slug"], "gaming")
        self.assertNotIn("headline", {item["slug"] for item in items})
        counts = {}
        for item in items:
            counts[item["category_slug"]] = counts.get(item["category_slug"], 0) + 1
        self.assertTrue(all(count <= 2 for count in counts.values()))

    def test_digest_endpoint_validates_language_and_category_slugs(self):
        no_lang = self.client.get("/api/v1/digest")
        self.assertEqual(no_lang.status_code, 400)
        bad_category = self.client.get("/api/v1/digest?lang=en&categories=technology,other")
        self.assertEqual(bad_category.status_code, 400)

    def test_internal_sender_requires_secret_before_any_database_read(self):
        with patch.dict(os.environ, {"DIGEST_TOKEN": "test-only-secret"}):
            with patch.object(world_pulse, "_db_fetch_all") as read_archive:
                response = self.client.post("/internal/send-digest")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "unauthorized")
        read_archive.assert_not_called()

    def test_get_responses_are_server_cached_and_rate_limit_is_counted_on_cache_hits(self):
        first = self.client.get("/api/v1/categories")
        second = self.client.get("/api/v1/categories")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get("Cache-Control"), "public, max-age=60")

        # Rate limiting wraps the cache, so a warmed response still counts towards the IP limit.
        with public_api_v1._API_RATE_LOCK:
            public_api_v1._API_RATE_BUCKETS.clear()
        for _ in range(120):
            response = self.client.get("/api/v1/categories")
            self.assertEqual(response.status_code, 200)
        blocked = self.client.get("/api/v1/categories")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.get_json()["error"]["code"], "rate_limit_exceeded")



    def test_device_registration_upserts_settings_without_echoing_token(self):
        token = "ExponentPushToken[abcdefghijklmnop]"
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=conn):
                with patch.object(world_pulse, "_release_db_connection"):
                    response = self.client.post("/api/v1/devices", json={
                        "token": token,
                        "platform": "ios",
                        "lang": "en",
                        "timezone": "Asia/Amman",
                        "digest_enabled": True,
                        "digest_hour_local": 8,
                        "categories": [],
                    })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["registered"])
        self.assertEqual(payload["categories"], [])
        self.assertNotIn("token", payload)
        self.assertIn("ON CONFLICT (token) DO UPDATE", cursor.execute.call_args.args[0])

    def test_digest_sender_sends_once_and_removes_unregistered_expo_tokens(self):
        from zoneinfo import ZoneInfo

        now_utc = datetime.now(timezone.utc)
        local_hour = now_utc.astimezone(ZoneInfo("Asia/Amman")).hour
        valid_token = "ExponentPushToken[abcdefghijklmnop]"
        stale_token = "ExpoPushToken[qrstuvwxyzabcdef]"
        state = {
            "devices": [
                {
                    "token": valid_token, "lang": "en", "timezone": "Asia/Amman",
                    "digest_hour_local": local_hour, "categories": [], "last_digest_sent_date": None,
                },
                {
                    "token": stale_token, "lang": "en", "timezone": "Asia/Amman",
                    "digest_hour_local": local_hour, "categories": [], "last_digest_sent_date": None,
                },
            ],
            "updates": [],
            "deletions": [],
        }

        class FakeCursor:
            def __init__(self):
                self.row = None
                self.rows = []
                self.rowcount = 0
                self.sql = ""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params=None):
                self.sql = sql
                self.row = None
                self.rows = []
                self.rowcount = 0
                if "pg_try_advisory_lock" in sql:
                    self.row = (True,)
                elif "SELECT token, lang, timezone, digest_hour_local" in sql:
                    self.rows = [dict(device) for device in state["devices"]]
                elif "UPDATE public.devices" in sql:
                    local_date, token, _same_date = params
                    for device in state["devices"]:
                        if device["token"] == token and device["last_digest_sent_date"] != local_date:
                            device["last_digest_sent_date"] = local_date
                            self.rowcount = 1
                            state["updates"].append((token, local_date))
                            break
                elif "DELETE FROM public.devices" in sql:
                    token = params[0]
                    before = len(state["devices"])
                    state["devices"] = [device for device in state["devices"] if device["token"] != token]
                    self.rowcount = before - len(state["devices"])
                    if self.rowcount:
                        state["deletions"].append(token)
                elif "pg_advisory_unlock" in sql:
                    self.row = (True,)

            def fetchone(self):
                return self.row

            def fetchall(self):
                return self.rows

        class FakeConnection:
            def __init__(self):
                self.commit_count = 0
                self.rollback_count = 0

            def cursor(self):
                return FakeCursor()

            def commit(self):
                self.commit_count += 1

            def rollback(self):
                self.rollback_count += 1

        rows = [
            raw_story("digest-tech", category="technology", published_at=now_utc - timedelta(minutes=3)),
            raw_story("digest-game", category="gaming", published_at=now_utc - timedelta(minutes=2)),
            raw_story("digest-world", category="world", published_at=now_utc - timedelta(minutes=1)),
        ]
        conn = FakeConnection()
        ticket_batches = [
            [
                {"status": "ok", "id": "ticket-ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            ]
        ]
        with patch.dict(os.environ, {"DIGEST_TOKEN": "server-only-test-secret"}):
            with patch.object(world_pulse, "_db_fetch_all", return_value=rows):
                with patch.object(world_pulse, "_connect_db", return_value=conn):
                    with patch.object(world_pulse, "_release_db_connection"):
                        with patch.object(world_pulse, "_story_allowed_in_display_language", return_value=True):
                            with patch.object(world_pulse, "_normalise_story", side_effect=fake_normalise):
                                with patch.object(public_api_v1, "_expo_send_batch", side_effect=ticket_batches) as send:
                                    first = self.client.post(
                                        "/internal/send-digest",
                                        headers={"X-Digest-Token": "server-only-test-secret"},
                                    )
                                    second = self.client.post(
                                        "/internal/send-digest",
                                        headers={"X-Digest-Token": "server-only-test-secret"},
                                    )

        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(first.get_json()["sent"], 1)
        self.assertEqual(first.get_json()["removed"], 1)
        self.assertEqual(state["deletions"], [stale_token])
        self.assertEqual(len(state["updates"]), 1)
        self.assertEqual(state["updates"][0][0], valid_token)
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        self.assertEqual(second.get_json()["sent"], 0)
        send.assert_called_once()

if __name__ == "__main__":
    unittest.main()
