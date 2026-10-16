"""Offline regression tests for source-aware news ingestion and DB URL handling."""
from __future__ import annotations

import os
import json
import unittest
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import app as world_pulse


class RSSPublisherGroupTests(unittest.TestCase):
    def _patch_rss_catalogue(self):
        return (
            patch.object(world_pulse, "_control_enabled", return_value=True),
            patch.object(world_pulse, "_domain_needs_license", return_value=False),
            patch.object(world_pulse, "_is_headline_only_domain", return_value=False),
        )

    def test_targeted_query_contains_only_the_requested_eligible_publisher_group(self):
        captured = {}

        def fake_parse(feed_url, category, lang, source_label):
            captured["url"] = feed_url
            captured["category"] = category
            captured["lang"] = lang
            return category, lang, []

        controls = self._patch_rss_catalogue()
        with controls[0], controls[1], controls[2], patch.object(
            world_pulse, "_parse_any_rss", side_effect=fake_parse
        ):
            result = world_pulse._parse_feed_task(
                "politics", "en", ("bbc.com", "cnn.com")
            )

        self.assertEqual(result, ("politics", "en", []))
        query = parse_qs(urlparse(captured["url"]).query)["q"][0]
        self.assertIn("site:bbc.com", query)
        self.assertIn("site:cnn.com", query)
        self.assertIn("when:3d", query)
        self.assertNotIn("site:reuters.com", query)

    def test_disallowed_group_is_rejected_before_network_access(self):
        controls = self._patch_rss_catalogue()
        with controls[0], controls[1], controls[2], patch.object(
            world_pulse, "_parse_any_rss"
        ) as parse:
            result = world_pulse._parse_feed_task(
                "politics", "en", ("not-an-allowlisted-domain.invalid",)
            )

        self.assertEqual(result, ("politics", "en", []))
        parse.assert_not_called()

    def test_collection_returns_cleanly_when_no_sources_are_enabled(self):
        with (
            patch.object(world_pulse, "_prime_source_control_cache"),
            patch.object(world_pulse, "_control_enabled", return_value=False),
            patch.object(world_pulse, "_parse_feed_task") as parse,
        ):
            result = world_pulse._collect_rss_articles()

        self.assertEqual(result, [])
        parse.assert_not_called()

    def test_collection_rotates_two_small_groups_per_category_and_language(self):
        calls = []

        def fake_parse(category, lang, source_group=None):
            calls.append((category, lang, tuple(source_group or ())))
            return category, lang, []

        with (
            patch.object(world_pulse, "_prime_source_control_cache"),
            patch.object(world_pulse, "_control_enabled", return_value=True),
            patch.object(world_pulse, "_domain_needs_license", return_value=False),
            patch.object(world_pulse, "_is_headline_only_domain", return_value=False),
            patch.object(world_pulse, "_parse_feed_task", side_effect=fake_parse),
        ):
            result = world_pulse._collect_rss_articles()

        expected_pairs = {
            (category, lang)
            for category in world_pulse.CATEGORY_NAMES
            for lang in ("ar", "en")
        }
        self.assertEqual(result, [])
        self.assertEqual({(category, lang) for category, lang, _ in calls}, expected_pairs)
        self.assertTrue(all(1 <= len(group) <= 4 for _, _, group in calls))
        self.assertTrue(all(count == 2 for count in (
            sum(1 for c, l, _ in calls if (c, l) == pair)
            for pair in expected_pairs
        )))


