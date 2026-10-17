"""Offline regression tests for source-aware news ingestion and DB URL handling."""
from __future__ import annotations

import os
import json
import unittest
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
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
        # Each category/language pair gets two rotating groups and sometimes a priority
        # group. Science-English also gets the three explicitly configured official feeds.
        counts = [
            sum(1 for c, l, _ in calls if (c, l) == pair)
            for pair in expected_pairs
        ]
        for pair in expected_pairs - {("science", "en")}:
            count = sum(1 for c, l, _ in calls if (c, l) == pair)
            self.assertTrue(2 <= count <= 3, (pair, count))
        science_en_groups = [group for c, l, group in calls if (c, l) == ("science", "en")]
        direct_feeds = [group for group in science_en_groups if group[0] == world_pulse.DIRECT_RSS_SENTINEL]
        self.assertEqual(len(direct_feeds), 5)
        self.assertEqual(
            {group[1] for group in direct_feeds},
            {"nasa.gov", "noaa.gov", "aljazeera.net", "aljazeera.com"},
        )
        direct_names = {group[2] for group in direct_feeds}
        self.assertIn("Al Jazeera Arabic (headline and source link only)", direct_names)
        self.assertIn("Al Jazeera English (headline and source link only)", direct_names)
        for category, lang, priority_domains in (
            ("gaming", "ar", ("saudigamer.com", "true-gaming.net", "arabhardware.net")),
            ("world", "ar", ("aljazeera.net", "almamlakatv.com", "petra.gov.jo")),
        ):
            pair_groups = [group for c, l, group in calls if (c, l) == (category, lang)]
            self.assertIn(priority_domains, pair_groups)

    def test_official_direct_rss_rejects_entries_outside_expected_publisher_host(self):
        good = {
            "title": "NASA announces a new science mission",
            "link": "https://www.nasa.gov/news-release/example-mission/",
            "summary": "A short public news release about the science mission.",
            "published": "Fri, 16 Oct 2026 08:00:00 GMT",
        }
        bad = {
            "title": "A cross-publisher item must be rejected",
            "link": "https://example.invalid/copied-story/",
            "summary": "This URL is not hosted by the trusted feed owner.",
        }
        response = MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<rss />"
        with (
            patch.object(world_pulse, "urlopen", return_value=response),
            patch.object(world_pulse.feedparser, "parse", return_value=SimpleNamespace(entries=[good, bad])),
            patch.object(world_pulse, "_parse_published", return_value=datetime(2026, 10, 16, tzinfo=timezone.utc)),
            patch.object(world_pulse, "_control_enabled", return_value=True),
            patch.object(world_pulse, "_domain_needs_license", return_value=False),
            patch.object(world_pulse, "_is_headline_only_domain", return_value=False),
            patch.object(world_pulse, "_publisher_requires_license", return_value=False),
        ):
            category, lang, items = world_pulse._parse_direct_rss_feed(
                "https://www.nasa.gov/news-release/feed/", "science", "en", "nasa.gov", "NASA News Releases"
            )

        self.assertEqual((category, lang), ("science", "en"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_url"], good["link"])
        self.assertEqual(items[0]["source_domain"], "nasa.gov")
        self.assertEqual(items[0]["original_title"], good["title"])


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
    def test_third_gemini_model_is_tried_when_both_first_models_return_429(self):
        def successful_response(**kwargs):
            payload = json.loads(kwargs["contents"])
            stories = []
            for article in payload:
                index = article["index"]
                stories.append({
                    "index": index,
                    "title_ar": "عنوان صحفي عربي واضح",
                    "title_en": "A clear English news headline",
                    "summary_ar": "ملخص عربي مستقل يستند إلى مقتطف الناشر.",
                    "summary_en": "An independent English summary based on the publisher excerpt.",
                    "content_ar": "تفاصيل الخبر من نص المصدر دون اختلاق وقائع. " + ("تفصيل متاح. " * 18),
                    "content_en": "Story details from source text without invented facts. " + ("Available detail. " * 18),
                })
            return SimpleNamespace(text=json.dumps({"stories": stories}))

        calls = []
        def respond(**kwargs):
            model = kwargs["model"]
            calls.append(model)
            if model in {"gemini-3.5-flash-lite", "gemini-3.8-flash"}:
                raise RuntimeError("429 RESOURCE_EXHAUSTED model-specific rate limit")
            return successful_response(**kwargs)

        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=respond)))
        fake_genai = SimpleNamespace(Client=Mock(return_value=client))
        fake_types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda attempts: SimpleNamespace(attempts=attempts),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        articles = [
            {
                "category": "world",
                "source_name": "Test publisher",
                "source_url": f"https://example.com/third-model-{index}",
                "original_title": f"Independent news headline {index}",
                "original_summary": f"Publisher excerpt about event {index}.",
                "original_language": "en",
            }
            for index in range(12)
        ]

        with (
            patch.object(world_pulse, "GEMINI_API_KEY", "test-key"),
            patch.object(world_pulse, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
            patch.object(world_pulse, "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"),
            patch.object(world_pulse, "GEMINI_FALLBACK_MODEL_2", "gemini-3.1-flash-lite"),
            patch.object(world_pulse, "genai", fake_genai),
            patch.object(world_pulse, "types", fake_types),
            patch.object(world_pulse, "MAX_GEMINI_API_CALLS_PER_REFRESH", 4),
            patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")),
            patch.object(world_pulse, "_persist_shared_gemini_cooldown", return_value=True),
            patch.object(world_pulse, "_build_editorial_prompt", side_effect=lambda items: json.dumps(items)),
            patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0),
            patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0),
        ):
            translated = world_pulse._translate_batch(articles)

        self.assertEqual(calls, [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.1-flash-lite",
        ])
        self.assertEqual(set(translated), set(range(12)))


    def test_primary_model_429_switches_remaining_batches_to_alternate(self):
        def successful_response(**kwargs):
            payload = json.loads(kwargs["contents"])
            stories = []
            for article in payload:
                index = article["index"]
                stories.append({
                    "index": index,
                    "title_ar": "عنوان صحفي عربي واضح",
                    "title_en": "A clear English news headline",
                    "summary_ar": "ملخص عربي مستقل يستند إلى مقتطف المصدر.",
                    "summary_en": "An independent English summary based on the source excerpt.",
                    "content_ar": "تفاصيل الخبر من النص المتاح دون إضافة وقائع غير مثبتة. " + ("تفصيل موثق. " * 18),
                    "content_en": "Story details from available source text without invented facts. " + ("Verified detail. " * 18),
                })
            return SimpleNamespace(text=json.dumps({"stories": stories}))

        calls = []
        def generate(**kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gemini-3.5-flash-lite" and len(calls) == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED model-specific rate limit")
            return successful_response(**kwargs)

        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(side_effect=generate)))
        fake_genai = SimpleNamespace(Client=Mock(return_value=client))
        fake_types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda attempts: SimpleNamespace(attempts=attempts),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        articles = [
            {
                "category": "world",
                "source_name": "Test publisher",
                "source_url": f"https://example.com/failover-{index}",
                "original_title": f"Independent news headline {index}",
                "original_summary": f"Publisher excerpt about a distinct event {index}.",
                "original_language": "en",
            }
            for index in range(12)
        ]
        with (
            patch.object(world_pulse, "GEMINI_API_KEY", "test-key"),
            patch.object(world_pulse, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
            patch.object(world_pulse, "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"),
            patch.object(world_pulse, "genai", fake_genai),
            patch.object(world_pulse, "types", fake_types),
            patch.object(world_pulse, "MAX_GEMINI_API_CALLS_PER_REFRESH", 3),
            patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")),
            patch.object(world_pulse, "_persist_shared_gemini_cooldown", return_value=True),
            patch.object(world_pulse, "_build_editorial_prompt", side_effect=lambda items: json.dumps(items)),
            patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0),
            patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0),
        ):
            translated = world_pulse._translate_batch(articles)

        self.assertEqual(calls, [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.8-flash",
        ])
        self.assertEqual(set(translated), set(range(12)))


    def test_model_specific_429_uses_single_alternate_model_attempt(self):
        def success_response(**kwargs):
            payload = json.loads(kwargs["contents"])
            stories = []
            for article in payload:
                index = article["index"]
                stories.append({
                    "index": index,
                    "title_ar": "عنوان صحفي عربي واضح",
                    "title_en": "A clear English news headline",
                    "summary_ar": "ملخص عربي مستقل يذكر الوقائع الموجودة في المقتطف.",
                    "summary_en": "An independent English summary containing the facts in the excerpt.",
                    "content_ar": "تفاصيل الخبر اعتماداً على النص المتاح دون اختلاق معلومات. " + ("تفصيل متاح. " * 18),
                    "content_en": "Story details from the available source text without invented facts. " + ("Available detail. " * 18),
                })
            return SimpleNamespace(text=json.dumps({"stories": stories}))

        def respond(**kwargs):
            if kwargs["model"] == "gemini-3.5-flash-lite":
                raise RuntimeError("429 RESOURCE_EXHAUSTED model-specific rate limit")
            return success_response(**kwargs)

        generate = Mock(side_effect=respond)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        fake_genai = SimpleNamespace(Client=Mock(return_value=client))
        fake_types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda attempts: SimpleNamespace(attempts=attempts),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        payload = [{
            "category": "world",
            "source_name": "Test publisher",
            "source_url": "https://example.com/model-failover-story",
            "original_title": "An important policy decision announced today",
            "original_summary": "The committee approved the proposal following a public vote.",
            "original_language": "en",
        }]

        with (
            patch.object(world_pulse, "GEMINI_API_KEY", "test-key"),
            patch.object(world_pulse, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
            patch.object(world_pulse, "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"),
            patch.object(world_pulse, "genai", fake_genai),
            patch.object(world_pulse, "types", fake_types),
            patch.object(world_pulse, "MAX_GEMINI_API_CALLS_PER_REFRESH", 2),
            patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")),
            patch.object(world_pulse, "_persist_shared_gemini_cooldown", return_value=True) as persist,
            patch.object(world_pulse, "_build_editorial_prompt", side_effect=lambda items: json.dumps(items)),
            patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0),
            patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0),
        ):
            translated = world_pulse._translate_batch(payload)

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args_list[0].kwargs["model"], "gemini-3.5-flash-lite")
        self.assertEqual(generate.call_args_list[1].kwargs["model"], "gemini-3.8-flash")
        self.assertEqual(set(translated), {0})
        persist.assert_called_once_with(
            "rate_limited_429", state_key="gemini_cooldown:gemini-3.5-flash-lite"
        )

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
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs),
            HttpRetryOptions=lambda attempts: SimpleNamespace(attempts=attempts),
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
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
            for index in range(24)
        ]

        with (
            patch.object(world_pulse, "GEMINI_API_KEY", "test-key"),
            patch.object(world_pulse, "genai", fake_genai),
            patch.object(world_pulse, "types", fake_types),
            patch.object(world_pulse, "MAX_GEMINI_API_CALLS_PER_REFRESH", 3),
            patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0),
            patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0),
            patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")),
            patch.object(world_pulse, "_build_editorial_prompt", side_effect=lambda payload: json.dumps(payload)),
        ):
            result = world_pulse._translate_batch(raw_articles)

        self.assertEqual(generate.call_count, 3)
        self.assertEqual(set(result), set(range(18)))
        client_options = fake_genai.Client.call_args.kwargs["http_options"]
        self.assertEqual(client_options.retry_options.attempts, 1)


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
