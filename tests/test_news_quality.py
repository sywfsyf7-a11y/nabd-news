"""Regression tests for story classification, image matching and duplicate suppression."""
import unittest
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
        self.assertEqual(_display_category(row, "en"), "economy")

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


if __name__ == "__main__":
    unittest.main()
