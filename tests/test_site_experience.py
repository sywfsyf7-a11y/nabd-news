"""Regression tests for fast article navigation and distinct editorial fields."""
import unittest
import os
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

import app as world_pulse


class SiteExperienceTests(unittest.TestCase):
    def setUp(self):
        self._display_cache_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._display_cache_temp.cleanup)
        cache_path = os.path.join(self._display_cache_temp.name, "display-cache.json")
        patcher = patch.object(world_pulse, "_DISPLAY_SHARED_CACHE_PATH", cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        with world_pulse._DISPLAY_STORIES_CACHE_LOCK:
            world_pulse._DISPLAY_STORIES_CACHE.clear()
        with world_pulse._DISPLAY_STORIES_REFRESHING_LOCK:
            world_pulse._DISPLAY_STORIES_REFRESHING.clear()

    def test_in_process_article_working_set_is_bounded_and_keeps_recent_stories(self):
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        rows = [
            {
                "source_url": f"https://example.com/memory-{index}",
                "published_at": base + timedelta(days=index),
                "fetched_at": base + timedelta(days=index),
            }
            for index in range(7)
        ]
        with patch.object(world_pulse, "MAX_MEMORY_ARTICLES", 3):
            with patch.object(world_pulse, "_MEMORY_ARTICLES", {}):
                world_pulse._remember_articles(rows)
                memory = world_pulse._MEMORY_ARTICLES
                self.assertEqual(len(memory), 3)
                self.assertEqual(
                    set(memory),
                    {f"https://example.com/memory-{index}" for index in (4, 5, 6)},
                )

    def test_homepage_hides_manual_refresh_and_status_ui_but_keeps_compiled_css(self):
        template_path = os.path.join(os.path.dirname(world_pulse.__file__), "templates", "index.html")
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()
        self.assertNotIn('id="refreshNews"', template)
        self.assertNotIn('id="newsStatusText"', template)
        self.assertNotIn("/api/news-status", template)
        self.assertNotIn("/api/refresh", template)
        self.assertIn("filename='css/site.css'", template)
        self.assertNotIn("cdn.tailwindcss.com", template)
        self.assertNotIn('<img src="{{ story.image_fallback_url }}"', template)
        self.assertNotIn('<img src="{{ article.image_fallback_url }}"', template)
        self.assertEqual(template.count("data-fallback-src="), 3)
        self.assertNotIn("English edition", template)
        self.assertNotIn("article.slug, lang='ar'", template)
        self.assertIn("story.original_language", template)
        self.assertEqual(world_pulse.NEWS_REFRESH_MINUTES, 5)
        self.assertEqual(world_pulse.NEWS_DISCOVERY_REFRESH_MINUTES, 15)
        self.assertEqual(world_pulse.MAX_ARTICLES_PER_REFRESH, 1)
        self.assertIn("الأخبار تتجدد باستمرار", world_pulse.UI_TEXT["ar"]["live"])
        self.assertIn("Continuously updated", world_pulse.UI_TEXT["en"]["live"])
        tailwind_config_path = os.path.join(os.path.dirname(world_pulse.__file__), "tailwind.config.js")
        self.assertTrue(os.path.exists(tailwind_config_path))

    def test_persistent_news_queue_serialises_metadata_without_losing_native_language(self):
        item = {
            "slug": "queue-story",
            "source_url": "https://saudigamer.com/story",
            "category": "gaming",
            "source_name": "Saudi Gamer",
            "source_domain": "saudigamer.com",
            "original_title": "عنوان من سعودي جيمر",
            "original_summary": "مقتطف قصير من المصدر",
            "published_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
            "original_language": "ar",
            "headline_only": False,
            "image_url": "https://not-needed.example/photo.jpg",
            "content_en": "This body is intentionally not part of the pending queue.",
        }
        stored = world_pulse._serialise_news_queue_item(item)
        restored = world_pulse._deserialise_news_queue_item(stored)
        self.assertEqual(restored["source_url"], item["source_url"])
        self.assertEqual(restored["original_language"], "ar")
        self.assertEqual(restored["category"], "gaming")
        self.assertEqual(restored["published_at"], item["published_at"])
        self.assertNotIn("image_url", stored)
        self.assertNotIn("content_en", stored)

    def test_persistent_news_discovery_interval_is_separate_from_publish_interval(self):
        now = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)
        state = {"discovered_at": (now - timedelta(minutes=14)).isoformat(), "items": []}
        with patch.object(world_pulse, "NEWS_DISCOVERY_REFRESH_MINUTES", 15):
            self.assertFalse(world_pulse._news_queue_discovery_due(state, now))
            self.assertTrue(world_pulse._news_queue_discovery_due(
                {"discovered_at": (now - timedelta(minutes=16)).isoformat(), "items": []}, now
            ))

    def test_category_source_allowlists_match_the_curated_arabic_and_english_publishers(self):
        expected = {
            "politics": {
                "ar": {"aljazeera.net", "alarabiya.net", "skynewsarabia.com", "aawsat.com", "alquds.co.uk", "wam.ae", "spa.gov.sa"},
                "en": {"bbc.com", "reuters.com", "apnews.com", "politico.com", "theguardian.com"},
            },
            "economy": {
                "ar": {"asharqbusiness.com", "cnbcarabia.com", "mubasher.info", "argaam.com"},
                "en": {"bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "marketwatch.com"},
            },
            "technology": {
                "ar": {"aitnews.com", "tech-wd.com", "arabhardware.net"},
                "en": {"theverge.com", "techcrunch.com", "wired.com", "arstechnica.com"},
            },
            "gaming": {
                "ar": {"saudigamer.com", "arabhardware.net"},
                "en": {"ign.com", "gamespot.com", "polygon.com", "eurogamer.net", "kotaku.com"},
            },
            "sports": {
                "ar": {"filgoal.com", "kooora.com", "beinsports.com", "yallakora.com"},
                "en": {"bbc.com", "espn.com", "skysports.com", "theathletic.com"},
            },
            "science": {
                "ar": {"nationalgeographic.com", "aljazeera.net"},
                "en": {"nasa.gov", "jpl.nasa.gov", "space.com", "livescience.com", "scientificamerican.com", "nature.com"},
            },
            "culture": {
                "ar": {"alaraby.co.uk", "alarab.co.uk"},
                "en": {"lithub.com", "artsy.net", "theguardian.com", "newyorker.com"},
            },
            "world": {
                "ar": {"bbc.com", "france24.com", "dw.com"},
                "en": {"bbc.com", "euronews.com", "apnews.com", "cnn.com"},
            },
        }
        actual = {
            category: {lang: set(domains) for lang, domains in languages.items()}
            for category, languages in world_pulse.CATEGORY_SOURCE_DOMAINS.items()
        }
        self.assertEqual(actual, expected)
        self.assertNotIn("npr.org", {d for langs in actual.values() for domains in langs.values() for d in domains})
        self.assertNotIn("cnn.com", actual["politics"]["ar"])
        self.assertNotIn("ign.com", actual["gaming"]["ar"])

    def test_art_institute_catalog_is_culture_only_and_requires_public_domain_records(self):
        import json
        from unittest.mock import MagicMock

        with patch.object(world_pulse, "urlopen") as network:
            self.assertEqual(world_pulse._search_art_institute_image(
                "Ancient Roman theatre exhibition", category="world"
            ), {})
            network.assert_not_called()

        response_data = {
            "data": [
                {
                    "id": 123,
                    "title": "Ancient Roman theatre exhibition",
                    "image_id": "a1b2c3d4",
                    "artist_title": "Museum collection",
                    "description": "An ancient Roman theatre exhibition.",
                    "date_display": "Ancient Rome",
                    "is_public_domain": True,
                },
                {
                    "id": 456,
                    "title": "Ancient Roman theatre exhibition copyrighted",
                    "image_id": "restricted-image",
                    "is_public_domain": False,
                },
            ]
        }
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(response_data).encode("utf-8")
        with patch.object(world_pulse, "urlopen", return_value=response):
            result = world_pulse._search_art_institute_image(
                "Ancient Roman theatre exhibition", category="culture"
            )
        self.assertEqual(result["image_source"], "artic_open_access")
        self.assertIn("/a1b2c3d4/", result["image_url"])
        self.assertEqual(result["image_license_url"], "https://creativecommons.org/publicdomain/zero/1.0/")
        self.assertIn("Art Institute of Chicago", result["image_credit"])

    def test_met_catalog_is_culture_only_and_rechecks_item_public_domain_flag(self):
        import json

        class FakeResponse:
            def __init__(self, value):
                self.value = value
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self, limit):
                return json.dumps(self.value).encode("utf-8")

        with patch.object(world_pulse, "urlopen") as network:
            self.assertEqual(world_pulse._search_met_open_access_image(
                "Ancient Roman theatre exhibition", category="technology"
            ), {})
            network.assert_not_called()

        def fake_urlopen(request, timeout):
            if "/v1.1/search?" in request.full_url:
                return FakeResponse({"objectIDs": [123]})
            return FakeResponse({
                "objectID": 123,
                "isPublicDomain": True,
                "primaryImage": "https://images.metmuseum.org/CRDImages/aa/original/test.jpg",
                "title": "Ancient Roman theatre exhibition",
                "artistDisplayName": "Museum collection",
                "objectName": "Sculpture",
                "culture": "Roman",
                "objectURL": "https://www.metmuseum.org/art/collection/search/123",
            })

        with patch.object(world_pulse, "urlopen", side_effect=fake_urlopen):
            result = world_pulse._search_met_open_access_image(
                "Ancient Roman theatre exhibition", category="culture"
            )
        self.assertEqual(result["image_source"], "met_open_access")
        self.assertEqual(result["image_url"], "https://images.metmuseum.org/CRDImages/aa/original/test.jpg")
        self.assertEqual(result["image_license_url"], "https://creativecommons.org/publicdomain/zero/1.0/")
        self.assertEqual(result["image_provider_url"], "https://www.metmuseum.org/art/collection/search/123")

    def test_native_language_story_stays_on_native_interface_without_translation(self):
        row = {
            "slug": "native-language-fallback",
            "source_url": "https://saudigamer.com/story",
            "source_name": "Saudi Gamer",
            "source_domain": "saudigamer.com",
            "category": "gaming",
            "original_language": "ar",
            "title_ar": "عنوان الخبر من سعودي جيمر",
            "title_en": "",
            "summary_ar": "ملخص عربي قصير عن الخبر.",
            "summary_en": "",
            "content_ar": "تفاصيل المصدر المتاحة عن الخبر تبقى في لغتها الأصلية.",
            "content_en": "",
            "image_url": "",
            "image_source": "none",
            "image_credit": "",
            "image_credit_url": "",
            "image_provider_url": "",
            "image_license_url": "",
        }
        story = world_pulse._normalise_story(row, "ar")
        self.assertEqual(story["title"], "عنوان الخبر من سعودي جيمر")
        self.assertEqual(story["display_language"], "ar")
        self.assertEqual(story["summary"], "ملخص عربي قصير عن الخبر.")
        self.assertTrue(world_pulse._row_allowed_on_language_site(row, "ar"))
        self.assertTrue(world_pulse._row_allowed_on_language_site(row, "en"))
        english_view = world_pulse._normalise_story(dict(row), "en")
        self.assertEqual(english_view["display_language"], "ar")
        self.assertTrue(english_view["translation_fallback"])

    def test_old_cross_language_bookmark_redirects_to_allowlisted_source_if_translation_is_missing(self):
        source_url = "https://www.theverge.com/2026/10/16/example-story"
        stored = {
            "slug": "old-international-story",
            "source_url": source_url,
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "category": "technology",
            "original_language": "en",
            "title_en": "An English-only technology headline",
            "title_ar": "",
            "summary_en": "A source-language summary for the archived story.",
            "summary_ar": "",
            "content_en": "A substantive English article body for the archived story, without an Arabic translation.",
            "content_ar": "",
        }
        from unittest.mock import patch
        with patch.object(world_pulse, "current_language", return_value="ar"):
            with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=stored):
                    response = world_pulse.app.test_client().get("/article/old-international-story?lang=ar")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), source_url)

    def test_headline_only_article_stays_native_language_and_is_not_translated(self):
        row = {
            "slug": "aljazeera-headline",
            "source_url": "https://www.aljazeera.net/news/world/example",
            "source_name": "Al Jazeera",
            "source_domain": "aljazeera.net",
            "category": "politics",
            "original_language": "ar",
            "title_ar": "عنوان عربي من الجزيرة",
            "title_en": "",
            "summary_ar": "يعرض نبض العالم العنوان ورابط الناشر فقط لهذا المصدر. افتح المصدر الأصلي لقراءة التفاصيل والسياق وآخر التحديثات.",
            "summary_en": "",
            "content_ar": "",
            "content_en": "",
            "image_url": "",
            "image_source": "none",
            "image_credit": "",
            "image_credit_url": "",
            "image_provider_url": "",
            "image_license_url": "",
        }
        story = world_pulse._normalise_story(row, "ar")
        self.assertEqual(story["title"], row["title_ar"])
        self.assertEqual(story["display_language"], "ar")
        self.assertEqual(story["content"], "")
        self.assertTrue(story["headline_only"])
        self.assertTrue(world_pulse._row_allowed_on_language_site(row, "ar"))
        self.assertTrue(world_pulse._row_allowed_on_language_site(row, "en"))
        english_view = world_pulse._normalise_story(dict(row), "en")
        self.assertEqual(english_view["display_language"], "ar")
        self.assertTrue(english_view["headline_only"])
        self.assertEqual(english_view["content"], "")

    def test_rss_excerpt_is_displayed_as_details_when_editorial_ai_is_unavailable(self):
        excerpt = (
            "The city council approved the transit plan after a public vote. "
            "The first phase will add three bus routes, according to the council's release."
        )
        raw = world_pulse._base_article({
            "slug": "rss-details-fallback",
            "source_url": "https://example.com/transit-plan",
            "category": "world",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": "City council approves transit plan",
            "original_summary": excerpt,
            "original_language": "en",
            "published_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
        })

        story = world_pulse._normalise_story(raw, "en")

        self.assertEqual(raw["content_en"], excerpt)
        self.assertTrue(story["content"])
        self.assertIn("three bus routes", story["content"])
        self.assertTrue(story["details_from_source_excerpt"])

    def test_single_sentence_excerpt_is_not_silently_hidden_as_details(self):
        excerpt = "The city council approved the plan after a public vote."
        raw = world_pulse._base_article({
            "slug": "single-sentence-details",
            "source_url": "https://example.com/one-sentence",
            "category": "world",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": "City council approves plan",
            "original_summary": excerpt,
            "original_language": "en",
            "published_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
        })

        story = world_pulse._normalise_story(raw, "en")

        self.assertTrue(story["content"])
        self.assertIn("public vote", story["content"])
        self.assertTrue(story["details_from_source_excerpt"])


    def test_missing_photo_uses_local_topic_art_fallback(self):
        published = datetime(2026, 10, 15, tzinfo=timezone.utc)
        common = {
            "slug": "fallback-story",
            "source_url": "https://example.com/fallback-story",
            "category": "world",
            "source_name": "Example publisher",
            "source_domain": "example.com",
            "title_en": "An example international story",
            "title_ar": "خبر دولي تجريبي",
            "summary_en": "A distinct English summary from the available source excerpt.",
            "summary_ar": "ملخص عربي مستقل من المقتطف المتاح للمصدر.",
            "content_en": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "published_at": published,
        }

        english = world_pulse._normalise_story(dict(common, original_language="en"), "en")
        arabic = world_pulse._normalise_story(dict(common, original_language="ar"), "ar")

        for story in (english, arabic):
            self.assertTrue(story["image_url"].startswith("/media/editorial.svg?"))
            self.assertEqual(story["image_url"], story["image_fallback_url"])
            self.assertIn("category=world", story["image_url"])
            self.assertEqual(story["image_source"], "editorial_generated")
        self.assertIn("lang=en", english["image_url"])
        self.assertIn("lang=ar", arabic["image_url"])


    def test_long_headline_is_shortened_and_duplicate_summary_is_repaired(self):
        headline = (
            "Government announces a major new energy support plan for households as "
            "fuel prices continue rising across several regions"
        )
        row = {
            "slug": "story-long-title",
            "source_url": "https://www.cnn.com/example-story",
            "category": "world",
            "source_name": "CNN",
            "source_domain": "cnn.com",
            "original_language": "en",
            "title_en": headline,
            "title_ar": "",
            "summary_en": headline,
            "summary_ar": "",
            "content_en": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertLessEqual(len(story["title"]), 92)
        self.assertTrue(story["title"].endswith("…"))
        self.assertFalse(world_pulse._summary_repeats_title(headline, story["summary"]))
        self.assertIn("original publisher", story["summary"])

    def test_distinct_details_can_be_used_as_summary_when_headline_and_summary_match(self):
        headline = "Central bank announces a new interest-rate decision"
        detail = (
            "The central bank said its policy committee voted to hold the benchmark rate. "
            "Officials said the next decision will depend on incoming inflation and employment data."
        )
        row = {
            "slug": "story-summary-details",
            "source_url": "https://www.cnn.com/example-story",
            "category": "economy",
            "source_name": "CNN",
            "source_domain": "cnn.com",
            "original_language": "en",
            "title_en": headline,
            "title_ar": "",
            "summary_en": headline,
            "summary_ar": "",
            "content_en": detail,
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertIn("central bank said", story["summary"].casefold())
        self.assertNotEqual(story["title"], story["summary"])
        self.assertTrue(story["content"])

    def test_category_photo_query_uses_topic_anchors_and_section_terms(self):
        cases = (
            ("technology", "New laptop chip launched", "computer technology circuit board"),
            ("gaming", "New console game release", "video game console controller gaming setup"),
            ("sports", "Football final match announced", "sports stadium football basketball athletes"),
            ("science", "Telescope discovers distant planet", "science laboratory telescope microscope astronomy"),
            ("culture", "New art exhibition opens", "art museum painting sculpture cultural heritage"),
        )
        for category, title, expected_terms in cases:
            with self.subTest(category=category):
                query = world_pulse._category_image_search_query(title, "", category).casefold()
                self.assertTrue(query)
                for term in expected_terms.split():
                    self.assertIn(term, query)
                self.assertTrue(any(token in query for token in title.casefold().split() if len(token) > 2))

    def test_category_fallback_photo_is_labelled_illustrative_and_keeps_credit(self):
        candidate = {
            "image_url": "https://images.example.test/category.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Photographer Name",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_title": "Gaming setup with a controller",
            "_image_relevance_evidence": "Video game hardware console controller setup for gaming",
            "_image_relevance_score": 0.31,
        }
        with patch.object(world_pulse, "_image_search_query_variants", return_value=["specific story", "category query"]):
            with patch.object(world_pulse, "_category_image_search_query", return_value="category query"):
                with patch.object(world_pulse, "_search_any_reusable_image", side_effect=[{}, dict(candidate)]):
                    result = world_pulse._search_article_image_with_variants(
                        "New video game hardware", "", "en", "gaming"
                    )
        self.assertIn("illustrative category image", result["image_credit"])
        self.assertIn("Photographer Name", result["image_credit"])
        self.assertEqual(result["image_license_url"], candidate["image_license_url"])

    def test_article_route_reuses_warm_display_pool_without_database_scan(self):
        stories = [
            {"slug": "story-one", "category": "technology", "title": "Short title"},
            {"slug": "story-two", "category": "technology", "title": "Related story"},
        ]
        warm_cache = {"en": (time.monotonic(), stories)}
        with patch.object(world_pulse, "_ensure_background_scheduler"):
            with patch.object(world_pulse, "current_language", return_value="en"):
                with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", warm_cache):
                    with patch.object(world_pulse, "_db_fetch_article_by_slug", side_effect=AssertionError("warm cache should win")):
                        with patch.object(world_pulse, "render_template", return_value="article rendered"):
                            response = world_pulse.app.test_client().get("/article/story-one?lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "article rendered")

    def test_source_control_cache_primes_all_known_toggles_with_one_database_query(self):
        class FakeCursor:
            def __init__(self):
                self.query = None
                self.params = None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params=None):
                self.query, self.params = query, params
            def fetchall(self):
                return [
                    ("news:world:ar:bbc.com", False),
                    ("image:openverse_licensed", False),
                ]

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.closed = False
            def cursor(self):
                return self.cursor_instance
            def close(self):
                self.closed = True

        old_cache = dict(world_pulse._CONTROL_CACHE)
        connection = FakeConnection()
        try:
            with world_pulse._CONTROL_CACHE_LOCK:
                world_pulse._CONTROL_CACHE.clear()
            with patch.object(world_pulse, "_ensure_schema", return_value=True):
                with patch.object(world_pulse, "_connect_db", return_value=connection) as connect:
                    self.assertTrue(world_pulse._prime_source_control_cache())
                    self.assertFalse(world_pulse._control_enabled("news:world:ar:bbc.com"))
                    self.assertFalse(world_pulse._control_enabled("image:openverse_licensed"))
                    # An unset source retains the current default-on behavior.
                    self.assertTrue(world_pulse._control_enabled("news:world:ar:france24.com"))
            connect.assert_called_once()
            self.assertIn("SELECT control_key, enabled FROM world_pulse_controls", connection.cursor_instance.query)
            self.assertTrue(connection.closed)
        finally:
            with world_pulse._CONTROL_CACHE_LOCK:
                world_pulse._CONTROL_CACHE.clear()
                world_pulse._CONTROL_CACHE.update(old_cache)

    def test_rss_batch_timeout_keeps_completed_feed_results_without_waiting_for_pending_feeds(self):
        story = {
            "slug": "stalled-feed-story",
            "source_url": "https://example.com/stalled-feed-story",
            "original_title": "A completed feed returned this headline",
            "original_summary": "A short source excerpt.",
            "original_language": "en",
            "source_domain": "example.com",
            "source_name": "Example",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }

        class FakeFuture:
            def __init__(self, result=None, is_done=False):
                self._result = result
                self._done = is_done
                self._cancelled = False
            def done(self):
                return self._done
            def result(self):
                if not self._done:
                    raise AssertionError("pending future must not be awaited")
                return self._result
            def cancel(self):
                self._cancelled = True
                return True
            def cancelled(self):
                return self._cancelled

        class FakeExecutor:
            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.futures = []
                self.shutdown_args = None
            def submit(self, fn, category, lang, source_group=()):
                if category == "world" and lang == "en":
                    future = FakeFuture(("world", "en", [dict(story)]), is_done=True)
                else:
                    future = FakeFuture(is_done=False)
                self.futures.append(future)
                return future
            def shutdown(self, wait, cancel_futures):
                self.shutdown_args = (wait, cancel_futures)

        executor = FakeExecutor(max_workers=20)

        def timed_out_as_completed(futures, timeout):
            yield next(future for future in futures if future.done())
            raise TimeoutError()

        with patch.object(world_pulse, "_prime_source_control_cache", return_value=True):
            with patch.object(world_pulse, "ThreadPoolExecutor", return_value=executor):
                with patch.object(world_pulse, "as_completed", side_effect=timed_out_as_completed):
                    with patch.object(world_pulse, "_classify_story", return_value="world"):
                        with patch.object(world_pulse, "_source_domain_for_category", return_value="example.com"):
                            with patch.object(world_pulse, "_stories_are_near_duplicates", return_value=False):
                                stories = world_pulse._collect_rss_articles()

        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source_url"], story["source_url"])
        self.assertEqual(executor.shutdown_args, (False, True))
        self.assertTrue(all(future.cancelled() for future in executor.futures if not future.done()))

    def test_generic_feed_section_headlines_are_rejected_but_real_headlines_pass(self):
        self.assertTrue(world_pulse._looks_like_feed_section_title("Latest Nintendo Life News", "Nintendo Life"))
        self.assertTrue(world_pulse._looks_like_feed_section_title("مستجدات التكنولوجيا", ""))
        self.assertTrue(world_pulse._looks_like_feed_section_title("New York - The Guardian", "The Guardian"))
        self.assertTrue(world_pulse._looks_like_feed_section_title(
            "Breaking News, World News and Video from Al Jazeera - Al Jazeera", "Al Jazeera"
        ))
        self.assertTrue(world_pulse._looks_like_feed_section_title(
            "آخر الأخبار العربية والدولية - الجزيرة نت", "الجزيرة نت"
        ))
        self.assertFalse(world_pulse._looks_like_feed_section_title(
            "World News and Video: Negotiators begin new ceasefire talks in Cairo", "Al Jazeera"
        ))
        self.assertFalse(
            world_pulse._looks_like_feed_section_title(
                "Nintendo announces a new console and release window", "Nintendo Life"
            )
        )
        self.assertFalse(
            world_pulse._looks_like_feed_section_title(
                "New York transit authority announces a subway plan", "The Guardian"
            )
        )

    def test_google_news_rss_parser_skips_a_section_label_but_keeps_a_real_story(self):
        from io import BytesIO

        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Google News</title>
          <item>
            <title>Latest Nintendo Life News</title>
            <link>https://www.nintendolife.com/news</link>
            <source url="https://www.nintendolife.com/">Nintendo Life</source>
          </item>
          <item>
            <title>Breaking News, World News and Video from Nintendo Life - Nintendo Life</title>
            <link>https://www.nintendolife.com/</link>
            <source url="https://www.nintendolife.com/">Nintendo Life</source>
          </item>
          <item>
            <title>Nintendo announces a new console and release window</title>
            <link>https://www.nintendolife.com/news/new-console-window</link>
            <description>Nintendo described a new console and release window.</description>
            <source url="https://www.nintendolife.com/">Nintendo Life</source>
          </item>
        </channel></rss>"""

        with patch.object(world_pulse, "urlopen", return_value=BytesIO(rss_xml)):
            with patch.object(world_pulse, "_source_domain_for_category", return_value="nintendolife.com"):
                with patch.object(world_pulse, "_control_enabled", return_value=True):
                    with patch.object(world_pulse, "_domain_needs_license", return_value=False):
                        with patch.object(world_pulse, "_publisher_requires_license", return_value=False):
                            with patch.object(world_pulse, "_is_headline_only_domain", return_value=False):
                                category, lang, items = world_pulse._parse_any_rss(
                                    "https://news.google.com/rss/search?q=test", "gaming", "en", "Google News"
                                )

        self.assertEqual((category, lang), ("gaming", "en"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["original_title"], "Nintendo announces a new console and release window")

    def test_display_builder_hides_legacy_section_titles_without_deleting_archive_rows(self):
        rows = [
            {
                "slug": "real-story",
                "source_url": "https://www.nintendolife.com/news/new-console-window",
                "source_domain": "nintendolife.com",
                "source_name": "Nintendo Life",
                "category": "gaming",
                "original_language": "en",
                "title_en": "Nintendo announces a new console and release window",
                "is_demo": False,
            },
            {
                "slug": "old-section-label",
                "source_url": "https://www.nintendolife.com/news",
                "source_domain": "nintendolife.com",
                "source_name": "Nintendo Life",
                "category": "gaming",
                "original_language": "en",
                "title_en": "Latest Nintendo Life News",
                "is_demo": False,
            },
            {
                "slug": "old-publisher-home-title",
                "source_url": "https://www.aljazeera.com/",
                "source_domain": "aljazeera.com",
                "source_name": "Al Jazeera",
                "category": "world",
                "original_language": "en",
                "title_en": "Breaking News, World News and Video from Al Jazeera - Al Jazeera",
                "is_demo": False,
            },
        ]
        with patch.object(world_pulse, "_all_live_articles", return_value=rows):
            with patch.object(world_pulse, "_display_category", side_effect=lambda row, lang: row["category"]):
                with patch.object(world_pulse, "_row_allowed_on_language_site", return_value=True):
                    with patch.object(world_pulse, "_stories_are_near_duplicates", return_value=False):
                        with patch.object(world_pulse, "_normalise_story", side_effect=lambda row, lang: dict(row)):
                            stories = world_pulse._build_display_stories("en")

        self.assertEqual([story["slug"] for story in stories], ["real-story"])
        self.assertEqual(len(rows), 3, "legacy archive rows must be hidden, not deleted")

    def test_direct_article_route_hides_legacy_publisher_seo_titles(self):
        row = {
            "slug": "legacy-seo-title",
            "source_url": "https://www.aljazeera.com/",
            "source_domain": "aljazeera.com",
            "source_name": "Al Jazeera",
            "category": "world",
            "original_language": "en",
            "title_en": "Breaking News, World News and Video from Al Jazeera - Al Jazeera",
            "summary_en": "A publisher landing-page label mistakenly stored as a headline.",
            "content_en": "",
            "is_demo": False,
        }
        with patch.object(world_pulse, "current_language", return_value="en"):
            with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=row):
                    with patch.object(world_pulse, "_row_allowed_on_language_site", return_value=True):
                        response = world_pulse.app.test_client().get(
                            "/article/legacy-seo-title?lang=en"
                        )
        self.assertEqual(response.status_code, 404)

    def test_google_news_rss_query_is_limited_to_recent_stories(self):
        with patch.object(world_pulse, "_control_enabled", return_value=True):
            with patch.object(world_pulse, "_parse_any_rss", return_value=("world", "ar", [])) as parser:
                world_pulse._parse_feed_task("world", "ar")
        feed_url = parser.call_args.args[0]
        query = parse_qs(urlparse(feed_url).query).get("q", [""])[0]
        self.assertIn("when:7d", query)
        self.assertNotIn("site:", query)

    def test_rss_feed_does_not_search_when_no_allowlisted_sources_are_enabled(self):
        with patch.object(world_pulse, "CATEGORY_SOURCE_DOMAINS", {"world": {"ar": []}}):
            with patch.object(world_pulse, "_parse_any_rss") as parser:
                result = world_pulse._parse_feed_task("world", "ar")
        self.assertEqual(result, ("world", "ar", []))
        parser.assert_not_called()

    def test_jpl_http_error_falls_back_only_to_allowlisted_google_news_domain(self):
        from io import BytesIO

        direct_url = "https://www.jpl.nasa.gov/feeds/news/"
        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Google News</title>
          <item>
            <title>NASA JPL announces a new Mars research mission</title>
            <link>https://www.jpl.nasa.gov/news/example-mars-mission/</link>
            <description>The Jet Propulsion Laboratory described a new Mars research mission and its scientific goals.</description>
            <source url="https://www.jpl.nasa.gov/">NASA Jet Propulsion Laboratory</source>
            <pubDate>Fri, 16 Oct 2026 08:00:00 GMT</pubDate>
          </item>
        </channel></rss>"""
        requested_urls = []

        def fake_urlopen(request, timeout):
            requested_urls.append(request.full_url)
            if request.full_url == direct_url:
                raise world_pulse.HTTPError(direct_url, 403, "Forbidden", {}, None)
            return BytesIO(rss_xml)

        self.assertEqual(
            world_pulse._source_domain_for_category("science", "en", "jpl.nasa.gov"),
            "nasa.gov",
        )
        with patch.object(world_pulse, "urlopen", side_effect=fake_urlopen):
            with patch.object(world_pulse, "_control_enabled", return_value=True):
                result = world_pulse._parse_direct_rss_feed(
                    direct_url,
                    "science",
                    "en",
                    "jpl.nasa.gov",
                    "NASA Jet Propulsion Laboratory",
                )

        self.assertEqual((result[0], result[1]), ("science", "en"))
        self.assertEqual(len(result[2]), 1)
        self.assertEqual(result[2][0]["source_domain"], "nasa.gov")
        self.assertEqual(
            result[2][0]["source_url"],
            "https://www.jpl.nasa.gov/news/example-mars-mission/",
        )
        self.assertEqual(len(requested_urls), 2)
        fallback_query = parse_qs(urlparse(requested_urls[1]).query)["q"][0]
        self.assertIn("site:jpl.nasa.gov", fallback_query)
        self.assertIn("when:3d", fallback_query)

    def test_source_language_story_with_no_rss_excerpt_gets_transparent_summary(self):
        article = world_pulse._base_article({
            "slug": "headline-only-fallback",
            "source_url": "https://example.com/story",
            "category": "world",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": "New policy announced",
            "original_summary": "",
            "original_language": "en",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        })
        self.assertTrue(article["summary_en"])
        self.assertIn("did not include an excerpt", article["summary_en"])
        self.assertEqual(article["summary_ar"], "")

    def test_shared_gemini_cooldown_is_respected_across_workers(self):
        class FakeCursor:
            def __init__(self, value):
                self.value = value
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, _sql, _params=None):
                pass
            def fetchone(self):
                return self.value

        class FakeConnection:
            def __init__(self, value):
                self.value = value
                self.closed = False
            def cursor(self):
                return FakeCursor(self.value)
            def close(self):
                self.closed = True

        connection = FakeConnection((
            "rate_limited_429",
            datetime.now(timezone.utc) - timedelta(minutes=5),
        ))
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=connection):
                remaining, reason = world_pulse._shared_gemini_cooldown_remaining()
        self.assertEqual(reason, "rate_limited_429")
        self.assertGreater(remaining, 0)
        self.assertTrue(connection.closed)

    def test_existing_image_query_includes_stale_matches_for_rotation(self):
        class FakeCursor:
            def __init__(self):
                self.query = ""
                self.params = None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params=None):
                self.query, self.params = query, params
            def fetchall(self):
                return []

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.closed = False
            def cursor(self, **kwargs):
                return self.cursor_instance
            def close(self):
                self.closed = True

        connection = FakeConnection()
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=connection):
                result = world_pulse._db_fetch_articles_needing_images(limit=6)
        self.assertEqual(result, [])
        self.assertIn("COALESCE(image_url, '') <> ''", connection.cursor_instance.query)
        self.assertIn("INTERVAL '1 second'", connection.cursor_instance.query)
        self.assertEqual(connection.cursor_instance.params[0], world_pulse.IMAGE_RETRY_AFTER_HOURS)
        self.assertEqual(connection.cursor_instance.params[1], world_pulse.IMAGE_CACHE_MAX_AGE_SECONDS)
        self.assertTrue(connection.closed)

    def test_news_is_persisted_before_image_provider_calls(self):
        raw = {
            "slug": "fresh-news-first",
            "source_url": "https://example.com/fresh-news-first",
            "category": "world",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": "A newly reported development",
            "original_summary": "The source provides a short, factual excerpt.",
            "original_language": "en",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
            "image_url": "",
            "image_source": "none",
            "image_checked_at": None,
        }
        translation = {
            "title_ar": "تطور جديد",
            "title_en": "A newly reported development",
            "summary_ar": "موجز موجز يوضح ما ذكره المصدر.",
            "summary_en": "A short brief describing the source report.",
            "content_ar": "تفاصيل متاحة من المصدر لا تقل عن مئة حرف لاختبار حفظ الخبر قبل الصور.",
            "content_en": "Source-supported details long enough for the test to persist the new article before image fetching.",
        }
        events = []
        image_candidate = {
            "image_url": "https://images.example.com/news.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Photographer",
            "image_credit_url": "https://photos.example.com/item",
            "image_provider_url": "https://photos.example.com/item",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": datetime.now(timezone.utc),
        }

        def save_news(rows):
            events.append("save")
            self.assertEqual(rows[0]["source_url"], raw["source_url"])
            self.assertEqual(rows[0]["image_url"], "")
            return True

        def enrich(rows):
            self.assertIn("save", events, "news must be stored before calling image providers")
            events.append("images")
            rows[0].update(image_candidate)

        with tempfile.TemporaryDirectory() as tmp:
            lock_path = os.path.join(tmp, "news.lock")
            with patch.dict(os.environ, {"REFRESH_LOCK_FILE": lock_path}):
                with patch.object(world_pulse, "_ensure_schema", return_value=True):
                    with patch.object(world_pulse, "_load_persisted_news_queue", return_value={"discovered_at": "", "items": []}):
                        with patch.object(world_pulse, "_save_persisted_news_queue", return_value=True):
                            with patch.object(world_pulse, "_collect_rss_articles", return_value=[dict(raw)]):
                                with patch.object(world_pulse, "_db_fetch_articles_needing_editorial", return_value=[]):
                                    with patch.object(world_pulse, "_db_fetch_all", return_value=[]):
                                        with patch.object(world_pulse, "_translate_batch", return_value={0: translation}):
                                            with patch.object(world_pulse, "_db_upsert_many", side_effect=save_news):
                                                with patch.object(world_pulse, "_enrich_article_images", side_effect=enrich):
                                                    with patch.object(world_pulse, "_avoid_repeated_news_photos"):
                                                        with patch.object(world_pulse, "_db_update_article_images", return_value=1) as image_update:
                                                            with patch.object(world_pulse, "_backfill_missing_article_images", return_value=0) as image_backfill:
                                                                world_pulse._refresh_news_job()
        self.assertEqual(events, ["save", "images"])
        image_update.assert_called_once()
        image_backfill.assert_not_called()
        stored_in_memory = world_pulse._MEMORY_ARTICLES[raw["source_url"]]
        self.assertEqual(stored_in_memory["image_url"], image_candidate["image_url"])
        self.assertEqual(world_pulse._LAST_REFRESH_STATE, "success")
        world_pulse._MEMORY_ARTICLES.pop(raw["source_url"], None)

    def test_homepage_ticker_uses_latest_story_and_does_not_require_a_today_timestamp(self):
        latest = {
            "slug": "latest-story",
            "category": "world",
            "title": "Latest stored story",
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        with patch.object(world_pulse, "_maybe_start_refresh"):
            with patch.object(world_pulse, "_get_display_stories", return_value=[latest]):
                with patch.object(world_pulse, "render_template", return_value="home") as render:
                    response = world_pulse.app.test_client().get("/?lang=ar")
        self.assertEqual(response.status_code, 200)
        self.assertIs(render.call_args.kwargs["breaking_story"], latest)

    def test_image_refresh_prioritises_stories_without_persisted_images(self):
        newest_with_image = {
            "slug": "newest-with-image",
            "image_url": "https://example.com/photo.jpg",
            "published_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
        }
        newest_missing = {
            "slug": "newest-missing",
            "image_url": "",
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        older_missing = {
            "slug": "older-missing",
            "image_url": "",
            "published_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
        }
        older_with_image = {
            "slug": "older-with-image",
            "image_url": "https://example.com/older.jpg",
            "published_at": datetime(2026, 10, 12, tzinfo=timezone.utc),
        }
        rows = world_pulse._prioritise_missing_image_rows([
            newest_with_image, older_with_image, newest_missing, older_missing,
        ])
        self.assertEqual(
            [row["slug"] for row in rows],
            ["newest-missing", "older-missing", "newest-with-image", "older-with-image"],
        )

    def test_image_refresh_rotates_past_recently_checked_missing_photos(self):
        now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        recent_failed = {
            "slug": "recent-failed",
            "image_url": "",
            "image_checked_at": now,
            "published_at": now,
        }
        older_unchecked = {
            "slug": "older-unchecked",
            "image_url": "",
            "image_checked_at": None,
            "published_at": datetime(2026, 10, 14, tzinfo=timezone.utc),
        }
        older_failed = {
            "slug": "older-failed",
            "image_url": "",
            "image_checked_at": datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc),
            "published_at": datetime(2026, 10, 13, tzinfo=timezone.utc),
        }
        existing_photo = {
            "slug": "existing-photo",
            "image_url": "https://example.com/photo.jpg",
            "image_checked_at": None,
            "published_at": now,
        }
        rows = world_pulse._prioritise_missing_image_rows([
            recent_failed, older_failed, existing_photo, older_unchecked,
        ])
        self.assertEqual(
            [row["slug"] for row in rows],
            ["older-unchecked", "older-failed", "recent-failed", "existing-photo"],
        )

    def test_image_search_query_uses_headline_and_source_excerpt_context(self):
        query = world_pulse._image_search_query(
            "Nvidia chip launched",
            "A new semiconductor prototype for artificial intelligence data centers.",
        )
        tokens = world_pulse._image_tokens(query)
        self.assertIn("nvidia", tokens)
        self.assertIn("chip", tokens)
        self.assertIn("semiconductor", tokens)
        self.assertLessEqual(len(tokens), 6)

    def test_image_search_query_falls_back_to_title_when_source_excerpt_is_empty(self):
        query = world_pulse._image_search_query(
            "New interest rate decision by central bank",
            "",
        )
        self.assertTrue(query)
        self.assertLessEqual(len(world_pulse._image_tokens(query)), 5)

    def test_image_enrichment_deadline_preserves_previous_safe_image_and_returns(self):
        now = datetime.now(timezone.utc)
        stale_checked = now - timedelta(days=10)
        first_url = "https://example.com/image-deadline-first"
        second_url = "https://example.com/image-deadline-second"
        stored = [
            {
                "slug": "first",
                "source_url": first_url,
                "image_url": "https://images.example.com/old-first.jpg",
                "image_source": "wikimedia_relevant",
                "image_credit": "Old photographer",
                "image_credit_url": "https://commons.wikimedia.org/wiki/Old_first",
                "image_provider_url": "https://commons.wikimedia.org/wiki/Old_first",
                "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
                "image_relevance_verified": True,
                "image_checked_at": stale_checked,
            },
            {
                "slug": "second",
                "source_url": second_url,
                "image_url": "https://images.example.com/old-second.jpg",
                "image_source": "openverse_licensed",
                "image_credit": "Second photographer",
                "image_credit_url": "https://photos.example.org/old-second",
                "image_provider_url": "https://photos.example.org/old-second",
                "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
                "image_relevance_verified": True,
                "image_checked_at": stale_checked,
            },
        ]
        raw = [
            {"source_url": first_url, "image_url": "", "image_source": "none", "image_checked_at": None,
             "image_search_title": "First story", "original_language": "en", "category": "world"},
            {"source_url": second_url, "image_url": "", "image_source": "none", "image_checked_at": None,
             "image_search_title": "Second story", "original_language": "en", "category": "world"},
        ]

        class FakeFuture:
            def __init__(self, result=None, complete=False):
                self._result = result
                self._complete = complete
                self.cancelled = False
            def cancel(self):
                self.cancelled = True
                return True
            def result(self):
                if not self._complete:
                    raise TimeoutError("still running")
                return self._result

        class FakeExecutor:
            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.futures = []
                self.shutdown_args = None
            def submit(self, _fn, item):
                if item["source_url"] == first_url:
                    f = FakeFuture({
                        "image_url": "https://images.example.com/new-first.jpg",
                        "image_source": "openverse_licensed",
                        "image_credit": "New photographer",
                        "image_credit_url": "https://photos.example.org/new-first",
                        "image_provider_url": "https://photos.example.org/new-first",
                        "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "image_checked_at": now,
                    }, complete=True)
                else:
                    f = FakeFuture(complete=False)
                self.futures.append(f)
                return f
            def shutdown(self, wait, cancel_futures):
                self.shutdown_args = (wait, cancel_futures)

        executor = FakeExecutor(max_workers=3)
        def complete_then_timeout(futures, timeout):
            futures = list(futures)
            yield futures[0]
            raise TimeoutError("image batch expired")

        with patch.object(world_pulse, "MAX_IMAGE_LOOKUPS_PER_REFRESH", 12):
            with patch.object(world_pulse, "_db_fetch_all", return_value=stored):
                with patch.object(world_pulse, "_control_enabled", return_value=True):
                    with patch.object(world_pulse, "_reserve_gemini_image_slots", return_value=0):
                        with patch.object(world_pulse, "ThreadPoolExecutor", return_value=executor):
                            with patch.object(world_pulse, "as_completed", side_effect=complete_then_timeout):
                                world_pulse._enrich_article_images(raw, force_refresh=True, allow_ai_generation=False)
    
        self.assertEqual(raw[0]["image_url"], "https://images.example.com/new-first.jpg")
        self.assertEqual(raw[1]["image_url"], "https://images.example.com/old-second.jpg")
        self.assertEqual(raw[1]["image_source"], "openverse_licensed")
        self.assertEqual(executor.shutdown_args, (False, True))
        self.assertTrue(executor.futures[1].cancelled)
        self.assertEqual(world_pulse._LAST_IMAGE_STATUS["found"], 1)

    def test_display_stories_cache_reuses_builder_until_invalidated(self):
        stories = [{"slug": "cached-story", "title_ar": "عنوان", "title_en": "Headline"}]
        with patch.object(world_pulse, "_build_display_stories", return_value=stories) as builder:
            with world_pulse._DISPLAY_STORIES_CACHE_LOCK:
                world_pulse._DISPLAY_STORIES_CACHE.clear()
            first = world_pulse._get_display_stories("ar")
            second = world_pulse._get_display_stories("ar")
            self.assertEqual(first, second)
            builder.assert_called_once_with("ar")
            with patch.object(world_pulse, "_refresh_display_stories_cache_async") as refresh:
                world_pulse._invalidate_db_articles_cache()
                third = world_pulse._get_display_stories("ar")
                self.assertEqual(third, first)
                refresh.assert_called_once()
            self.assertEqual(builder.call_count, 1)

    def test_second_worker_reuses_shared_normalized_display_snapshot(self):
        story = {
            "slug": "shared-display-story",
            "title": "Cached normalized headline",
            "summary": "Cached summary",
            "published_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
            "fetched_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
        }
        world_pulse._write_shared_display_cache("en", [story])
        with patch.object(world_pulse, "_build_display_stories", side_effect=AssertionError("must reuse shared cache")) as builder:
            result = world_pulse._get_display_stories("en")
        self.assertEqual(result, [story])
        builder.assert_not_called()

    def test_expired_shared_display_snapshot_is_served_while_refresh_is_scheduled(self):
        story = {"slug": "stale-display-story", "title": "Still usable"}
        world_pulse._write_shared_display_cache("en", [story])
        world_pulse._mark_shared_display_cache_stale()
        with patch.object(world_pulse, "_refresh_display_stories_cache_async") as refresh:
            with patch.object(world_pulse, "_build_display_stories", side_effect=AssertionError("refresh must be async")):
                result = world_pulse._get_display_stories("en")
        self.assertEqual(result, [story])
        refresh.assert_called_once()

    def test_hiding_an_article_discards_shared_display_snapshot(self):
        world_pulse._write_shared_display_cache("ar", [{"slug": "hidden-story"}])
        world_pulse._clear_display_stories_cache(hard=True)
        self.assertIsNone(world_pulse._read_shared_display_cache("ar"))

    def test_parallel_cold_display_requests_share_one_build_per_language(self):
        stories = [{"slug": "shared-cold-story", "title": "Headline"}]

        def slow_build(lang):
            self.assertEqual(lang, "en")
            time.sleep(0.05)
            return stories

        with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
            with patch.object(world_pulse, "_build_display_stories", side_effect=slow_build) as builder:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(lambda _index: world_pulse._get_display_stories("en"), range(6)))

        self.assertEqual(builder.call_count, 1)
        self.assertEqual(results, [stories] * 6)

    def test_expired_display_cache_is_served_while_background_refresh_runs(self):
        old_stories = [{"slug": "old-cache-story", "title": "Previously cached"}]
        new_stories = [{"slug": "fresh-cache-story", "title": "Newly refreshed"}]
        cache = {
            "en": (
                time.monotonic() - world_pulse._DISPLAY_STORIES_CACHE_TTL_SECONDS - 1,
                old_stories,
            )
        }
        refresh_started = threading.Event()
        release_refresh = threading.Event()

        def controlled_build(lang):
            self.assertEqual(lang, "en")
            refresh_started.set()
            release_refresh.wait(timeout=3)
            return new_stories

        with world_pulse._DISPLAY_STORIES_REFRESHING_LOCK:
            world_pulse._DISPLAY_STORIES_REFRESHING.discard("en")
        with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", cache):
            with patch.object(world_pulse, "_build_display_stories", side_effect=controlled_build) as builder:
                try:
                    displayed = world_pulse._get_display_stories("en")
                    self.assertEqual(displayed, old_stories)
                    self.assertTrue(refresh_started.wait(timeout=1))
                    self.assertEqual(builder.call_count, 1)
                finally:
                    release_refresh.set()

                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    with world_pulse._DISPLAY_STORIES_CACHE_LOCK:
                        current = cache.get("en")
                    if current and current[1] == new_stories:
                        break
                    time.sleep(0.01)

                self.assertEqual(cache["en"][1], new_stories)

    def test_news_status_poll_reports_state_without_triggering_refresh(self):
        with patch.object(world_pulse, "_maybe_start_refresh") as maybe_refresh:
            with patch.object(world_pulse, "_db_last_fetched_at", return_value=None):
                with patch.object(world_pulse, "_probe_database", return_value={"state": "not_configured", "error_code": "", "checked_at": None}):
                    with patch.object(world_pulse, "_database_url", return_value=""):
                        with patch.object(world_pulse, "_control_enabled", return_value=True):
                            with patch.object(world_pulse, "_presskit_provider_configured", return_value=False):
                                with patch.object(world_pulse, "_news_setup_issues", return_value=[]):
                                    response = world_pulse.app.test_client().get("/api/news-status")
        self.assertEqual(response.status_code, 200)
        maybe_refresh.assert_not_called()

    def test_image_provider_group_prefers_higher_relevance_over_provider_order(self):
        low_relevance = {
            "image_url": "https://images.example.com/weak-match.jpg",
            "image_source": "wikimedia_relevant",
            "_image_relevance_score": 0.18,
        }
        high_relevance = {
            "image_url": "https://images.example.com/topic-match.jpg",
            "image_source": "openverse_licensed",
            "_image_relevance_score": 0.86,
        }
        finders = (
            ("image:wikimedia_relevant", lambda: low_relevance),
            ("image:openverse_licensed", lambda: high_relevance),
        )

        with patch.object(world_pulse, "_control_enabled", return_value=True):
            result = world_pulse._search_image_provider_group("test", finders)

        self.assertEqual(result["image_url"], high_relevance["image_url"])
        self.assertEqual(result["_image_relevance_score"], 0.86)

    def test_image_provider_group_returns_first_configured_priority_match(self):
        first = {"image_url": "https://images.example.com/commons.jpg", "image_source": "wikimedia_relevant"}
        second = {"image_url": "https://images.example.com/openverse.jpg", "image_source": "openverse_licensed"}
        finders = (
            ("image:wikimedia_relevant", lambda: first),
            ("image:openverse_licensed", lambda: second),
        )
        with patch.object(world_pulse, "_control_enabled", return_value=True):
            result = world_pulse._search_image_provider_group("test", finders)
        self.assertEqual(result, first)

    def test_image_provider_group_deadline_allows_processing_headroom(self):
        self.assertEqual(
            world_pulse.IMAGE_PROVIDER_GROUP_TIMEOUT_SECONDS,
            min(
                15,
                max(
                    world_pulse.IMAGE_SEARCH_TIMEOUT_SECONDS + 5,
                    world_pulse.IMAGE_SEARCH_TIMEOUT_SECONDS * 3,
                ),
            ),
        )
        self.assertLessEqual(world_pulse.IMAGE_PROVIDER_GROUP_TIMEOUT_SECONDS, 15)

        original_as_completed = world_pulse.as_completed
        observed_timeouts = []
        candidate = {
            "image_url": "https://images.example.com/timely-result.jpg",
            "image_source": "wikimedia_relevant",
            "_image_relevance_score": 0.8,
        }

        def record_timeout(futures, timeout):
            observed_timeouts.append(timeout)
            return original_as_completed(futures, timeout=timeout)

        with patch.object(world_pulse, "_control_enabled", return_value=True):
            with patch.object(world_pulse, "as_completed", side_effect=record_timeout):
                result = world_pulse._search_image_provider_group(
                    "test", (("image:wikimedia_relevant", lambda: candidate),)
                )

        self.assertEqual(observed_timeouts, [world_pulse.IMAGE_PROVIDER_GROUP_TIMEOUT_SECONDS])
        self.assertEqual(result["image_url"], candidate["image_url"])

    def test_forced_image_refresh_does_not_reuse_a_fresh_cached_photo_when_better_match_exists(self):
        checked_at = datetime.now(timezone.utc)
        source_url = "https://www.example.com/news/image-refresh"
        stored = {
            "slug": "image-refresh-story",
            "source_url": source_url,
            "category": "technology",
            "source_name": "Example News",
            "source_domain": "example.com",
            "image_url": "https://images.example.com/old-photo.jpg",
            "image_source": "wikimedia_relevant",
            "image_credit": "Old photographer",
            "image_credit_url": "https://commons.wikimedia.org/wiki/Old_photo",
            "image_provider_url": "https://commons.wikimedia.org/wiki/Old_photo",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": checked_at,
            "title_en": "New satellite technology launched",
            "title_ar": "",
            "summary_en": "A brief summary of a satellite technology launch.",
            "summary_ar": "",
            "content_en": "",
            "content_ar": "",
            "original_language": "en",
            "published_at": checked_at,
            "fetched_at": checked_at,
            "read_minutes": 1,
            "is_demo": False,
        }
        raw = {
            "slug": stored["slug"],
            "source_url": source_url,
            "category": "technology",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": stored["title_en"],
            "original_language": "en",
            "image_search_title": stored["title_en"],
            "image_url": "",
            "image_source": "none",
            "image_checked_at": None,
        }
        new_result = {
            "image_url": "https://images.example.com/new-photo.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "New photographer",
            "image_credit_url": "https://photos.example.org/item/new-photo",
            "image_provider_url": "https://photos.example.org/item/new-photo",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": checked_at,
            "image_title": "New satellite technology photo",
            "_image_relevance_evidence": "New satellite technology launch communications satellite",
            "_image_relevance_score": 0.82,
        }
        with patch.object(world_pulse, "_db_fetch_all", return_value=[stored]):
            with patch.object(world_pulse, "_control_enabled", return_value=True):
                with patch.object(world_pulse, "_search_any_reusable_image", return_value=new_result):
                    world_pulse._enrich_article_images([raw], force_refresh=True, allow_ai_generation=False)

        self.assertEqual(raw["image_url"], new_result["image_url"])
        self.assertEqual(raw["image_credit"], "New photographer")
        self.assertEqual(raw["image_source"], "openverse_licensed")



