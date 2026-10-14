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

    def test_missing_images_use_original_language_fallbacks(self):
        base = {
            "slug": "story-fallback",
            "source_url": "https://example.test/story",
            "category": "world",
            "title_ar": "عنوان",
            "title_en": "Headline",
            "summary_ar": "",
            "summary_en": "",
            "content_ar": "",
            "content_en": "",
            "original_language": "ar",
            "image_url": "",
            "image_source": "none",
        }
        arabic = world_pulse._normalise_story(dict(base), "ar")
        english = world_pulse._normalise_story(dict(base, original_language="en"), "en")

        self.assertEqual(arabic["image_url"], "/static/A.jpg")
        self.assertEqual(arabic["image_source"], "language_fallback")
        self.assertEqual(english["image_url"], "/static/E.jpg")
        self.assertEqual(english["image_source"], "language_fallback")

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



    def test_gemini_prompt_is_topic_specific_and_brand_aligned(self):
        prompt = world_pulse._build_gemini_image_prompt({
            "category": "technology",
            "original_language": "ar",
            "original_title": "شركة تكشف عن أجهزة منزل ذكية جديدة",
            "original_summary": "أجهزة جديدة تتصل بالشبكة وتعمل مع المنزل الذكي.",
        })
        self.assertIn("شركة تكشف عن أجهزة منزل ذكية جديدة", prompt)
        self.assertIn("نبض العالم", prompt)
        self.assertIn("2D vector infographic", prompt)
        self.assertIn("generic smart devices", prompt)
        self.assertIn("third-party brand logos", prompt)
        self.assertIn("Arabic", prompt)

    def test_gemini_image_generation_uses_the_configured_model_and_persists_jpeg(self):
        import base64
        import io
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from PIL import Image

        png_buffer = io.BytesIO()
        Image.new("RGB", (48, 27), "white").save(png_buffer, format="PNG")
        encoded_png = base64.b64encode(png_buffer.getvalue()).decode("ascii")
        fake_client = MagicMock()
        fake_client.interactions.create.return_value = SimpleNamespace(
            output_image=SimpleNamespace(data=encoded_png, mime_type="image/png")
        )
        article = {
            "category": "technology",
            "original_language": "ar",
            "original_title": "أجهزة منزل ذكية جديدة",
            "original_summary": "ملخص قصير عن الأجهزة المتصلة",
        }
        with patch.object(world_pulse.genai, "Client", return_value=fake_client):
            with patch.object(world_pulse, "GEMINI_API_KEY", "test-key"):
                with patch.object(world_pulse, "GEMINI_IMAGE_GENERATION_ENABLED", True):
                    with patch.object(world_pulse, "_control_enabled", return_value=True):
                        with patch.object(world_pulse, "_store_gemini_generated_image", return_value="b" * 32) as store:
                            result = world_pulse._generate_gemini_article_image(article)

        self.assertEqual(result["image_source"], "gemini_generated")
        self.assertEqual(result["image_url"], "/media/generated/" + "b" * 32)
        store.assert_called_once()
        self.assertTrue(store.call_args.args[0].startswith(b"\xff\xd8"))
        call = fake_client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], world_pulse.GEMINI_IMAGE_MODEL)
        self.assertEqual(call["response_format"]["aspect_ratio"], "16:9")
        self.assertEqual(call["response_format"]["image_size"], "1K")

    def test_gemini_failure_falls_back_to_existing_image_providers(self):
        fallback = {
            "image_url": "https://images.pexels.com/test.jpeg",
            "image_source": "pexels_api",
            "image_credit": "Photographer",
            "image_credit_url": "https://www.pexels.com/",
            "image_provider_url": "https://www.pexels.com/photo/test/",
            "image_license_url": "https://www.pexels.com/license/",
            "image_checked_at": None,
        }
        article = {
            "original_title": "Generic technology story",
            "image_search_title": "Generic technology story",
            "original_language": "en",
            "category": "technology",
            "_allow_ai_image_generation": True,
        }
        from unittest.mock import patch
        with patch.object(world_pulse, "_generate_gemini_article_image", return_value={}) as generator:
            with patch.object(world_pulse, "_search_any_reusable_image", return_value=fallback) as old_sources:
                result = world_pulse._resolve_article_image(article)
        generator.assert_called_once_with(article)
        old_sources.assert_called_once()
        self.assertEqual(result["image_source"], "pexels_api")
        self.assertEqual(result["image_url"], fallback["image_url"])

    def test_all_jinja_templates_compile(self):
        for template_name in world_pulse.app.jinja_env.list_templates():
            with self.subTest(template=template_name):
                world_pulse.app.jinja_env.get_template(template_name)

    def test_generated_image_route_serves_persistent_asset_bytes(self):
        from unittest.mock import patch
        with patch.object(world_pulse, "_read_gemini_generated_image", return_value=(b"fake-jpeg-bytes", "image/jpeg")):
            response = world_pulse.app.test_client().get("/media/generated/" + "a" * 32)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertIn("immutable", response.headers.get("Cache-Control", ""))

    def test_public_mutation_apis_require_csrf(self):
        client = world_pulse.app.test_client()
        refresh = client.post("/api/refresh", headers={"X-CSRF-Token": "not-a-valid-token"})
        self.assertEqual(refresh.status_code, 400)

        ask = client.post(
            "/api/ask",
            json={"slug": "not-a-real-story", "lang": "en", "question": "What happened?"},
        )
        self.assertEqual(ask.status_code, 404)

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
