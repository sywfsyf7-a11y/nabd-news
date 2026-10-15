"""Regression tests for fast article navigation and distinct editorial fields."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import app as world_pulse


class SiteExperienceTests(unittest.TestCase):
    def test_long_headline_is_shortened_and_duplicate_summary_is_repaired(self):
        headline = (
            "Government announces a major new energy support plan for households as "
            "fuel prices continue rising across several regions"
        )
        row = {
            "slug": "story-long-title",
            "source_url": "https://www.cnn.com/example-story",
            "category": "world",
            "source_name": "CNN",
            "source_domain": "cnn.com",
            "original_language": "en",
            "title_en": headline,
            "title_ar": "",
            "summary_en": headline,
            "summary_ar": "",
            "content_en": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertLessEqual(len(story["title"]), 92)
        self.assertTrue(story["title"].endswith("…"))
        self.assertFalse(world_pulse._summary_repeats_title(headline, story["summary"]))
        self.assertIn("original publisher", story["summary"])

    def test_distinct_details_can_be_used_as_summary_when_headline_and_summary_match(self):
        headline = "Central bank announces a new interest-rate decision"
        detail = (
            "The central bank said its policy committee voted to hold the benchmark rate. "
            "Officials said the next decision will depend on incoming inflation and employment data."
        )
        row = {
            "slug": "story-summary-details",
            "source_url": "https://www.reuters.com/example-story",
            "category": "economy",
            "source_name": "Reuters",
            "source_domain": "reuters.com",
            "original_language": "en",
            "title_en": headline,
            "title_ar": "",
            "summary_en": headline,
            "summary_ar": "",
            "content_en": detail,
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertIn("central bank said", story["summary"].casefold())
        self.assertNotEqual(story["title"], story["summary"])
        self.assertTrue(story["content"])

    def test_article_route_builds_the_display_pool_only_once(self):
        stories = [
            {"slug": "story-one", "category": "technology", "title": "Short title"},
            {"slug": "story-two", "category": "technology", "title": "Related story"},
        ]
        with patch.object(world_pulse, "_get_display_stories", return_value=stories) as pool:
            with patch.object(world_pulse, "_find_article", side_effect=AssertionError("duplicate DB scan")):
                with patch.object(world_pulse, "render_template", return_value="article rendered"):
                    response = world_pulse.app.test_client().get("/article/story-one?lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "article rendered")
        pool.assert_called_once_with("en")

    def test_homepage_ticker_uses_latest_story_and_does_not_require_a_today_timestamp(self):
        latest = {
            "slug": "latest-story",
            "category": "world",
            "title": "Latest stored story",
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        with patch.object(world_pulse, "_maybe_start_refresh"):
            with patch.object(world_pulse, "_get_display_stories", return_value=[latest]):
                with patch.object(world_pulse, "render_template", return_value="home") as render:
                    response = world_pulse.app.test_client().get("/?lang=ar")
        self.assertEqual(response.status_code, 200)
        self.assertIs(render.call_args.kwargs["breaking_story"], latest)

    def test_image_refresh_prioritises_stories_without_persisted_images(self):
        newest_with_image = {
            "slug": "newest-with-image",
            "image_url": "https://example.com/photo.jpg",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }
        newest_missing = {
            "slug": "newest-missing",
            "image_url": "",
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        older_missing = {
            "slug": "older-missing",
            "image_url": "",
            "published_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
        }
        older_with_image = {
            "slug": "older-with-image",
            "image_url": "https://example.com/older.jpg",
            "published_at": datetime(2026, 10, 12, tzinfo=timezone.utc),
        }
        rows = world_pulse._prioritise_missing_image_rows([
            newest_with_image, older_with_image, newest_missing, older_missing,
        ])
        self.assertEqual(
            [row["slug"] for row in rows],
            ["newest-missing", "older-missing", "newest-with-image", "older-with-image"],
        )

    def test_image_refresh_rotates_past_recently_checked_missing_photos(self):
        now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        recent_failed = {
            "slug": "recent-failed",
            "image_url": "",
            "image_checked_at": now,
            "published_at": now,
        }
        older_unchecked = {
            "slug": "older-unchecked",
            "image_url": "",
            "image_checked_at": None,
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        older_failed = {
            "slug": "older-failed",
            "image_url": "",
            "image_checked_at": datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc),
            "published_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
        }
        existing_photo = {
            "slug": "existing-photo",
            "image_url": "https://example.com/photo.jpg",
            "image_checked_at": None,
            "published_at": now,
        }
        rows = world_pulse._prioritise_missing_image_rows([
            recent_failed, older_failed, existing_photo, older_unchecked,
        ])
        self.assertEqual(
            [row["slug"] for row in rows],
            ["older-unchecked", "older-failed", "recent-failed", "existing-photo"],
        )

    def test_forced_image_refresh_does_not_reuse_a_fresh_cached_photo_when_better_match_exists(self):
        checked_at = datetime.now(timezone.utc)
        source_url = "https://www.example.com/news/image-refresh"
        stored = {
            "slug": "image-refresh-story",
            "source_url": source_url,
            "category": "technology",
            "source_name": "Example News",
            "source_domain": "example.com",
            "image_url": "https://images.example.com/old-photo.jpg",
            "image_source": "wikimedia_relevant",
            "image_credit": "Old photographer",
            "image_credit_url": "https://commons.wikimedia.org/wiki/Old_photo",
            "image_provider_url": "https://commons.wikimedia.org/wiki/Old_photo",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": checked_at,
            "title_en": "New satellite technology launched",
            "title_ar": "",
            "summary_en": "A brief summary of a satellite technology launch.",
            "summary_ar": "",
            "content_en": "",
            "content_ar": "",
            "original_language": "en",
            "published_at": checked_at,
            "fetched_at": checked_at,
            "read_minutes": 1,
            "is_demo": False,
        }
        raw = {
            "slug": stored["slug"],
            "source_url": source_url,
            "category": "technology",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": stored["title_en"],
            "original_language": "en",
            "image_search_title": stored["title_en"],
            "image_url": "",
            "image_source": "none",
            "image_checked_at": None,
        }
        new_result = {
            "image_url": "https://images.example.com/new-photo.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "New photographer",
            "image_credit_url": "https://photos.example.org/item/new-photo",
            "image_provider_url": "https://photos.example.org/item/new-photo",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": checked_at,
        }
        with patch.object(world_pulse, "_db_fetch_all", return_value=[stored]):
            with patch.object(world_pulse, "_control_enabled", return_value=True):
                with patch.object(world_pulse, "_search_any_reusable_image", return_value=new_result):
                    world_pulse._enrich_article_images([raw], force_refresh=True, allow_ai_generation=False)

        self.assertEqual(raw["image_url"], new_result["image_url"])
        self.assertEqual(raw["image_credit"], "New photographer")
        self.assertEqual(raw["image_source"], "openverse_licensed")


if __name__ == "__main__":
    unittest.main()
