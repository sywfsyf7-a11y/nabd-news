"""Regression tests for fast article navigation and distinct editorial fields."""
import unittest
import os
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import app as world_pulse


class SiteExperienceTests(unittest.TestCase):
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


    def test_missing_photo_uses_language_specific_brand_fallback(self):
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

        self.assertEqual(english["image_url"], "/static/E.jpg")
        self.assertEqual(english["image_fallback_url"], "/static/E.jpg")
        self.assertEqual(english["image_source"], "fallback_en")
        self.assertEqual(arabic["image_url"], "/static/A.jpg")
        self.assertEqual(arabic["image_fallback_url"], "/static/A.jpg")
        self.assertEqual(arabic["image_source"], "fallback_ar")


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
            "source_url": "https://www.reuters.com/example-story",
            "category": "economy",
            "source_name": "Reuters",
            "source_domain": "reuters.com",
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

    def test_article_route_builds_the_display_pool_only_once(self):
        stories = [
            {"slug": "story-one", "category": "technology", "title": "Short title"},
            {"slug": "story-two", "category": "technology", "title": "Related story"},
        ]
        with patch.object(world_pulse, "_get_display_stories", return_value=stories) as pool:
            with patch.object(world_pulse, "_find_article", side_effect=AssertionError("duplicate DB scan")):
                with patch.object(world_pulse, "render_template", return_value="article rendered"):
                    response = world_pulse.app.test_client().get("/article/story-one?lang=en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "article rendered")
        pool.assert_called_once_with("en")

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
                    ("news:world:ar:cnn.com", False),
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
                    self.assertFalse(world_pulse._control_enabled("news:world:ar:cnn.com"))
                    self.assertFalse(world_pulse._control_enabled("image:openverse_licensed"))
                    # An unset source retains the current default-on behavior.
                    self.assertTrue(world_pulse._control_enabled("news:world:ar:petra.gov.jo"))
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
                    with patch.object(world_pulse, "_collect_rss_articles", return_value=[dict(raw)]):
                        with patch.object(world_pulse, "_db_fetch_articles_needing_editorial", return_value=[]):
                            with patch.object(world_pulse, "_db_fetch_all", return_value=[]):
                                with patch.object(world_pulse, "_translate_batch", return_value={0: translation}):
                                    with patch.object(world_pulse, "_db_upsert_many", side_effect=save_news):
                                        with patch.object(world_pulse, "_enrich_article_images", side_effect=enrich):
                                            with patch.object(world_pulse, "_avoid_repeated_news_photos"):
                                                with patch.object(world_pulse, "_db_update_article_images", return_value=1) as image_update:
                                                    with patch.object(world_pulse, "_backfill_missing_article_images", return_value=0):
                                                        world_pulse._refresh_news_job()
        self.assertEqual(events, ["save", "images"])
        image_update.assert_called_once()
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
            world_pulse._invalidate_db_articles_cache()
            world_pulse._get_display_stories("ar")
            self.assertEqual(builder.call_count, 2)

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
        self.assertNotIn("_image_relevance_score", result)

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
        }
        with patch.object(world_pulse, "_db_fetch_all", return_value=[stored]):
            with patch.object(world_pulse, "_control_enabled", return_value=True):
                with patch.object(world_pulse, "_search_any_reusable_image", return_value=new_result):
                    world_pulse._enrich_article_images([raw], force_refresh=True, allow_ai_generation=False)

        self.assertEqual(raw["image_url"], new_result["image_url"])
        self.assertEqual(raw["image_credit"], "New photographer")
        self.assertEqual(raw["image_source"], "openverse_licensed")


if __name__ == "__main__":
    unittest.main()
