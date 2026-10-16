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

    def test_bbc_al_jazeera_and_cnn_catalog_policies(self):
        self.assertEqual(world_pulse._source_domain_for_category("world", "ar", "www.aljazeera.net"), "aljazeera.net")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "www.aljazeera.com"), "aljazeera.com")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "edition.cnn.com"), "cnn.com")
        self.assertTrue(world_pulse._is_headline_only_domain("www.bbc.com"))
        self.assertTrue(world_pulse._is_headline_only_domain("aljazeera.com"))
        self.assertFalse(world_pulse._is_headline_only_domain("cnn.com"))

    def test_headline_only_sources_do_not_copy_rss_text_or_generate_ai_article(self):
        row = {
            "slug": "bbc-headline",
            "source_url": "https://www.bbc.com/news/world-example",
            "category": "world",
            "source_domain": "www.bbc.com",
            "source_name": "BBC News",
            "original_language": "en",
            "title_en": "A verified BBC headline",
            "title_ar": "",
            "summary_en": "Publisher headline and source link only.",
            "summary_ar": "",
            "content_en": "This full text must not be displayed on the site.",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
        }
        story = world_pulse._normalise_story(row, "en")
        self.assertTrue(story["headline_only"])
        self.assertEqual(story["content"], "")
        self.assertIn("Headline and source link only", story["summary"])
    def test_major_publishers_are_configured_with_safe_rights_modes(self):
        self.assertEqual(world_pulse._source_domain_for_category("world", "ar", "www.aljazeera.net"), "aljazeera.net")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "www.aljazeera.com"), "aljazeera.com")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(world_pulse._source_domain_for_category("world", "en", "edition.cnn.com"), "cnn.com")
        self.assertTrue(world_pulse._is_headline_only_domain("www.bbc.com"))
        self.assertTrue(world_pulse._is_headline_only_domain("aljazeera.com"))
        self.assertFalse(world_pulse._is_headline_only_domain("cnn.com"))

    def test_headline_only_story_suppresses_body_and_uses_source_notice(self):
        row = {
            "slug": "publisher-headline",
            "source_url": "https://www.bbc.com/news/example",
            "category": "world",
            "source_domain": "www.bbc.com",
            "source_name": "BBC News",
            "original_language": "en",
            "title_en": "Publisher headline",
            "title_ar": "",
            "summary_en": "Old description",
            "summary_ar": "",
            "content_en": "Stored body text",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
        }
        story = world_pulse._normalise_story(row, "en")
        self.assertTrue(story["headline_only"])
        self.assertEqual(story["content"], "")
        self.assertIn("Headline and source link only", story["summary"])

    def test_missing_images_use_language_specific_A_or_E_fallback(self):
        base = {
            "slug": "story-fallback",
            "source_url": "https://example.test/story",
            "category": "science",
            "title_ar": "إطلاق مهمة القمر",
            "title_en": "Lunar mission launch",
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
        self.assertEqual(arabic["image_url"], "/static/images/fallback-ar.svg")
        self.assertEqual(arabic["image_source"], "fallback_ar")
        self.assertEqual(english["image_url"], "/static/images/fallback-en.svg")
        self.assertEqual(english["image_source"], "fallback_en")

    def test_headline_image_query_removes_editorial_filler(self):
        query = world_pulse._image_search_phrase(
            "Breaking: NASA announces Artemis moon mission today"
        )
        self.assertIn("NASA", query)
        self.assertIn("Artemis", query)
        self.assertNotIn("Breaking", query)
        self.assertNotIn("today", query.casefold())

    def test_image_search_variants_retry_the_short_headline_after_context_query(self):
        variants = world_pulse._image_search_query_variants(
            "NASA Artemis mission",
            "The spacecraft carries astronauts around the Moon and returns near Earth.",
        )
        self.assertEqual(len(variants), 3)
        self.assertTrue(variants[0].startswith("NASA Artemis"))
        self.assertIn("astronauts", variants[0].casefold())
        self.assertEqual(variants[1], "NASA Artemis mission")
        self.assertEqual(variants[2], "The spacecraft carries astronauts")

    def test_image_match_score_accepts_one_entity_for_a_two_term_query_but_not_a_long_query(self):
        self.assertEqual(
            world_pulse._image_match_score("Trump tariff China", "China city skyline"),
            0.0,
        )
        self.assertGreater(
            world_pulse._image_match_score("Mourinho Vinicius", "Vinicius Jr football portrait"),
            0,
        )

    def test_image_search_falls_back_to_short_headline_for_open_catalogues(self):
        from unittest.mock import patch

        match = {
            "image_url": "https://images.example.test/vinicius.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Photographer",
            "image_credit_url": "https://openverse.example.test/item",
            "image_provider_url": "https://openverse.example.test/item",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "_image_relevance_score": 0.75,
        }
        article = {
            "slug": "story-image-retry",
            "source_url": "https://example.test/story",
            "category": "sports",
            "original_title": "Mourinho Vinicius ban timing",
            "original_summary": "The football manager commented on the player's suspension.",
            "image_search_title": "Mourinho Vinicius ban timing",
            "image_search_context": "The football manager commented on the player's suspension.",
            "original_language": "en",
        }
        with patch.object(world_pulse, "_search_any_reusable_image", side_effect=[{}, match]) as search:
            result = world_pulse._resolve_article_image(article)
        self.assertEqual(result["image_source"], "openverse_licensed")
        self.assertEqual(search.call_count, 2)
        self.assertEqual(search.call_args_list[1].kwargs, {"open_only": True})

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

    def test_reusable_images_are_tried_before_gemini_generation(self):
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
            with patch.object(world_pulse, "_search_any_reusable_image", return_value=fallback) as reusable:
                result = world_pulse._resolve_article_image(article)
        generator.assert_not_called()
        reusable.assert_called_once_with("Generic technology story", "en", "technology")
        self.assertEqual(result["image_source"], "pexels_api")
        self.assertEqual(result["image_url"], fallback["image_url"])

    def test_gemini_illustration_is_used_only_after_reusable_image_search_fails(self):
        generated = {
            "image_url": "/media/generated/" + "c" * 32,
            "image_source": "gemini_generated",
            "image_credit": "AI-generated illustration with Google Gemini",
            "image_credit_url": "",
            "image_provider_url": "https://ai.google.dev/gemini-api/docs/image-generation",
            "image_license_url": "",
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
        with patch.object(world_pulse, "_search_any_reusable_image", return_value={}) as reusable:
            with patch.object(world_pulse, "_generate_gemini_article_image", return_value=generated) as generator:
                result = world_pulse._resolve_article_image(article)
        self.assertEqual(reusable.call_count, 1)
        generator.assert_called_once_with(article)
        self.assertEqual(result["image_source"], "gemini_generated")
        self.assertEqual(result["image_url"], generated["image_url"])

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
        self.assertEqual(article["content_ar"], "ملخص الخبر")

    def test_global_publisher_catalog_is_expanded_and_language_scoped(self):
        catalog = world_pulse.CATEGORY_SOURCE_DOMAINS
        entry_count = sum(len(domains) for langs in catalog.values() for domains in langs.values())
        self.assertGreaterEqual(entry_count, 200)
        self.assertIn("voanews.com", catalog["world"]["en"])
        self.assertIn("almamlakatv.com", catalog["world"]["ar"])
        self.assertIn("eurekalert.org", catalog["science"]["en"])
        self.assertIn("true-gaming.net", catalog["gaming"]["ar"])
        self.assertEqual(
            world_pulse._source_domain_for_category("science", "en", "www.noaa.gov"),
            "noaa.gov",
        )
        self.assertEqual(
            world_pulse._source_domain_for_category("sports", "ar", "www.espn.com"),
            "",
        )

    def test_editorial_prompt_forbids_invented_details_and_generic_padding(self):
        prompt = world_pulse._build_editorial_prompt([{
            "index": 0,
            "category": "world",
            "source": "Example News",
            "source_url": "https://example.test/story",
            "headline": "Headline only",
            "rss_excerpt": "A brief excerpt",
            "source_language": "en",
        }])
        self.assertIn("Never invent or infer names, dates, places, numbers", prompt)
        self.assertIn("Do not pad the article with generic filler", prompt)
        self.assertIn("headline and RSS excerpt", prompt)

    def test_library_of_congress_image_search_accepts_only_item_level_open_rights(self):
        import io
        import json
        from unittest.mock import patch

        payload = {
            "results": [
                {
                    "title": "NASA Artemis launch",
                    "id": "https://www.loc.gov/item/example-open/",
                    "image_url": ["//cdn.loc.gov/images/artemis.jpg"],
                    "rights": ["No known restrictions on publication"],
                    "contributor": ["Library of Congress"],
                    "description": "NASA Artemis rocket launch",
                    "access_restricted": False,
                },
                {
                    "title": "NASA Artemis launch photo",
                    "id": "https://www.loc.gov/item/example-restricted/",
                    "image_url": ["//cdn.loc.gov/images/restricted.jpg"],
                    "rights": ["In copyright; permission required"],
                    "contributor": ["Restricted photographer"],
                    "description": "NASA Artemis rocket launch",
                    "access_restricted": False,
                },
            ]
        }
        fake_response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        with patch.object(world_pulse, "urlopen", return_value=fake_response):
            result = world_pulse._search_loc_open_access_image("NASA Artemis launch", "en", "science")
        self.assertEqual(result["image_source"], "loc_open_access")
        self.assertEqual(result["image_url"], "https://cdn.loc.gov/images/artemis.jpg")
        self.assertIn("example-open", result["image_license_url"])


    def test_database_errors_are_classified_without_returning_secret_details(self):
        self.assertEqual(
            world_pulse._database_error_code(
                RuntimeError("FATAL: (EMAXCONNSESSION) max clients are limited to pool_size: 15")
            ),
            "max_clients_reached",
        )
        self.assertEqual(
            world_pulse._database_error_code(
                RuntimeError("password authentication failed for user postgres")
            ),
            "authentication_failed",
        )

    def test_gemini_429_trips_circuit_breaker_and_stops_remaining_batches(self):
        from unittest.mock import MagicMock, patch

        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = RuntimeError("HTTP/1.1 429 Too Many Requests")
        articles = [
            {
                "source_url": f"https://example.test/story-{i}",
                "source_name": "Example News",
                "category": "world",
                "original_title": f"Headline {i}",
                "original_summary": f"Short source excerpt for story {i}",
                "original_language": "en",
            }
            for i in range(8)
        ]
        with patch.object(world_pulse.genai, "Client", return_value=fake_client):
            with patch.object(world_pulse, "GEMINI_API_KEY", "test-key"):
                with patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0.0):
                    with patch.object(world_pulse, "GEMINI_429_COOLDOWN_MINUTES", 60):
                        result = world_pulse._translate_batch(articles)
                        self.assertEqual(result, {})
                        self.assertEqual(fake_client.models.generate_content.call_count, 3)
                        self.assertEqual(
                            fake_client.models.generate_content.call_args_list[0].kwargs["model"],
                            world_pulse.GEMINI_MODEL,
                        )
                        self.assertEqual(
                            fake_client.models.generate_content.call_args_list[1].kwargs["model"],
                            world_pulse.GEMINI_FALLBACK_MODEL,
                        )
                        self.assertEqual(
                            fake_client.models.generate_content.call_args_list[2].kwargs["model"],
                            world_pulse.GEMINI_FALLBACK_MODEL_2,
                        )
                        self.assertGreater(world_pulse._GEMINI_RATE_LIMIT_UNTIL, world_pulse.time.monotonic())

    def test_gemini_503_or_504_trips_short_circuit_breaker_and_stops_batches(self):
        from unittest.mock import MagicMock, patch

        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = RuntimeError("HTTP/1.1 504 Gateway Timeout")
        articles = [
            {
                "source_url": f"https://example.test/server-error-{i}",
                "source_name": "Example News",
                "category": "world",
                "original_title": f"Headline {i}",
                "original_summary": f"Short source excerpt for story {i}",
                "original_language": "en",
            }
            for i in range(12)
        ]
        with patch.object(world_pulse.genai, "Client", return_value=fake_client):
            with patch.object(world_pulse, "GEMINI_API_KEY", "test-key"):
                with patch.object(world_pulse, "_GEMINI_RATE_LIMIT_UNTIL", 0.0):
                    with patch.object(world_pulse, "_GEMINI_TRANSIENT_ERROR_UNTIL", 0.0):
                        with patch.object(world_pulse, "GEMINI_TRANSIENT_ERROR_COOLDOWN_MINUTES", 10):
                            result = world_pulse._translate_batch(articles)
                            self.assertEqual(result, {})
                            # A transient 5xx advances through the configured model chain once per model, then stops.
                            self.assertEqual(fake_client.models.generate_content.call_count, 3)
                            self.assertEqual(
                                fake_client.models.generate_content.call_args_list[0].kwargs["model"],
                                world_pulse.GEMINI_MODEL,
                            )
                            self.assertEqual(
                                fake_client.models.generate_content.call_args_list[1].kwargs["model"],
                                world_pulse.GEMINI_FALLBACK_MODEL,
                            )
                            self.assertEqual(
                                fake_client.models.generate_content.call_args_list[2].kwargs["model"],
                                world_pulse.GEMINI_FALLBACK_MODEL_2,
                            )
                            self.assertGreater(
                                world_pulse._GEMINI_TRANSIENT_ERROR_UNTIL,
                                world_pulse.time.monotonic(),
                            )
        self.assertTrue(world_pulse._is_gemini_transient_server_error(RuntimeError("503 Service Unavailable")))
        self.assertTrue(world_pulse._is_gemini_transient_server_error(RuntimeError("504 Gateway Timeout")))
        self.assertFalse(world_pulse._is_gemini_transient_server_error(RuntimeError("invalid JSON")))

    def test_database_source_language_brief_remains_displayable_without_bilingual_body(self):
        from unittest.mock import patch

        article = {
            "slug": "source-only-brief",
            "source_url": "https://www.theverge.com/example-story",
            "category": "technology",
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "original_language": "en",
            "title_en": "A verified source headline",
            "summary_en": "A short source-language excerpt about the reported development.",
            "content_en": "",
            "title_ar": "",
            "summary_ar": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
        }
        with patch.object(world_pulse, "_all_live_articles", return_value=[article]):
            stories = world_pulse._get_display_stories("en")
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["title"], "A verified source headline")
        self.assertEqual(stories[0]["summary"], article["summary_en"])
        self.assertEqual(stories[0]["content"], "")

    def test_image_storage_diagnostic_saves_and_reads_without_gemini(self):
        from unittest.mock import patch

        with patch.object(world_pulse, "_store_gemini_generated_image", return_value="d" * 32) as store:
            with patch.object(
                world_pulse,
                "_read_gemini_generated_image",
                return_value=(b"diagnostic-jpeg-bytes", "image/jpeg"),
            ) as read:
                result = world_pulse._run_image_storage_probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["image_url"], "/media/generated/" + "d" * 32)
        self.assertEqual(result["mime_type"], "image/jpeg")
        store.assert_called_once()
        self.assertEqual(store.call_args.args[1], "diagnostic:world-pulse-image-storage-test")
        read.assert_called_once_with("d" * 32)

    def test_admin_monitor_login_and_dashboard_render_without_revealing_database_url(self):
        from unittest.mock import patch

        client = world_pulse.app.test_client()
        safe_db_state = {
            "state": "error",
            "error_code": "max_clients_reached",
            "checked_at": "2026-10-14T00:00:00+00:00",
            "checked_monotonic": world_pulse.time.monotonic(),
        }
        with patch.object(world_pulse, "_admin_password", return_value="test-admin-password"):
            with patch.object(world_pulse, "_probe_database", return_value=safe_db_state):
                with patch.object(world_pulse, "_database_url", return_value="postgresql://secret-user:secret-password@secret-host/db"):
                    response = client.post(
                        "/admin/login",
                        data={"password": "test-admin-password"},
                        follow_redirects=True,
                    )
        self.assertEqual(response.status_code, 200)
        self.assertIn("لوحة المراقبة".encode("utf-8"), response.data)
        self.assertIn("max_clients_reached".encode("utf-8"), response.data)
        self.assertNotIn("secret-password".encode("utf-8"), response.data)
        self.assertNotIn("secret-host".encode("utf-8"), response.data)


    def test_shared_supabase_session_url_uses_transaction_port(self):
        from unittest.mock import patch

        session_url = "postgresql://postgres.projectref@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
        with patch.dict(
            world_pulse.os.environ,
            {"SUPABASE_POOLER_URL": session_url, "DATABASE_URL": ""},
            clear=False,
        ):
            result = world_pulse._database_url()
        self.assertIn("@aws-0-ap-northeast-1.pooler.supabase.com:6543/", result)
        self.assertIn("postgres.projectref@", result)
        self.assertNotIn(":5432/", result)

    def test_supabase_other_hosts_and_already_transaction_urls_are_unchanged(self):
        from unittest.mock import patch

        direct = "postgresql://postgres@db.projectref.supabase.co:5432/postgres"
        with patch.dict(world_pulse.os.environ, {"SUPABASE_POOLER_URL": direct, "DATABASE_URL": ""}, clear=False):
            self.assertEqual(world_pulse._database_url(), direct)

        transaction = "postgresql://postgres.projectref@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
        with patch.dict(world_pulse.os.environ, {"SUPABASE_POOLER_URL": transaction, "DATABASE_URL": ""}, clear=False):
            self.assertEqual(world_pulse._database_url(), transaction)


    def test_database_url_removes_unsupported_pgbouncer_query_parameter(self):
        from unittest.mock import patch

        dsn = (
            "postgresql://postgres.projectref@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
            "?sslmode=require&pgbouncer=true&application_name=world-pulse"
        )
        with patch.dict(
            world_pulse.os.environ,
            {"SUPABASE_POOLER_URL": dsn, "DATABASE_URL": ""},
            clear=False,
        ):
            result = world_pulse._database_url()
        self.assertIn(":6543/postgres", result)
        self.assertIn("sslmode=require", result)
        self.assertIn("application_name=world-pulse", result)
        self.assertNotIn("pgbouncer", result.casefold())

    def test_database_url_removes_pgbouncer_flag_case_insensitively(self):
        from unittest.mock import patch

        dsn = (
            "postgresql://postgres.projectref@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
            "?PgBouncer=true&sslmode=require"
        )
        with patch.dict(
            world_pulse.os.environ,
            {"SUPABASE_POOLER_URL": dsn, "DATABASE_URL": ""},
            clear=False,
        ):
            result = world_pulse._database_url()
        self.assertNotIn("pgbouncer", result.casefold())
        self.assertIn("sslmode=require", result)


    def test_database_url_trims_encoded_whitespace_after_database_name(self):
        from unittest.mock import patch

        dsn = (
            "postgresql://postgres.projectref@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres%20"
            "?sslmode=require&pgbouncer=true"
        )
        with patch.dict(
            world_pulse.os.environ,
            {"SUPABASE_POOLER_URL": dsn, "DATABASE_URL": ""},
            clear=False,
        ):
            result = world_pulse._database_url()
        self.assertIn(":6543/postgres?sslmode=require", result)
        self.assertNotIn("postgres%20", result)
        self.assertNotIn("pgbouncer", result.casefold())

    def test_editorial_fallback_route_returns_topic_specific_svg(self):
        client = world_pulse.app.test_client()
        response = client.get("/media/editorial.svg?title=NASA%20Artemis%20mission&category=science&lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertIn("image/svg+xml", response.content_type)
        self.assertIn(b"<svg", response.data)
        self.assertIn(b"WORLD PULSE", response.data)
        self.assertIn(b"Artemis", response.data)

    def test_editorial_fallback_escapes_untrusted_title_markup(self):
        client = world_pulse.app.test_client()
        response = client.get("/media/editorial.svg?title=%3Cscript%3Ealert(1)%3C%2Fscript%3E&category=world")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script", response.data.lower())

    def test_cc_by_sa_image_license_has_a_correct_visible_label(self):
        self.assertEqual(
            world_pulse._image_license_label("https://creativecommons.org/licenses/by-sa/4.0/"),
            "CC BY-SA 4.0",
        )
    def test_news_template_parses_after_visual_fallback_changes(self):
        template = world_pulse.app.jinja_env.get_template("index.html")
        self.assertIsNotNone(template)



    def test_nasa_image_search_returns_relevant_preview_and_blocks_explicit_copyright(self):
        import io
        import json
        from unittest.mock import patch

        payload = {
            "collection": {
                "items": [
                    {
                        "data": [{
                            "title": "Artemis lunar rocket launch",
                            "description": "NASA Artemis lunar mission rocket launch photography",
                            "keywords": [{"name": "Artemis"}, {"name": "Moon"}],
                            "nasa_id": "KSC-ARTEMIS-TEST",
                            "center": "KSC",
                            "photographer": "NASA/KSC",
                        }],
                        "links": [{
                            "rel": "preview",
                            "href": "https://images-assets.nasa.gov/image/KSC-ARTEMIS-TEST/KSC-ARTEMIS-TEST~thumb.jpg",
                        }],
                    },
                    {
                        "data": [{
                            "title": "Artemis lunar rocket launch photo",
                            "description": "NASA Artemis lunar mission rocket launch",
                            "nasa_id": "KSC-RESTRICTED-TEST",
                            "copyright": "Third-party copyrighted image; permission required",
                        }],
                        "links": [{
                            "rel": "preview",
                            "href": "https://images-assets.nasa.gov/image/KSC-RESTRICTED-TEST/KSC-RESTRICTED-TEST~thumb.jpg",
                        }],
                    },
                ]
            }
        }
        with patch.object(world_pulse, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode("utf-8"))):
            result = world_pulse._search_nasa_image("NASA Artemis lunar rocket launch", "en", "science")
        self.assertEqual(result["image_source"], "nasa_images")
        self.assertEqual(
            result["image_url"],
            "https://images-assets.nasa.gov/image/KSC-ARTEMIS-TEST/KSC-ARTEMIS-TEST~thumb.jpg",
        )
        self.assertIn("KSC-ARTEMIS-TEST", result["image_provider_url"])
        self.assertIn("nasa.gov", result["image_license_url"])

    def test_nasa_image_search_skips_irrelevant_categories_without_network_access(self):
        from unittest.mock import patch

        with patch.object(world_pulse, "urlopen", side_effect=AssertionError("network must not be called")):
            result = world_pulse._search_nasa_image("Election results", "en", "politics")
        self.assertEqual(result, {})

    def test_commons_cc_by_sa_photo_is_allowed_with_creator_attribution(self):
        import io
        import json
        from unittest.mock import patch

        page = {
            "title": "File:NASA Artemis moon rocket launch.jpg",
            "imageinfo": [{
                "mime": "image/jpeg",
                "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/test.jpg",
                "url": "https://upload.wikimedia.org/wikipedia/commons/test.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                    "Artist": {"value": "Example photographer"},
                    "ImageDescription": {"value": "NASA Artemis lunar rocket launch"},
                },
            }],
        }
        payload = {"query": {"pages": [page]}}
        raw = json.dumps(payload).encode("utf-8")
        with patch.object(world_pulse, "urlopen", return_value=io.BytesIO(raw)) as mock_urlopen:
            result = world_pulse._search_commons_image("NASA Artemis lunar rocket launch", "en", "science")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertIn("gsrsearch=NASA", mock_urlopen.call_args.args[0].full_url)
        self.assertEqual(result["image_source"], "wikimedia_relevant")
        self.assertEqual(result["image_credit"], "Example photographer")
        self.assertIn("by-sa/4.0", result["image_license_url"])

    def test_stock_image_apis_are_removed_from_runtime(self):
        self.assertFalse(hasattr(world_pulse, "_search_pexels_image"))
        self.assertFalse(hasattr(world_pulse, "_search_unsplash_image"))
        self.assertFalse(hasattr(world_pulse, "PEXELS_API_KEY"))
        self.assertFalse(hasattr(world_pulse, "UNSPLASH_ACCESS_KEY"))
        self.assertNotIn("pexels_api", world_pulse.TRUSTED_REUSABLE_IMAGE_SOURCES)
        self.assertNotIn("unsplash_api", world_pulse.TRUSTED_REUSABLE_IMAGE_SOURCES)
        source = __import__("inspect").getsource(world_pulse._search_any_reusable_image)
        self.assertNotIn("_search_pexels_image(", source)
        self.assertNotIn("_search_unsplash_image(", source)

    def test_openverse_license_policy_only_accepts_commercially_reusable_cc_licenses(self):
        self.assertTrue(world_pulse._openverse_license_url_ok("cc0", "https://creativecommons.org/publicdomain/zero/1.0/"))
        self.assertTrue(world_pulse._openverse_license_url_ok("pdm", "https://creativecommons.org/publicdomain/mark/1.0/"))
        self.assertTrue(world_pulse._openverse_license_url_ok("by", "https://creativecommons.org/licenses/by/4.0/"))
        self.assertTrue(world_pulse._openverse_license_url_ok("by-sa", "https://creativecommons.org/licenses/by-sa/4.0/"))
        self.assertFalse(world_pulse._openverse_license_url_ok("by-nc", "https://creativecommons.org/licenses/by-nc/4.0/"))
        self.assertFalse(world_pulse._openverse_license_url_ok("by-nd", "https://creativecommons.org/licenses/by-nd/4.0/"))
        self.assertFalse(world_pulse._openverse_license_url_ok("cc0", "http://creativecommons.org/publicdomain/zero/1.0/"))
        self.assertFalse(world_pulse._openverse_license_url_ok("cc0", "https://example.test/publicdomain/zero/1.0/"))

    def test_openverse_search_returns_image_with_creator_source_and_license(self):
        import io
        import json
        from unittest.mock import patch

        payload = {
            "results": [
                {
                    "id": "image-cc-by-sa",
                    "title": "NASA Artemis lunar rocket launch",
                    "url": "https://images.example.test/artemis-rocket.jpg",
                    "foreign_landing_url": "https://commons.example.test/artemis",
                    "creator": "Example photographer",
                    "creator_url": "https://commons.example.test/photographer",
                    "license": "by-sa",
                    "license_version": "4.0",
                    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                    "width": 1600,
                    "height": 900,
                    "mature": False,
                    "tags": [{"name": "NASA"}, {"name": "Artemis"}, {"name": "lunar"}],
                },
                {
                    "id": "image-nc",
                    "title": "NASA Artemis lunar rocket launch",
                    "url": "https://images.example.test/unapproved.jpg",
                    "foreign_landing_url": "https://commons.example.test/unapproved",
                    "creator": "Example photographer",
                    "license": "by-nc",
                    "license_version": "4.0",
                    "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                    "width": 1600,
                    "height": 900,
                    "mature": False,
                    "tags": [{"name": "NASA"}, {"name": "Artemis"}, {"name": "lunar"}],
                },
            ]
        }
        with patch.object(
            world_pulse,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode("utf-8")),
        ) as mock_open:
            result = world_pulse._search_openverse_image("NASA Artemis lunar rocket launch", "en", "science")
        self.assertEqual(result["image_source"], "openverse_licensed")
        self.assertEqual(result["image_credit"], "Example photographer")
        self.assertEqual(result["image_provider_url"], "https://commons.example.test/artemis")
        self.assertEqual(result["image_license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
        request = mock_open.call_args.args[0]
        self.assertIn("license=cc0%2Cpdm%2Cby%2Cby-sa", request.full_url)
        self.assertIn("license_type=commercial", request.full_url)
        self.assertIn("/v1/images/image-cc-by-sa/thumb/", result["image_cache_url"])
        self.assertIn("full_size=true&compressed=true", result["image_cache_url"])

    def test_active_image_search_uses_openverse_without_unsplash_or_pexels_keys(self):
        from unittest.mock import patch

        openverse_result = {
            "image_url": "https://images.example.test/licensed.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Creator",
            "image_provider_url": "https://openverse.example.test/item",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        with patch.object(world_pulse, "_control_enabled", return_value=True):
            with patch.object(world_pulse, "_search_commons_image", return_value={}):
                with patch.object(world_pulse, "_search_openverse_image", return_value=openverse_result) as openverse:
                    with patch.object(world_pulse, "_search_loc_open_access_image", side_effect=AssertionError("Openverse result should win")):
                        with patch.object(world_pulse, "_search_nasa_image", side_effect=AssertionError("Openverse result should win")):
                            with patch.object(world_pulse, "_search_approved_presskit_image", side_effect=AssertionError("Openverse result should win")):
                                result = world_pulse._search_any_reusable_image("NASA Artemis lunar rocket launch", "en", "science")
        self.assertEqual(result, openverse_result)
        openverse.assert_called_once()


    def test_unverified_external_image_is_not_shown_without_item_level_licence(self):
        row = {
            "slug": "unverified-image",
            "source_url": "https://example.test/story",
            "category": "world",
            "source_name": "Example",
            "source_domain": "example.test",
            "original_language": "ar",
            "title_ar": "عنوان الخبر",
            "title_en": "",
            "summary_ar": "ملخص الخبر",
            "summary_en": "",
            "content_ar": "",
            "content_en": "",
            "image_url": "https://images.example.test/photo.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Unknown creator",
            "image_credit_url": "",
            "image_provider_url": "https://example.test/photo",
            "image_license_url": "",
        }
        story = world_pulse._normalise_story(row, "ar")
        self.assertEqual(story["image_url"], "/static/A.jpg")
        self.assertEqual(story["image_source"], "fallback_ar")
        self.assertEqual(story["image_credit"], "")
        self.assertEqual(story["image_license_url"], "")


    def test_cached_catalogued_image_url_passes_only_with_item_license_metadata(self):
        good = {
            "image_url": "/media/catalogued/" + "a" * 40,
            "image_source": "openverse_licensed",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
        self.assertTrue(world_pulse._image_license_verified(good))
        self.assertFalse(world_pulse._image_license_verified(dict(good, image_source="unknown_provider")))
        self.assertFalse(world_pulse._image_license_verified(dict(good, image_license_url="")))
        self.assertFalse(world_pulse._image_license_verified(dict(good, image_url="/media/catalogued/not-a-hash")))

    def test_backfill_query_includes_legacy_A_E_and_stopped_api_rows(self):
        from unittest.mock import MagicMock, patch

        fake_connection = MagicMock()
        fake_cursor = fake_connection.cursor.return_value.__enter__.return_value
        fake_cursor.fetchall.return_value = []
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=fake_connection):
                with patch.object(world_pulse, "_release_db_connection"):
                    world_pulse._db_fetch_articles_needing_images(24)
        query = fake_cursor.execute.call_args.args[0]
        self.assertIn("fallback_ar", query)
        self.assertIn("fallback_en", query)
        self.assertIn("pexels_api", query)
        self.assertIn("unsplash_api", query)
        self.assertIn("/static/A.jpg", query)
        self.assertIn("/static/E.jpg", query)

    def test_licensed_photo_is_optimized_and_cached_to_supabase(self):
        import io
        from unittest.mock import MagicMock, patch
        from PIL import Image

        image_buffer = io.BytesIO()
        Image.new("RGB", (1800, 1000), "#5d7a9b").save(image_buffer, format="PNG")
        source_bytes = image_buffer.getvalue()

        fake_connection = MagicMock()
        fake_cursor = fake_connection.cursor.return_value.__enter__.return_value
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = source_bytes
        candidate = {
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/test.png",
            "image_source": "wikimedia_relevant",
            "image_credit": "Example photographer",
            "image_credit_url": "https://commons.wikimedia.org/wiki/File:Test.png",
            "image_provider_url": "https://commons.wikimedia.org/wiki/File:Test.png",
            "image_license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        }

        with patch.object(world_pulse, "_image_license_verified", return_value=True):
            with patch.object(world_pulse, "_catalogued_image_exists", return_value=False):
                with patch.object(world_pulse, "_ensure_schema", return_value=True):
                    with patch.object(world_pulse, "_connect_db", return_value=fake_connection):
                        with patch.object(world_pulse, "_release_db_connection"):
                            with patch.object(world_pulse, "urlopen", return_value=response_context):
                                cached = world_pulse._cache_reusable_image(dict(candidate))

        self.assertTrue(cached["image_url"].startswith("/media/catalogued/"))
        self.assertEqual(cached["image_source"], "wikimedia_relevant")
        self.assertEqual(cached["image_license_url"], candidate["image_license_url"])
        fake_connection.commit.assert_called_once()
        sql, params = fake_cursor.execute.call_args.args
        self.assertIn("INSERT INTO world_pulse_catalogued_images", sql)
        self.assertEqual(params[2], "image/jpeg")
        self.assertLess(len(params[3]), 2 * 1024 * 1024)
        with Image.open(io.BytesIO(params[3])) as stored:
            self.assertEqual(stored.format, "JPEG")
            self.assertLessEqual(stored.width, 1600)
            self.assertLessEqual(stored.height, 1200)

    def test_catalogued_image_route_serves_persisted_bytes_and_cache_headers(self):
        from unittest.mock import patch

        client = world_pulse.app.test_client()
        with patch.object(world_pulse, "_read_catalogued_image", return_value=(b"fake-webp-image-bytes", "image/webp")):
            response = client.get("/media/catalogued/" + "a" * 40)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/webp")
        self.assertEqual(response.data, b"fake-webp-image-bytes")
        self.assertIn("immutable", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
