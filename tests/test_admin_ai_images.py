"""Regression tests for admin-selected AI illustration generation and image persistence."""
import unittest
from unittest.mock import patch

import app as world_pulse


class AdminAiImageTests(unittest.TestCase):
    def test_stored_ai_image_uses_first_party_validation_not_third_party_license(self):
        row = {
            "slug": "ai-illustration-story",
            "source_url": "https://aitnews.com/ai-illustration-story",
            "source_name": "AIT News",
            "source_domain": "aitnews.com",
            "category": "technology",
            "original_language": "en",
            "title_en": "A new technology development announced",
            "title_ar": "إعلان تطور تقني جديد",
            "summary_en": "The company announced a new technical development for customers.",
            "summary_ar": "أعلنت الشركة تطورًا تقنيًا جديدًا للعملاء.",
            "content_en": (
                "The announcement describes a new technical development for customers. "
                "The available report explains its stated purpose and the product area involved "
                "without adding unverified claims or unsupported numbers."
            ),
            "content_ar": (
                "يصف الإعلان تطورًا تقنيًا جديدًا للعملاء. ويوضح التقرير المتاح الغرض المعلن "
                "والمجال الذي يتعلق به المنتج دون إضافة ادعاءات غير متحققة أو أرقام غير مسندة."
            ),
            "image_url": "/media/generated/" + ("a" * 32),
            "image_source": "gemini_generated",
            "image_credit": "AI-generated editorial illustration with Google Gemini",
            "image_credit_url": "",
            "image_provider_url": "https://ai.google.dev/gemini-api/docs/image-generation",
            "image_license_url": "",
            "image_relevance_verified": True,
        }

        self.assertTrue(world_pulse._image_license_verified(row))
        normalised = world_pulse._normalise_story(row, "en")
        self.assertEqual(normalised["image_url"], row["image_url"])
        self.assertEqual(normalised["image_source"], "gemini_generated")

    def test_invalid_generated_image_route_is_rejected(self):
        self.assertFalse(world_pulse._image_license_verified({
            "image_url": "/media/generated/not-a-valid-id",
            "image_source": "gemini_generated",
            "image_license_url": "",
        }))
        self.assertFalse(world_pulse._image_license_verified({
            "image_url": "https://untrusted.example/graphic.jpg",
            "image_source": "gemini_generated",
            "image_license_url": "",
        }))

    def test_admin_generation_is_limited_before_requesting_an_image(self):
        with patch.object(world_pulse, "ADMIN_GEMINI_IMAGE_GENERATION_ENABLED", True):
            with patch.object(world_pulse, "MAX_ADMIN_GEMINI_IMAGES_PER_24H", 2):
                with patch.object(world_pulse, "GEMINI_API_KEY", "configured"):
                    with patch.object(world_pulse, "genai", object()):
                        with patch.object(world_pulse, "types", object()):
                            with patch.object(world_pulse, "_db_count_admin_gemini_images_last_24h", return_value=2):
                                with patch.object(world_pulse, "_generate_gemini_article_image") as generate:
                                    result = world_pulse._admin_generate_and_save_article_image("story-one")

        self.assertEqual(result, "daily_limit")
        generate.assert_not_called()

    def test_admin_image_generation_attaches_the_result_to_the_saved_article(self):
        article = {
            "slug": "story-one",
            "source_url": "https://aitnews.com/story-one",
            "category": "technology",
            "original_language": "en",
            "title_en": "A new technology development announced",
        }
        raw = {
            "slug": "story-one",
            "source_url": "https://aitnews.com/story-one",
            "category": "technology",
            "original_language": "en",
            "original_title": "A new technology development announced",
            "original_summary": "A concise source-supported context.",
        }
        generated = {
            "image_url": "/media/generated/" + ("b" * 32),
            "image_source": "gemini_generated",
            "image_credit": "AI-generated editorial illustration with Google Gemini",
            "image_credit_url": "",
            "image_provider_url": "https://ai.google.dev/gemini-api/docs/image-generation",
            "image_license_url": "",
        }

        with patch.object(world_pulse, "ADMIN_GEMINI_IMAGE_GENERATION_ENABLED", True):
            with patch.object(world_pulse, "MAX_ADMIN_GEMINI_IMAGES_PER_24H", 8):
                with patch.object(world_pulse, "GEMINI_API_KEY", "configured"):
                    with patch.object(world_pulse, "genai", object()):
                        with patch.object(world_pulse, "types", object()):
                            with patch.object(world_pulse, "_db_count_admin_gemini_images_last_24h", return_value=0):
                                with patch.object(world_pulse, "_admin_fetch_article_by_slug", return_value=article):
                                    with patch.object(world_pulse, "_raw_from_stored_article", return_value=raw):
                                        with patch.object(world_pulse, "_generate_gemini_article_image", return_value=generated) as generate:
                                            with patch.object(world_pulse, "_db_update_article_images", return_value=1) as save:
                                                result = world_pulse._admin_generate_and_save_article_image("story-one")

        self.assertEqual(result, "saved")
        generate.assert_called_once_with(raw, manual_admin=True)
        saved_row = save.call_args.args[0][0]
        self.assertEqual(saved_row["source_url"], raw["source_url"])
        self.assertEqual(saved_row["image_url"], generated["image_url"])
        self.assertTrue(saved_row["image_relevance_verified"])

    def test_admin_template_offers_ai_images_when_editing_and_creating_articles(self):
        source, _filename, _uptodate = world_pulse.app.jinja_env.loader.get_source(
            world_pulse.app.jinja_env, "admin_articles.html"
        )
        self.assertIn('name="action" value="generate_ai_article_image"', source)
        self.assertIn('name="create_image_mode"', source)
        self.assertIn('value="upload"', source)
        self.assertIn('value="ai"', source)
        self.assertIn('name="create_image_file"', source)
        self.assertIn("admin_gemini_image_generation_limit", source)


if __name__ == "__main__":
    unittest.main()
