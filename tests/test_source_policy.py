import unittest

import app as world_pulse


class SourcePolicyTests(unittest.TestCase):
    def test_category_publisher_allowlist_accepts_subdomains(self):
        self.assertEqual(
            world_pulse._source_domain_for_category("technology", "en", "www.theverge.com"),
            "theverge.com",
        )
        self.assertEqual(
            world_pulse._source_domain_for_category("technology", "en", "news.unknown.test"),
            "",
        )

    def test_language_site_rejects_wrong_language_and_unknown_domains(self):
        arabic_story = {
            "category": "technology",
            "original_language": "ar",
            "source_domain": "aitnews.com",
            "source_name": "AIT News",
        }
        self.assertTrue(world_pulse._row_allowed_on_language_site(arabic_story, "ar"))
        self.assertFalse(world_pulse._row_allowed_on_language_site(arabic_story, "en"))

        unapproved = dict(arabic_story, source_domain="unknown.example")
        self.assertFalse(world_pulse._row_allowed_on_language_site(unapproved, "ar"))

    def test_headline_image_query_removes_editorial_filler(self):
        query = world_pulse._image_search_phrase(
            "Breaking: NASA announces Artemis moon mission today"
        )
        self.assertIn("NASA", query)
        self.assertIn("Artemis", query)
        self.assertNotIn("Breaking", query)
        self.assertNotIn("today", query.casefold())

    def test_image_match_score_prefers_related_metadata(self):
        self.assertGreater(
            world_pulse._image_match_score("NASA Artemis mission", "NASA Artemis rocket launch"),
            0,
        )
        self.assertEqual(
            world_pulse._image_match_score("NASA Artemis mission", "football stadium referee"),
            0,
        )


    def test_public_mutation_apis_require_csrf(self):
        client = world_pulse.app.test_client()
        refresh = client.post("/api/refresh", headers={"X-CSRF-Token": "not-a-valid-token"})
        self.assertEqual(refresh.status_code, 400)

        ask = client.post(
            "/api/ask",
            json={"slug": "not-a-real-story", "lang": "en", "question": "What happened?"},
            headers={"X-CSRF-Token": "not-a-valid-token"},
        )
        self.assertEqual(ask.status_code, 400)

    def test_original_language_story_can_be_persisted_without_gemini(self):
        article = world_pulse._base_article({
            "slug": "story-test",
            "source_url": "https://aitnews.com/example",
            "category": "technology",
            "source_name": "AIT News",
            "source_domain": "aitnews.com",
            "original_title": "عنوان تقني",
            "original_summary": "ملخص الخبر",
            "original_language": "ar",
        })
        self.assertEqual(article["title_ar"], "عنوان تقني")
        self.assertEqual(article["summary_ar"], "ملخص الخبر")
        self.assertEqual(article["title_en"], "")
        self.assertEqual(article["original_language"], "ar")
        self.assertEqual(article["content_ar"], "")


if __name__ == "__main__":
    unittest.main()