class PersistentPendingQueueTests(unittest.TestCase):
    def test_cleanup_deduplicates_without_dropping_oldest_or_newest_pending_items(self):
        items = [
            {
                "source_url": f"https://example.com/pending/{index}",
                "category": "world",
                "original_language": "en",
                "sequence": index,
            }
            for index in range(65)
        ]
        items.extend([
            dict(items[10]),
            {
                "source_url": "https://example.com/already-published",
                "category": "world",
                "original_language": "en",
            },
        ])

        cleaned = world_pulse._clean_pending_news_queue(
            items,
            {"example.com/already-published"},
        )

        self.assertEqual(len(cleaned), 65)
        self.assertEqual(cleaned[0]["sequence"], 0)
        self.assertEqual(cleaned[-1]["sequence"], 64)
        self.assertEqual(
            [item["sequence"] for item in cleaned],
            list(range(65)),
        )



class BoundedImageProviderSearchTests(unittest.TestCase):
    def test_culture_specialist_catalogues_run_only_after_primary_catalogues_miss(self):
        selected = {
            "image_url": "https://images.example.test/artwork.jpg",
            "image_source": "met_open_access",
            "_image_relevance_score": 0.72,
        }
        with patch.object(
            world_pulse,
            "_search_image_provider_group",
            side_effect=[{}, selected],
        ) as search_group:
            result = world_pulse._search_any_reusable_image(
                "A major art exhibition opens", "en", "culture"
            )

        self.assertEqual(result, selected)
        self.assertEqual(search_group.call_count, 2)
        primary_name, primary_finders = search_group.call_args_list[0].args
        self.assertEqual(primary_name, "open_catalogues")
        self.assertEqual(
            [key for key, _finder in primary_finders],
            ["image:openverse_licensed", "image:wikimedia_relevant", "image:loc_open_access"],
        )
        specialist_name, specialist_finders = search_group.call_args_list[1].args
        self.assertEqual(specialist_name, "specialist_catalogues")
        self.assertEqual(
            {key for key, _finder in specialist_finders},
            {
                "image:artic_open_access",
                "image:met_open_access",
                "image:cleveland_museum_open_access",
                "image:wellcome_open_access",
            },
        )

    def test_non_cultural_stories_skip_museum_catalogues(self):
        selected = {
            "image_url": "https://images.example.test/nasa.jpg",
            "image_source": "nasa_images",
            "_image_relevance_score": 0.80,
        }
        with patch.object(
            world_pulse,
            "_search_image_provider_group",
            side_effect=[{}, selected],
        ) as search_group:
            result = world_pulse._search_any_reusable_image(
                "A satellite launches into orbit", "en", "science"
            )

        self.assertEqual(result, selected)
        self.assertEqual(search_group.call_count, 2)
        self.assertEqual(search_group.call_args_list[0].args[0], "open_catalogues")
        self.assertEqual(search_group.call_args_list[1].args[0], "specialist_catalogues")
        specialist_keys = {
            key for key, _finder in search_group.call_args_list[1].args[1]
        }
        self.assertEqual(specialist_keys, {"image:wellcome_open_access"})


    def test_archive_feed_query_limits_each_language_before_combining(self):
        from unittest.mock import MagicMock

        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        with patch.object(world_pulse, "_DB_ARTICLES_CACHE", None):
            with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", 0.0):
                # Isolate this SQL-shape test from a shared archive file left by earlier tests.
                with patch.object(world_pulse, "_read_shared_archive_cache", return_value=None):
                    with patch.object(world_pulse, "_write_shared_archive_cache"):
                        with patch.object(world_pulse, "_ensure_schema", return_value=True):
                            with patch.object(world_pulse, "_connect_db", return_value=connection):
                                with patch.object(world_pulse, "_release_db_connection"):
                                    self.assertEqual(world_pulse._db_fetch_all(), [])

        query = cursor.execute.call_args.args[0]
        self.assertNotIn("ROW_NUMBER()", query)
        self.assertIn("UNION ALL", query)
        self.assertIn("SELECT * FROM (", query)
        self.assertEqual(query.count("LIMIT 120"), 2)
        self.assertIn("original_language = 'ar'", query)
        self.assertIn("original_language = 'en'", query)
        self.assertIn("LOWER(source_domain) = ANY(%s)", query)
        self.assertIn("LOWER(source_name) LIKE ANY(%s)", query)
        params = cursor.execute.call_args.args[1]
        self.assertEqual(len(params), 6)
        self.assertIn("aljazeera.net", params[0])
        self.assertIn("theverge.com", params[3])
        self.assertNotIn("npr.org", params[0] + params[3])

    def test_partial_translation_falls_back_to_cohesive_native_article(self):
        native_body = (
            "يتناول التقرير تفاصيل الحدث وسياقه بحسب المعلومات التي نشرها المصدر. "
            "وتوضح المادة ما جرى والخطوة التالية دون إضافة معلومات غير موجودة في المصدر."
        )
        row = {
            "slug": "partial-translation",
            "source_url": "https://www.saudigamer.com/example-story/",
            "source_name": "Saudi Gamer",
            "source_domain": "saudigamer.com",
            "category": "gaming",
            "original_language": "ar",
            "title_ar": "عنوان عربي أصلي واضح عن تطور جديد في الألعاب",
            "title_en": "A partial English translation",
            "summary_ar": "يلخص هذا الموجز الحدث ويوضح أبرز ما يورده المصدر عن تفاصيل التطور الجديد.",
            "summary_en": "A generated English summary exists but the translated details are incomplete.",
            "content_ar": native_body,
            "content_en": "Only a fragment.",
            "image_url": "",
            "image_source": "none",
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertEqual(story["display_language"], "ar")
        self.assertTrue(story["translation_fallback"])
        self.assertEqual(story["title"], row["title_ar"])
        self.assertEqual(story["summary"], row["summary_ar"])
        self.assertTrue(story["content"])

    def test_headline_only_article_opens_internal_detail_with_original_source_link(self):
        row = {
            "slug": "bbc-headline-only",
            "source_url": "https://www.bbc.com/news/example-story",
            "source_name": "BBC News",
            "source_domain": "bbc.com",
            "category": "world",
            "original_language": "en",
            "title_en": "A BBC publisher headline",
            "title_ar": "",
            "summary_en": "A restricted publisher headline has no reusable article text.",
            "summary_ar": "",
            "content_en": "This is a stored but restricted body which must never appear on our internal page.",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "is_demo": False,
        }

        with patch.object(world_pulse, "_ensure_background_scheduler"):
            with patch.object(world_pulse, "current_language", return_value="en"):
                with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                    with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=row):
                        with patch.object(world_pulse, "_row_allowed_on_language_site", return_value=True):
                            with patch.object(world_pulse, "_display_category", return_value="world"):
                                with patch.object(world_pulse, "_db_fetch_related_articles", return_value=[]):
                                    with patch.object(world_pulse, "_get_display_stories", side_effect=AssertionError("cold article should not rebuild homepage")) as rebuild:
                                        with patch.object(world_pulse, "render_template", return_value="internal article page") as render:
                                            response = world_pulse.app.test_client().get("/article/bbc-headline-only?lang=en")
                                        rebuild.assert_not_called()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "internal article page")
        self.assertEqual(render.call_args.kwargs["article"]["source_url"], row["source_url"])
        self.assertEqual(render.call_args.kwargs["article"]["content"], "")

    def test_source_only_cards_open_internal_article_pages_and_keep_status_ui_hidden(self):
        template_path = os.path.join(os.path.dirname(world_pulse.__file__), "templates", "index.html")
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()

        self.assertNotIn("story.source_url if story.source_only", template)
        self.assertNotIn("breaking_story.source_url if breaking_story.source_only", template)
        self.assertIn("url_for('article', slug=story.slug, lang=lang)", template)
        self.assertNotIn('{% if story.source_only %} target="_blank"', template)
        self.assertIn("article.source_url", template)
        self.assertIn('id="latest-stories"', template)
        self.assertNotIn('id="refreshNews"', template)
        self.assertNotIn('id="newsStatusText"', template)
        self.assertNotIn("Last updated", template)
        self.assertNotIn("تحديث تلقائي كل", template)


    def test_stale_catalogued_images_are_eligible_for_periodic_revalidation(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=connection):
                with patch.object(world_pulse, "_release_db_connection"):
                    self.assertEqual(world_pulse._db_fetch_articles_needing_images(limit=1), [])
        sql = cursor.execute.call_args.args[0]
        self.assertNotIn("image_url NOT LIKE '/media/catalogued/", sql)
        self.assertIn("image_checked_at < NOW() - (%s * INTERVAL '1 second')", sql)
        self.assertGreaterEqual(world_pulse.IMAGE_CACHE_MAX_AGE_SECONDS, 6 * 3600)

    def test_arabic_archive_image_revalidation_uses_native_arabic_title_and_summary(self):
        row = {
            "slug": "arabic-story",
            "source_url": "https://aitnews.com/2026/10/17/example",
            "category": "technology",
            "source_name": "AIT News",
            "source_domain": "aitnews.com",
            "original_language": "ar",
            "title_ar": "عنوان عربي عن إطلاق هاتف جديد",
            "summary_ar": "تفاصيل عربية عن الهاتف ومواصفاته المعلنة.",
            "content_ar": "تفاصيل إضافية موثقة من المصدر.",
            "title_en": "New phone announced",
            "summary_en": "An English summary about the announced phone.",
            "content_en": "Additional source-supported details.",
            "image_url": "",
            "image_source": "none",
            "image_checked_at": None,
        }
        captured = []

        def capture(items, **_kwargs):
            captured.extend(dict(item) for item in items)

        with patch.object(world_pulse, "_db_fetch_articles_needing_images", return_value=[row]):
            with patch.object(world_pulse, "_enrich_article_images", side_effect=capture):
                with patch.object(world_pulse, "_db_update_article_images", return_value=1):
                    world_pulse._backfill_missing_article_images(limit=1)

        self.assertEqual(captured[0]["image_search_title"], row["title_ar"])
        self.assertEqual(captured[0]["image_search_context"], row["summary_ar"])

    def test_periodic_image_revalidation_does_not_keep_a_stale_photo_when_no_match_exists(self):
        old_image = {
            "image_url": "/media/catalogued/" + ("a" * 40),
            "image_source": "wikimedia_relevant",
            "image_credit": "Old creator",
            "image_credit_url": "https://commons.wikimedia.org/wiki/Old_file",
            "image_provider_url": "https://commons.wikimedia.org/wiki/Old_file",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": datetime.now(timezone.utc) - timedelta(days=2),
        }
        raw = {
            "slug": "old-story",
            "source_url": "https://example.com/old-story",
            "category": "world",
            "source_name": "Example News",
            "source_domain": "example.com",
            "original_title": "A distinct verified headline about a new development",
            "original_summary": "A short factual excerpt from the original publisher.",
            "original_language": "en",
            "image_url": "",
            "image_source": "none",
            "_fallback_cached_image": old_image,
            "_revalidating_cached_image": True,
        }
        with patch.object(world_pulse, "_search_article_image_with_variants", return_value={}):
            result = world_pulse._resolve_article_image(raw)

        self.assertEqual(result["image_url"], "")
        self.assertEqual(result["image_source"], "none")


    def test_privacy_policy_covers_advertising_cookies_and_identifiers_in_both_languages(self):
        privacy = world_pulse.STATIC_PAGES["privacy"]
        arabic = " ".join(body for _heading, body in privacy["sections_ar"])
        english = " ".join(body for _heading, body in privacy["sections_en"])

        self.assertIn("Google AdSense", arabic)
        self.assertIn("عناوين IP", arabic)
        self.assertIn("إشارات الويب", arabic)
        self.assertIn("Google AdSense", english)
        self.assertIn("cookies", english.casefold())
        self.assertIn("web beacons", english)
        self.assertIn("IP addresses", english)
        self.assertIn("consent mechanism", english)

        template, _filename, _uptodate = world_pulse.app.jinja_env.loader.get_source(
            world_pulse.app.jinja_env, "index.html"
        )
        self.assertIn("policies.google.com/technologies/partner-sites", template)
        self.assertIn("adssettings.google.com", template)

    def test_ai_enriched_badge_requires_substantive_arabic_and_english_bodies(self):
        row = {
            "slug": "ai-quality-check",
            "source_url": "https://www.theverge.com/news/ai-quality-check",
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "category": "technology",
            "original_language": "en",
            "title_ar": "تحديث تقني جديد",
            "title_en": "A new technology update",
            "summary_ar": "يعرض المصدر تحديثاً تقنياً محدداً.",
            "summary_en": "The source describes a specific technology update.",
            "content_ar": "تفاصيل مختصرة فقط.",
            "content_en": "A short detail.",
            "image_url": "",
            "image_source": "none",
            "is_demo": False,
        }
        short_story = world_pulse._normalise_story(dict(row), "en")
        self.assertFalse(short_story["ai_enriched"])

        long_ar = (
            "يوضح المصدر أن الشركة أعلنت عن تحديث تقني جديد لمنتجها. "
            "وتشير المادة إلى التغيير المعلن والسياق المذكور وموعد التنفيذ عندما يكون متاحاً. "
            "ولا يضيف هذا الملخص أرقاماً أو أسماء أو نتائج لم ترد في النص الأصلي. "
        ) * 2
        long_en = (
            "The source says the company announced a new technology update. "
            "The brief describes the reported change and the context provided in the source. "
            "It does not add figures, names, dates, outcomes, or claims that the source did not report. "
        ) * 2
        complete_story = world_pulse._normalise_story(
            dict(row, content_ar=long_ar, content_en=long_en), "en"
        )
        self.assertTrue(complete_story["ai_enriched"])

    def test_sitemaps_exclude_short_or_headline_only_article_pages(self):
        published = datetime.now(timezone.utc)
        eligible = {
            "slug": "eligible-story",
            "source_url": "https://www.theverge.com/news/eligible-story",
            "title": "A substantive technology report",
            "summary": "A separate executive summary about the reported development.",
            "content": ("The article provides source-supported details about the reported development. " * 4),
            "published_at": published,
            "headline_only": False,
            "source_only": False,
            "is_demo": False,
        }
        thin = dict(
            eligible,
            slug="thin-story",
            source_url="https://www.theverge.com/news/thin-story",
            title="A thin item",
            content="A few words only.",
            source_only=True,
        )
        headline_only = dict(
            eligible,
            slug="headline-only-story",
            source_url="https://www.bbc.com/news/headline-only-story",
            title="Headline-only item",
            headline_only=True,
            source_only=True,
            content="",
        )
        rows = [eligible, thin, headline_only]
        with patch.object(world_pulse, "_get_display_stories", side_effect=lambda _lang: rows):
            with patch.object(world_pulse, "STATIC_PAGES", {}):
                client = world_pulse.app.test_client()
                sitemap_response = client.get("/sitemap.xml")
                news_sitemap_response = client.get("/news-sitemap.xml")

        self.assertEqual(sitemap_response.status_code, 200)
        sitemap_body = sitemap_response.get_data(as_text=True)
        self.assertIn("eligible-story", sitemap_body)
        self.assertNotIn("thin-story", sitemap_body)
        self.assertNotIn("headline-only-story", sitemap_body)
        news_body = news_sitemap_response.get_data(as_text=True)
        self.assertIn("eligible-story", news_body)
        self.assertNotIn("thin-story", news_body)
        self.assertNotIn("headline-only-story", news_body)

    def test_thin_or_headline_only_article_pages_are_not_indexed_as_full_articles(self):
        source, _filename, _uptodate = world_pulse.app.jinja_env.loader.get_source(
            world_pulse.app.jinja_env, "index.html"
        )
        self.assertIn("article.headline_only", source)
        self.assertIn("article.source_only", source)
        self.assertIn("(article.content|length < 180)", source)
        self.assertIn('content="noindex,follow"', source)

    def test_content_audit_treats_google_news_url_as_wrapper_not_publisher(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        row = {
            "slug": "google-news-wrapper",
            "source_url": "https://news.google.com/rss/articles/example",
            "source_domain": "bbc.com",
            "source_name": "BBC News",
            "category": "politics",
            "original_language": "en",
            "title_en": "Government announces new election policy",
            "summary_en": "The government announced a new election policy today.",
            "content_en": "",
            "title_ar": "",
            "summary_ar": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "",
            "image_license_url": "",
            "image_checked_at": None,
            "published_at": now,
            "is_demo": False,
        }
        issues = world_pulse._content_quality_audit_issues(row, now=now)
        self.assertNotIn("source_domain_mismatch", issues)
        self.assertNotIn("source_not_allowlisted_for_category_language", issues)

    def test_content_audit_still_flags_wrong_direct_publisher_domain(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        row = {
            "slug": "wrong-direct-host",
            "source_url": "https://example.invalid/news/story",
            "source_domain": "bbc.com",
            "source_name": "BBC News",
            "category": "politics",
            "original_language": "en",
            "title_en": "Government announces new election policy",
            "summary_en": "The government announced a new election policy today.",
            "content_en": "",
            "title_ar": "",
            "summary_ar": "",
            "content_ar": "",
            "image_url": "",
            "image_source": "",
            "image_license_url": "",
            "image_checked_at": None,
            "published_at": now,
            "is_demo": False,
        }
        issues = world_pulse._content_quality_audit_issues(row, now=now)
        self.assertIn("source_domain_mismatch", issues)


    def test_editorial_prompt_requires_original_source_supported_reports(self):
        prompt = world_pulse._build_editorial_prompt([{
            "index": 0,
            "category": "world",
            "source": "Example News",
            "source_url": "https://example.com/story",
            "headline": "Government announces a new policy",
            "rss_excerpt": "The government announced the policy on Tuesday.",
            "source_language": "en",
        }])
        self.assertIn("independent editorial synthesis", prompt)
        self.assertIn("not a line-by-line paraphrase", prompt)
        self.assertIn("140–220 words", prompt)
        self.assertIn("never pad it with generic background or invented context", prompt)



    def test_shared_archive_snapshot_serves_a_warm_worker_without_database_query(self):
        row = {
            "slug": "shared-archive-story",
            "source_url": "https://www.theverge.com/shared-archive-story",
            "source_domain": "theverge.com",
            "source_name": "The Verge",
            "category": "technology",
            "original_language": "en",
            "title_en": "A stored technology headline",
            "summary_en": "A stored summary that makes the story eligible for the current feed.",
            "content_en": "Saved detail text.",
            "published_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "fetched_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "is_demo": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "archive.json")
            with patch.object(world_pulse, "_ARCHIVE_SHARED_CACHE_PATH", cache_path):
                with patch.object(world_pulse, "_DB_ARTICLE_CACHE_TTL_SECONDS", 60):
                    with patch.object(world_pulse, "_DB_ARTICLES_CACHE", None):
                        with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", 0.0):
                            with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                                world_pulse._write_shared_archive_cache([row])
                                with patch.object(
                                    world_pulse, "_query_persistent_archive_rows",
                                    side_effect=AssertionError("warm shared cache must prevent a database query"),
                                ) as query:
                                    result = world_pulse._db_fetch_all()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slug"], "shared-archive-story")
        self.assertIsInstance(result[0]["published_at"], datetime)
        query.assert_not_called()

    def test_archive_cache_merge_preserves_a_licensed_photo_and_adds_the_new_story(self):
        older = {
            "slug": "existing-ait-story",
            "source_url": "https://aitnews.com/existing-story",
            "source_domain": "aitnews.com",
            "source_name": "AIT News",
            "category": "technology",
            "original_language": "ar",
            "title_ar": "عنوان سابق",
            "summary_ar": "ملخص سابق يفي بشرط العرض",
            "content_ar": "تفاصيل الخبر السابق.",
            "title_en": "",
            "summary_en": "",
            "content_en": "",
            "image_url": "https://images.example.test/licensed.jpg",
            "image_source": "wikimedia_relevant",
            "image_credit": "Creator name",
            "image_credit_url": "https://commons.wikimedia.org/wiki/File:licensed.jpg",
            "image_provider_url": "https://commons.wikimedia.org/wiki/File:licensed.jpg",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "published_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
            "fetched_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
            "is_demo": False,
        }
        updated_existing = {
            **older,
            "title_ar": "عنوان محرر جديد",
            "summary_ar": "ملخص مستقل جديد من مصدر مسموح.",
            "content_ar": "تفاصيل إضافية مسموح بها.",
            "image_url": "",
            "image_source": "none",
            "image_credit": "",
            "image_credit_url": "",
            "image_provider_url": "",
            "image_license_url": "",
            "fetched_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        }
        new_story = {
            **older,
            "slug": "new-ait-story",
            "source_url": "https://aitnews.com/new-story",
            "title_ar": "خبر تقني جديد",
            "summary_ar": "ملخص جديد لخبر تقني.",
            "content_ar": "تفاصيل الخبر التقني الجديد.",
            "image_url": "",
            "image_source": "none",
            "image_credit": "",
            "image_credit_url": "",
            "image_provider_url": "",
            "image_license_url": "",
            "published_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            "fetched_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(world_pulse, "_ARCHIVE_SHARED_CACHE_PATH", os.path.join(temp_dir, "archive.json")):
                with patch.object(world_pulse, "_ARCHIVE_SHARED_CACHE_MAX_STALE_SECONDS", 300):
                    with patch.object(world_pulse, "_DB_ARTICLES_CACHE", [older]):
                        with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", time.monotonic()):
                            self.assertTrue(world_pulse._merge_article_rows_into_archive_cache([updated_existing, new_story]))
                            cached = [dict(row) for row in world_pulse._DB_ARTICLES_CACHE]
                            shared = world_pulse._read_shared_archive_cache(max_age_seconds=60)

        by_url = {row["source_url"]: row for row in cached}
        saved_old = by_url[older["source_url"]]
        self.assertEqual(saved_old["title_ar"], "عنوان محرر جديد")
        self.assertEqual(saved_old["image_url"], older["image_url"])
        self.assertEqual(saved_old["image_source"], "wikimedia_relevant")
        self.assertIn(new_story["source_url"], by_url)
        self.assertIsNotNone(shared)
        self.assertEqual(len(world_pulse._DISPLAY_STORIES_CACHE), 0)

    def test_image_metadata_sync_keeps_the_archive_cache_warm(self):
        source_url = "https://aitnews.com/image-sync-story"
        stored = {
            "slug": "image-sync-story",
            "source_url": source_url,
            "source_domain": "aitnews.com",
            "source_name": "AIT News",
            "category": "technology",
            "original_language": "ar",
            "title_ar": "خبر تقني",
            "summary_ar": "ملخص قصير",
            "image_url": "",
            "image_source": "none",
            "image_credit": "",
            "image_credit_url": "",
            "image_provider_url": "",
            "image_license_url": "",
            "image_checked_at": None,
            "is_demo": False,
        }
        candidate = {
            **stored,
            "image_url": "https://images.example.test/new.jpg",
            "image_source": "wikimedia_relevant",
            "image_credit": "Creator",
            "image_credit_url": "https://commons.wikimedia.org/wiki/File:new.jpg",
            "image_provider_url": "https://commons.wikimedia.org/wiki/File:new.jpg",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_relevance_verified": True,
            "image_checked_at": datetime.now(timezone.utc),
        }
        cache_time = time.monotonic() - 1.0
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(world_pulse, "_ARCHIVE_SHARED_CACHE_PATH", os.path.join(temp_dir, "archive.json")):
                with patch.object(world_pulse, "_DB_ARTICLES_CACHE", [dict(stored)]):
                    with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", cache_time):
                        with patch.object(
                            world_pulse, "_DISPLAY_STORIES_CACHE",
                            {"ar": (time.monotonic(), [{**stored, "title": "خبر تقني", "image_fallback_url": "/static/images/fallback-ar.svg"}])},
                        ):
                            world_pulse._sync_cached_image_metadata([candidate])
                            self.assertEqual(world_pulse._DB_ARTICLES_CACHE_AT, cache_time)
                            self.assertEqual(world_pulse._DB_ARTICLES_CACHE[0]["image_url"], candidate["image_url"])
                            self.assertEqual(world_pulse._DISPLAY_STORIES_CACHE["ar"][1][0]["image_url"], candidate["image_url"])
                            self.assertEqual(
                                world_pulse._DISPLAY_STORIES_CACHE["ar"][1][0]["image_credit"],
                                "Creator",
                            )




class ProductionAuditRegressionTests(unittest.TestCase):
    def test_admin_login_accepts_unicode_password_without_500(self):
        password = "نبض-Admin-كلمةسر-2026"
        with patch.dict(os.environ, {"ADMIN_PANEL_PASSWORD": password}):
            with patch.object(world_pulse, "_ensure_background_scheduler"):
                client = world_pulse.app.test_client()
                response = client.post("/admin/login", data={"password": password})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/monitor", response.headers.get("Location", ""))

    def test_admin_login_wrong_unicode_password_returns_regular_login_page(self):
        with patch.dict(os.environ, {"ADMIN_PANEL_PASSWORD": "كلمةسر-صحيحة"}):
            with patch.object(world_pulse, "_ensure_background_scheduler"):
                response = world_pulse.app.test_client().post(
                    "/admin/login", data={"password": "كلمةسر-خاطئة"}
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("كلمة المرور غير صحيحة", response.get_data(as_text=True))

    def test_stored_story_permalink_survives_current_ingestion_allowlist_change(self):
        now = datetime.now(timezone.utc)
        archived = {
            "slug": "legacy-publisher-story",
            "source_url": "https://retired-publisher.example/news/legacy-story",
            "source_name": "Retired Publisher",
            "source_domain": "retired-publisher.example",
            "category": "world",
            "original_language": "en",
            "title_en": "A permanent archived news story",
            "title_ar": "",
            "summary_en": "The publisher reported a concrete development and supplied the main verified facts.",
            "summary_ar": "",
            "content_en": (
                "The saved report describes the development and the details available when it was published. "
                "The brief retains the source attribution and does not add names, figures, causes, or other facts "
                "that are not supported by the stored material. Readers can follow the original publisher link "
                "for subsequent updates and any additional context."
            ),
            "content_ar": "",
            "published_at": now,
            "fetched_at": now,
            "read_minutes": 1,
            "is_demo": False,
            "is_hidden": False,
        }
        with patch.object(world_pulse, "_ensure_background_scheduler"):
            with patch.object(world_pulse, "current_language", return_value="ar"):
                with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                    with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=archived) as lookup:
                        with patch.object(world_pulse, "_row_allowed_on_language_site", return_value=False):
                            with patch.object(world_pulse, "_display_category", return_value="world"):
                                with patch.object(world_pulse, "_db_fetch_related_articles", return_value=[]):
                                    with patch.object(world_pulse, "render_template", return_value="archive story rendered") as render:
                                        response = world_pulse.app.test_client().get(
                                            "/article/legacy-publisher-story?lang=ar"
                                        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), archived["source_url"])
        lookup.assert_called_once_with("legacy-publisher-story")
        render.assert_not_called()

    def test_saved_archive_permalink_rejects_mismatched_host_and_hidden_rows(self):
        base = {
            "source_url": "https://one-publisher.example/article/1",
            "source_domain": "one-publisher.example",
            "source_name": "One Publisher",
            "original_language": "en",
            "title_en": "A real archived headline",
            "category": "world",
            "is_demo": False,
            "is_hidden": False,
        }
        self.assertTrue(world_pulse._safe_saved_article_permalink(base))
        self.assertFalse(world_pulse._safe_saved_article_permalink(dict(
            base, source_url="https://another-site.example/article/1"
        )))
        self.assertFalse(world_pulse._safe_saved_article_permalink(dict(base, is_hidden=True)))

    def test_legacy_restricted_publishers_do_not_render_old_full_bodies(self):
        row = {
            "slug": "legacy-reuters-story",
            "source_url": "https://www.reuters.com/world/example-story",
            "source_name": "Reuters",
            "source_domain": "reuters.com",
            "category": "world",
            "original_language": "en",
            "title_en": "A Reuters headline",
            "title_ar": "عنوان رويترز",
            "summary_en": "A stored historic summary that is no longer eligible for article-text reuse.",
            "summary_ar": "ملخص محفوظ قديم لم يعد مؤهلاً لإعادة استخدام نص المقال.",
            "content_en": "Legacy body content. " * 20,
            "content_ar": "نص قديم للمقال. " * 30,
        }
        story = world_pulse._normalise_story(row, "ar")
        self.assertTrue(story["headline_only"])
        self.assertEqual(story["content"], "")
        self.assertTrue(story["source_only"])




class CataloguedImageMemoryCacheTests(unittest.TestCase):
    def _fake_connection(self, image_bytes):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (image_bytes, "image/jpeg")
        return connection

    def test_repeat_image_request_uses_bounded_memory_cache(self):
        image_id = "a" * 40
        image_bytes = b"licensed-image-bytes"
        connection = self._fake_connection(image_bytes)
        with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE", OrderedDict()):
            with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE_BYTES", 0):
                with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE_MAX_BYTES", 1024):
                    with patch.object(world_pulse, "_ensure_schema", return_value=True):
                        with patch.object(world_pulse, "_connect_db", return_value=connection) as connect:
                            with patch.object(world_pulse, "_release_db_connection"):
                                first = world_pulse._read_catalogued_image(image_id)
                                second = world_pulse._read_catalogued_image(image_id)

        self.assertEqual(first, (image_bytes, "image/jpeg"))
        self.assertEqual(second, first)
        connect.assert_called_once()

    def test_image_memory_cache_evicts_oldest_entry_when_byte_limit_is_reached(self):
        first_id, second_id = "1" * 40, "2" * 40
        first_bytes, second_bytes = b"123456", b"abcdef"
        first_connection = self._fake_connection(first_bytes)
        second_connection = self._fake_connection(second_bytes)
        refetched_first = self._fake_connection(first_bytes)
        with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE", OrderedDict()):
            with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE_BYTES", 0):
                with patch.object(world_pulse, "_CATALOGUED_IMAGE_MEMORY_CACHE_MAX_BYTES", 10):
                    with patch.object(world_pulse, "_ensure_schema", return_value=True):
                        with patch.object(
                            world_pulse, "_connect_db",
                            side_effect=[first_connection, second_connection, refetched_first],
                        ) as connect:
                            with patch.object(world_pulse, "_release_db_connection"):
                                self.assertEqual(
                                    world_pulse._read_catalogued_image(first_id),
                                    (first_bytes, "image/jpeg"),
                                )
                                self.assertEqual(
                                    world_pulse._read_catalogued_image(second_id),
                                    (second_bytes, "image/jpeg"),
                                )
                                self.assertEqual(
                                    world_pulse._read_catalogued_image(first_id),
                                    (first_bytes, "image/jpeg"),
                                )

        self.assertEqual(connect.call_count, 3)
        self.assertLessEqual(world_pulse._CATALOGUED_IMAGE_MEMORY_CACHE_BYTES, 10)



    def test_unverified_legacy_photo_is_replaced_with_topic_illustration(self):
        row = {
            "slug": "legacy-photo-unverified",
            "source_url": "https://www.theverge.com/2026/10/17/legacy-photo-unverified",
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "category": "technology",
            "original_language": "en",
            "title_en": "Oil tankers face new maritime blockade near Iran",
            "summary_en": "Officials described changes to tanker routes and shipping restrictions near Iran.",
            "content_en": "Officials described changes to tanker routes and shipping restrictions near Iran. The source says that the situation could affect shipping schedules and energy markets.",
            "image_url": "https://images.example.test/irrelevant-portrait.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Photographer Name",
            "image_credit_url": "https://openverse.org/image/example",
            "image_provider_url": "https://openverse.org/image/example",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_relevance_verified": False,
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertNotEqual(story["image_url"], row["image_url"])
        self.assertTrue(story["image_url"].startswith("/media/editorial.svg?"))
        self.assertEqual(story["image_source"], "editorial_generated")

    def test_topic_verified_licensed_photo_remains_visible(self):
        row = {
            "slug": "verified-photo",
            "source_url": "https://www.theverge.com/2026/10/17/verified-photo",
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "category": "technology",
            "original_language": "en",
            "title_en": "Satellite images show a tanker route",
            "summary_en": "New satellite images show changes to a tanker route.",
            "content_en": "New satellite images show changes to a tanker route. The publisher's report describes the shipping changes and their possible impact.",
            "image_url": "https://images.example.test/tanker-route.jpg",
            "image_source": "openverse_licensed",
            "image_credit": "Photographer Name",
            "image_credit_url": "https://openverse.org/image/tanker-route",
            "image_provider_url": "https://openverse.org/image/tanker-route",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_relevance_verified": True,
        }

        story = world_pulse._normalise_story(row, "en")

        self.assertEqual(story["image_url"], row["image_url"])
        self.assertEqual(story["image_source"], "openverse_licensed")

    def test_article_route_recovers_a_permalink_derived_from_source_url(self):
        source_url = "https://www.theverge.com/2026/10/17/derived-permalink"
        slug = world_pulse._slug_for_url(source_url)
        row = {
            "slug": "",
            "source_url": source_url,
            "source_name": "The Verge",
            "source_domain": "theverge.com",
            "category": "technology",
            "original_language": "en",
            "title_en": "Satellite imagery shows a new tanker route",
            "title_ar": "",
            "summary_en": "Satellite imagery shows a change in a shipping route near an important maritime passage.",
            "summary_ar": "",
            "content_en": "Satellite imagery shows a change in a shipping route near an important maritime passage. The available source excerpt says the development may affect transit planning and shipping schedules.",
            "content_ar": "",
            "image_url": "",
            "image_source": "none",
            "image_relevance_verified": False,
            "is_demo": False,
        }

        with patch.object(world_pulse, "current_language", return_value="en"):
            with patch.object(world_pulse, "_DISPLAY_STORIES_CACHE", {}):
                with patch.object(world_pulse, "_db_fetch_article_by_slug", return_value=None):
                    with patch.object(world_pulse, "_all_live_articles", return_value=[row]):
                        with patch.object(world_pulse, "_db_fetch_related_articles", return_value=[]):
                            with patch.object(world_pulse, "render_template", return_value="article recovered"):
                                response = world_pulse.app.test_client().get(f"/article/{slug}?lang=en")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "article recovered")


class AdminImageWorkflowTests(unittest.TestCase):
    def test_admin_offers_both_licensed_photo_search_and_one_click_ai_illustration(self):
        template_path = os.path.join(
            os.path.dirname(world_pulse.__file__), "templates", "admin_articles.html"
        )
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()

        self.assertIn("البحث الذكي عن صورة حقيقية مناسبة ومرخّصة", template)
        self.assertIn("ابحث تلقائيًا عن صورة مرخّصة", template)
        self.assertIn('name="action" value="retry_article_image"', template)
        self.assertIn('value="auto" selected>البحث التلقائي عن صورة حقيقية مرخّصة', template)
        self.assertIn("رفع صورة يدويًا (صورة مرخّصة أو صورة مولّدة بالذكاء الاصطناعي)", template)
        self.assertIn('name="upload_image_mode"', template)
        self.assertIn('name="ai_generated_confirmed"', template)
        self.assertIn("إنشاء صورة تلقائيًا بالذكاء الاصطناعي", template)
        self.assertIn('name="action" value="generate_ai_article_image"', template)
        self.assertIn('<option value="ai">', template)
        self.assertIn("لن تحتاج إلى كتابة وصف أو تفاصيل للصورة", template)

    def test_admin_image_search_path_explicitly_disables_image_generation(self):
        source_path = os.path.join(os.path.dirname(world_pulse.__file__), "app.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        helper_start = source.index("def _refresh_existing_article_images_job")
        helper_end = source.index("NEWS_QUEUE_STATE_KEY", helper_start)
        helper = source[helper_start:helper_end]

        self.assertIn("_enrich_article_images(candidates, force_refresh=True, allow_ai_generation=False)", helper)
        template_path = os.path.join(
            os.path.dirname(world_pulse.__file__), "templates", "admin_articles.html"
        )
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn('name="action" value="retry_article_image"', template)


class AdSenseConsentReadinessTests(unittest.TestCase):
    def test_adsense_and_ads_txt_are_disabled_by_default(self):
        with patch.dict(os.environ, {
            "ADSENSE_ENABLED": "false",
            "ADSENSE_CONSENT_READY": "false",
            "ADSENSE_PUBLISHER_ID": "",
        }):
            settings = world_pulse._adsense_settings()
            self.assertFalse(settings["enabled"])
            response = world_pulse.app.test_client().get("/ads.txt")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_data(as_text=True), "")

    def test_adsense_requires_valid_publisher_id_and_confirmed_cmp_setup(self):
        environment = {
            "ADSENSE_ENABLED": "true",
            "ADSENSE_CONSENT_READY": "false",
            "ADSENSE_PUBLISHER_ID": "ca-pub-1234567890123456",
        }
        with patch.dict(os.environ, environment):
            self.assertFalse(world_pulse._adsense_settings()["enabled"])
            self.assertEqual(world_pulse.app.test_client().get("/ads.txt").status_code, 404)

        with patch.dict(os.environ, {**environment, "ADSENSE_CONSENT_READY": "true"}):
            settings = world_pulse._adsense_settings()
            self.assertTrue(settings["enabled"])
            self.assertEqual(settings["publisher_id"], "ca-pub-1234567890123456")
            response = world_pulse.app.test_client().get("/ads.txt")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.get_data(as_text=True),
                "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0f\n",
            )

    def test_template_gates_google_ads_script_on_explicit_readiness(self):
        template_path = os.path.join(
            os.path.dirname(world_pulse.__file__), "templates", "index.html"
        )
        with open(template_path, encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn("{% if adsense_enabled %}", template)
        self.assertIn(
            "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={{ adsense_publisher_id }}",
            template,
        )
        self.assertIn("{% endif %}", template)


if __name__ == "__main__":
    unittest.main()
