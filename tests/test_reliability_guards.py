"""Regression tests for the production reliability fixes in the newsroom pipeline."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as world_pulse


class StructuredEditorialResponseTests(unittest.TestCase):
    def test_parses_fenced_structured_json(self):
        value = {"stories": [{"index": 0, "title_en": "Headline"}]}
        parsed = world_pulse._parse_editorial_response_text(
            "```json\n" + json.dumps(value) + "\n```"
        )
        self.assertEqual(parsed[0]["title_en"], "Headline")

    def test_recovers_valid_story_json_after_a_short_preamble(self):
        value = {"stories": [{"index": 0, "content_en": "Text with a } brace"}]}
        parsed = world_pulse._parse_editorial_response_text(
            "Here is the result:\n" + json.dumps(value)
        )
        self.assertEqual(parsed[0]["content_en"], "Text with a } brace")

    def test_rejects_empty_or_malformed_model_output(self):
        with self.assertRaises(world_pulse._InvalidEditorialResponse):
            world_pulse._parse_editorial_response_text("")

        with self.assertRaises(world_pulse._InvalidEditorialResponse):
            world_pulse._parse_editorial_response_text("not JSON")

    def test_image_query_uses_english_anchors_for_known_arabic_entities(self):
        query = world_pulse._english_image_anchor_query(
            "روسيا وأوكرانيا تبحثان اتفاقاً جديداً",
            "اجتماع مسؤولين في أوكرانيا",
        )
        self.assertIn("Russia", query)
        self.assertIn("Ukraine", query)

    def test_long_title_can_match_a_distinctive_named_entity(self):
        self.assertGreater(
            world_pulse._image_match_score(
                "Ukraine officials hold talks amid a new regional security proposal",
                "Ukraine officials meet at a regional summit",
            ),
            0,
        )
        self.assertEqual(
            world_pulse._image_match_score("Trump tariff China", "China city skyline"),
            0.0,
        )

    def test_gemini_invalid_json_tries_fallback_model(self):
        story = {
            "index": 0,
            "title_ar": "عنوان عربي واضح",
            "title_en": "A clear English headline",
            "summary_ar": "هذا ملخص عربي مستقل يتضمن تفاصيل تدعمها المادة الأصلية.",
            "summary_en": "This is a distinct English summary grounded in the original source material.",
            "content_ar": "تتضمن المادة تفاصيل موجزة إضافية تدعمها المعلومات المتاحة من المصدر الأصلي.",
            "content_en": "The source provides additional concise details that support this brief and avoid adding unsupported claims.",
        }
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = [
            SimpleNamespace(text="not JSON"),
            SimpleNamespace(text=json.dumps({"stories": [story]}, ensure_ascii=False)),
        ]
        article = {
            "source_url": "https://example.test/story",
            "source_name": "Example News",
            "category": "world",
            "original_title": "A verified headline",
            "original_summary": "A concise publisher excerpt with enough context.",
            "original_language": "en",
        }
        with patch.object(world_pulse.genai, "Client", return_value=fake_client):
            with patch.object(world_pulse, "GEMINI_API_KEY", "test-key"):
                with patch.object(world_pulse, "_shared_gemini_cooldown_remaining", return_value=(0, "")):
                    with patch.object(world_pulse, "_persist_shared_gemini_cooldown", return_value=True):
                        result = world_pulse._translate_batch([article])

        self.assertEqual(result[0]["title_en"], "A clear English headline")
        self.assertEqual(fake_client.models.generate_content.call_count, 2)
        self.assertEqual(
            fake_client.models.generate_content.call_args_list[0].kwargs["model"],
            world_pulse.GEMINI_MODEL,
        )
        self.assertEqual(
            fake_client.models.generate_content.call_args_list[1].kwargs["model"],
            world_pulse.GEMINI_FALLBACK_MODEL,
        )



class PersistentArchiveStabilityTests(unittest.TestCase):
    def test_database_outage_uses_last_successful_archive_snapshot(self):
        snapshot = [
            {"slug": "saved-story", "source_url": "https://example.test/saved-story"}
        ]
        with patch.object(world_pulse, "_DB_ARTICLES_CACHE", snapshot):
            with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", 0.0):
                with patch.object(world_pulse, "_ensure_schema", return_value=False):
                    result = world_pulse._db_fetch_all()

        self.assertEqual(result, snapshot)
        self.assertIsNot(result, snapshot)

    def test_display_list_uses_shared_database_rows_not_worker_local_memory(self):
        persisted = {
            "slug": "persisted-story",
            "source_url": "https://example.test/persisted",
            "published_at": None,
            "fetched_at": None,
        }
        worker_only = {
            "slug": "worker-only-story",
            "source_url": "https://example.test/worker-only",
            "published_at": None,
            "fetched_at": None,
        }
        with patch.object(world_pulse, "_db_fetch_all", return_value=[persisted]):
            with patch.dict(world_pulse._MEMORY_ARTICLES, {"https://example.test/worker-only": worker_only}, clear=True):
                rows = world_pulse._all_live_articles()

        self.assertEqual([row["slug"] for row in rows], ["persisted-story"])

    def test_archived_story_permalink_falls_back_to_direct_database_lookup(self):
        archived = {
            "slug": "older-saved-story",
            "source_url": "https://example.test/older-saved-story",
            "source_name": "Example News",
            "source_domain": "example.test",
            "category": "world",
            "original_language": "en",
            "title_en": "An archived story",
            "title_ar": "",
            "summary_en": "A saved story summary.",
            "summary_ar": "",
            "content_en": "The saved story details.",
            "content_ar": "",
        }
        with patch.object(world_pulse, "_ensure_background_scheduler"):
            with patch.object(world_pulse, "current_language", return_value="en"):
                with patch.object(world_pulse, "_get_display_stories", return_value=[]):
                    with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=archived) as lookup:
                        with patch.object(world_pulse, "_row_allowed_on_language_site", return_value=True):
                            with patch.object(world_pulse, "_display_category", return_value="world"):
                                with patch.object(world_pulse, "_normalise_story", side_effect=lambda row, lang: dict(row)):
                                    with patch.object(world_pulse, "render_template", return_value="article rendered") as render:
                                        response = world_pulse.app.test_client().get("/article/older-saved-story?lang=en")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "article rendered")
        lookup.assert_called_once_with("older-saved-story")
        self.assertEqual(render.call_args.kwargs["article"]["slug"], "older-saved-story")


if __name__ == "__main__":
    unittest.main()
