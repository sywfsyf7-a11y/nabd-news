"""Regression tests for story classification, image matching and duplicate suppression."""
import unittest
from unittest.mock import patch

import app as world_pulse
from datetime import datetime, timezone

from app import (
    _canonical_story_url,
    _classify_story,
    _display_category,
    _image_match_score,
    _stories_are_near_duplicates,
)


class NewsQualityTests(unittest.TestCase):
    def test_tracking_parameters_do_not_create_new_story_identity(self):
        first = "https://www.example.com/news/story-123/?utm_source=feed&fbclid=abc#top"
        second = "http://example.com/news/story-123"
        self.assertEqual(_canonical_story_url(first), _canonical_story_url(second))

    def test_content_query_parameters_are_preserved(self):
        first = "https://example.com/story?id=123&utm_campaign=daily"
        second = "https://example.com/story?id=456&utm_campaign=daily"
        self.assertNotEqual(_canonical_story_url(first), _canonical_story_url(second))

    def test_near_duplicate_titles_are_suppressed(self):
        published = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
        first = {
            "source_url": "https://one.example/news/1",
            "original_language": "en",
            "original_title": "Government announces new energy plan for households",
            "published_at": published,
        }
        second = {
            "source_url": "https://two.example/news/2?utm_source=rss",
            "original_language": "en",
            "original_title": "Government announces new energy plan for the households",
            "published_at": published,
        }
        self.assertTrue(_stories_are_near_duplicates(first, second))

    def test_precomputed_feed_signatures_keep_near_duplicate_detection(self):
        first = {
            "source_url": "https://one.example/story",
            "original_language": "en",
            "original_title": "Government announces new energy plan for households",
            "title_en": "Government announces new energy plan for households",
            "published_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        }
        second = {
            "source_url": "https://two.example/story",
            "original_language": "en",
            "original_title": "Government announces new energy plan for the households",
            "title_en": "Government announces new energy plan for the households",
            "published_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        }
        left = world_pulse._display_dedupe_signature(first, "en")
        right = world_pulse._display_dedupe_signature(second, "en")
        self.assertTrue(world_pulse._display_signatures_are_near_duplicates(left, right, "en"))

    def test_similar_length_headlines_with_distinct_words_are_not_duplicates(self):
        first = {
            "source_url": "https://one.example/technology-policy",
            "original_language": "en",
            "original_title": "Government technology policy promises major renewable energy investment",
        }
        second = {
            "source_url": "https://two.example/ocean-science",
            "original_language": "en",
            "original_title": "Scientists discover unusual deep ocean species across remote marine trenches",
        }
        self.assertFalse(_stories_are_near_duplicates(first, second))

    def test_different_topics_are_not_suppressed(self):
        first = {
            "source_url": "https://one.example/news/1",
            "original_language": "en",
            "original_title": "Government announces new energy plan for households",
        }
        second = {
            "source_url": "https://two.example/news/2",
            "original_language": "en",
            "original_title": "Scientists discover a new species in deep ocean waters",
        }
        self.assertFalse(_stories_are_near_duplicates(first, second))

    def test_economy_headline_can_override_incorrect_culture_feed(self):
        result = _classify_story(
            "Fuel crisis deepens in Yemen as prices surge",
            "Fuel shortages and energy prices are rising.",
            "culture",
            "cnn.com",
        )
        self.assertEqual(result, "economy")

    def test_arabic_fuel_headline_can_override_incorrect_culture_feed(self):
        result = _classify_story(
            "أزمة الوقود تتفاقم مع ارتفاع الأسعار",
            "تواجه الأسواق ارتفاعاً في أسعار الوقود والطاقة.",
            "culture",
            "cnn.com",
        )
        self.assertEqual(result, "economy")

    def test_stored_misclassified_story_is_corrected_for_display(self):
        row = {
            "category": "culture",
            "source_domain": "cnn.com",
            "source_name": "CNN",
            "original_language": "en",
            "title_en": "Fuel crisis deepens in Yemen as prices surge",
            "summary_en": "Fuel shortages and energy prices are rising.",
        }
        # CNN is permitted in World News only under the curated publisher policy.
        self.assertEqual(_display_category(row, "en"), "world")

    def test_category_correction_respects_publisher_allowlist(self):
        row = {
            "category": "culture",
            "source_domain": "alqafilah.com",
            "source_name": "Al Qafilah",
            "original_language": "ar",
            "title_ar": "أزمة الوقود تتفاقم مع ارتفاع الأسعار",
            "summary_ar": "تواجه الأسواق ارتفاعاً في أسعار الوقود والطاقة.",
        }
        self.assertEqual(_display_category(row, "ar"), "culture")

    def test_image_match_rejects_single_common_word_for_long_query(self):
        self.assertEqual(
            _image_match_score("Trump tariff China", "China city skyline"),
            0.0,
        )

    def test_image_match_accepts_multiple_topic_terms(self):
        self.assertGreater(
            _image_match_score("Trump tariff China", "Trump tariff dispute with China"),
            0.0,
        )



    def test_publishing_tick_repairs_one_existing_story_without_using_new_story_slot(self):
        fresh = {
            "slug": "fresh-story",
            "source_url": "https://example.test/fresh-story",
            "category": "world",
            "original_language": "en",
        }
        old = {
            "slug": "old-thin-story",
            "source_url": "https://example.test/old-thin-story",
            "source_name": "Example News",
            "source_domain": "example.test",
            "original_language": "en",
        }
        old_raw = {
            "slug": "old-thin-story",
            "source_url": old["source_url"],
            "_database_backfill": True,
        }
        with patch.object(world_pulse, "MAX_ARTICLES_PER_REFRESH", 1):
            with patch.object(world_pulse, "_db_fetch_articles_needing_editorial", return_value=[old]):
                with patch.object(world_pulse, "_raw_from_stored_article", return_value=old_raw):
                    batch, selected_queue_keys = world_pulse._select_news_publication_batch([fresh])

        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0]["source_url"], fresh["source_url"])
        self.assertEqual(batch[1]["source_url"], old["source_url"])
        self.assertEqual(selected_queue_keys, {world_pulse._canonical_story_url(fresh["source_url"])})

    def test_publishing_tick_does_not_rewrite_headline_only_publishers(self):
        fresh = {
            "slug": "fresh-story",
            "source_url": "https://example.test/fresh-story",
            "category": "world",
            "original_language": "en",
        }
        restricted = {
            "slug": "restricted-story",
            "source_url": "https://www.reuters.com/world/example",
            "source_name": "Reuters",
            "source_domain": "reuters.com",
            "original_language": "en",
        }
        with patch.object(world_pulse, "_db_fetch_articles_needing_editorial", return_value=[restricted]):
            with patch.object(world_pulse, "_is_headline_only_domain", return_value=True):
                batch, selected_queue_keys = world_pulse._select_news_publication_batch([fresh])

        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["source_url"], fresh["source_url"])
        self.assertEqual(selected_queue_keys, {world_pulse._canonical_story_url(fresh["source_url"])})

    def test_five_minute_publication_tick_matches_bounded_discovery_queue(self):
        self.assertEqual(world_pulse.NEWS_DISCOVERY_REFRESH_MINUTES, 15)
        self.assertEqual(world_pulse.NEWS_REFRESH_MINUTES, 5)
        self.assertEqual(world_pulse.NEWS_RETRY_MINUTES, 5)
        self.assertEqual(world_pulse.MAX_ARTICLES_PER_REFRESH, 1)
        self.assertEqual(world_pulse.MAX_QUEUE_ADDITIONS_PER_DISCOVERY, 3)

    def test_borderline_image_relevance_is_rejected_to_prevent_misleading_photos(self):
        candidate = {
            "image_url": "https://images.example.test/loosely-related.jpg",
            "image_source": "wikimedia_relevant",
            "_image_relevance_score": 0.383,
            "_image_relevance_evidence": "Iran oil story with a generic portrait",
            "image_credit": "Example contributor",
            "image_credit_url": "https://commons.wikimedia.org/wiki/Example",
            "image_provider_url": "https://commons.wikimedia.org/wiki/Example",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        with patch.object(world_pulse, "_image_search_query_variants", return_value=["Iran oil tanker blockade naval crisis"]):
            with patch.object(world_pulse, "_category_image_search_query", return_value=""):
                with patch.object(world_pulse, "_image_search_query", return_value="Iran oil tanker blockade naval crisis"):
                    with patch.object(world_pulse, "_english_image_anchor_query", return_value=""):
                        with patch.object(world_pulse, "_search_any_reusable_image", return_value=candidate):
                            with patch.object(world_pulse, "_image_match_score", return_value=0.383):
                                result = world_pulse._search_article_image_with_variants(
                                    "Iran oil tanker blockade naval crisis",
                                    "A report about a maritime oil disruption.",
                                    "en",
                                    "world",
                                )

        self.assertEqual(result, {})
        self.assertEqual(world_pulse.MIN_IMAGE_RELEVANCE_SCORE, 0.40)

if __name__ == "__main__":
    unittest.main()
