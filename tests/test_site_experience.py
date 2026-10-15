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
