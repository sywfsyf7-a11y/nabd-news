"""Offline regression tests for source-aware news ingestion and DB URL handling."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch
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