class RSSDeadlineSeparationTests(unittest.TestCase):
    def test_ready_feed_results_are_not_lost_to_classification_time(self):
        now = datetime.now(timezone.utc)
        stories = {
            "en": {
                "source_url": "https://cnn.com/unique-english-story",
                "source_domain": "cnn.com",
                "source_name": "CNN",
                "original_title": "A distinct English headline about a major technology launch",
                "original_summary": "A short source excerpt.",
                "original_language": "en",
                "published_at": now,
            },
            "ar": {
                "source_url": "https://arabnews.com/unique-arabic-story",
                "source_domain": "arabnews.com",
                "source_name": "Arab News",
                "original_title": "عنوان عربي مختلف حول إطلاق تقني مهم اليوم",
                "original_summary": "مقتطف قصير من المصدر.",
                "original_language": "ar",
                "published_at": now - timedelta(seconds=5),
            },
        }

        def fake_parse(category, lang, source_group=None):
            # Both I/O jobs finish inside the deadline. English finishes first, which
            # used to trigger slow classification before as_completed yielded Arabic.
            time.sleep(0.01 if lang == "en" else 0.03)
            return category, lang, [dict(stories[lang])]

        def slow_classification(title, summary, fallback, source_domain=""):
            time.sleep(0.09)
            return fallback

        with (
            patch.object(world_pulse, "CATEGORY_NAMES", {"politics": {"ar": "سياسة", "en": "Politics"}}),
            patch.object(world_pulse, "CATEGORY_SOURCE_DOMAINS", {"politics": {"ar": ["arabnews.com"], "en": ["cnn.com"]}}),
            patch.object(world_pulse, "_prime_source_control_cache"),
            patch.object(world_pulse, "_control_enabled", return_value=True),
            patch.object(world_pulse, "_domain_needs_license", return_value=False),
            patch.object(world_pulse, "_is_headline_only_domain", return_value=False),
            patch.object(world_pulse, "_parse_feed_task", side_effect=fake_parse),
            patch.object(world_pulse, "_classify_story", side_effect=slow_classification),
            patch.object(world_pulse, "RSS_BATCH_TIMEOUT_SECONDS", 0.06),
        ):
            result = world_pulse._collect_rss_articles()

        self.assertEqual(len(result), 2)
        self.assertEqual({story["original_language"] for story in result}, {"ar", "en"})


class GeminiRequestBudgetTests(unittest.TestCase):
    def test_translation_stops_after_configured_api_call_budget(self):
        def fake_generate_content(**kwargs):
            payload = json.loads(kwargs["contents"])
            stories = []
            for article in payload:
                index = article["index"]
                stories.append({
                    "index": index,
                    "title_ar": "عنوان صحفي عربي واضح",
                    "title_en": "A clear English news headline",
                    "summary_ar": "ملخص عربي مستقل يستند إلى مقتطف المصدر المتاح.",
                    "summary_en": "An independent English summary based on the available source excerpt.",
                    "content_ar": "تفاصيل الخبر من المعلومات المتاحة دون إضافة وقائع غير مثبتة. " + ("تفصيل موثق. " * 20),
                    "content_en": "Story details based on the available information without adding unsupported facts. " + ("Verified detail. " * 20),
                })
            return SimpleNamespace(text=json.dumps({"stories": stories}))

        generate = Mock(side_effect=fake_generate_content)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        fake_genai = SimpleNamespace(Client=Mock(return_value=client))
        fake_types = SimpleNamespace(
            HttpOptions=Mock(return_value=None),
            GenerateContentConfig=Mock(return_value=None),
        )
        raw_articles = [
            {
                "category": "world",
                "source_name": "Test publisher",
                "source_url": f"https://example.com/story-{index}",
                "original_title": f"Test headline number {index}",
                "original_summary": "A verified RSS excerpt.",
                "original_language": "en",
            }
            for index in range(12)
        ]

        with (
            patch.object(world_pulse, "GEMINI_API_KEY", "test-key"),
            patch.object(world_pulse, "genai", fake_genai),
            patch.object(world_pulse, "types", fake_types),
            patch.object(world_pulse, "MAX_GEMINI_API_CALLS_PER_REFRESH", 2),
            patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0),
            patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0),
            patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")),
            patch.object(world_pulse, "_build_editorial_prompt", side_effect=lambda payload: json.dumps(payload)),
        ):
            result = world_pulse._translate_batch(raw_articles)

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(set(result), set(range(8)))


class DatabaseURLTests(unittest.TestCase):
    def test_shared_supabase_pooler_url_uses_transaction_pooling_compatibly(self):
        dsn = (
            "postgresql://wp_user:secret@aws-0-ap-northeast-1.pooler.supabase.com:5432/"
            "postgres?pgbouncer=true&sslmode=require"
        )
        with patch.dict(os.environ, {"SUPABASE_POOLER_URL": dsn}):
            normalized = world_pulse._database_url()

        parsed = urlparse(normalized)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.port, 6543)
        self.assertEqual(parsed.path, "/postgres")
        self.assertNotIn("pgbouncer", query)
        self.assertEqual(query.get("sslmode"), ["require"])


if __name__ == "__main__":
    unittest.main()
