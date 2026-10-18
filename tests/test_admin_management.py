"""Regression tests for the protected admin archive and reversible moderation."""
import unittest
from unittest.mock import MagicMock, patch

import app as world_pulse


class AdminArchiveManagementTests(unittest.TestCase):
    def _logged_in_session(self, client):
        with client.session_transaction() as sess:
            sess["wp_admin_authenticated"] = True
            sess["wp_admin_csrf"] = "test-csrf-token"

    def test_admin_root_redirects_to_login_when_not_authenticated(self):
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            response = world_pulse.app.test_client().get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

    def test_admin_archive_is_not_exposed_when_password_is_unconfigured(self):
        with patch.object(world_pulse, "_admin_enabled", return_value=False):
            response = world_pulse.app.test_client().get("/admin/articles")
        self.assertEqual(response.status_code, 404)

    def test_logged_in_admin_can_open_archive_manager(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_list_articles", return_value=([], 0, "")):
                response = client.get("/admin/articles")
        self.assertEqual(response.status_code, 200)
        self.assertIn("إدارة الأخبار والأرشيف", response.get_data(as_text=True))
        self.assertIn("إضافة خبر جديد", response.get_data(as_text=True))

    def test_custom_sections_are_included_in_the_category_registry(self):
        with patch.object(world_pulse, "_get_custom_categories", return_value={
            "movies": {"ar": "أفلام", "en": "Movies", "is_custom": True}
        }):
            names = world_pulse._all_category_names()
        self.assertEqual(names["movies"], {"ar": "أفلام", "en": "Movies"})
        self.assertIn("movies", names)
        self.assertTrue(world_pulse._is_custom_category("movies"))

    def test_admin_archive_shows_custom_section_creation_form(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_list_articles", return_value=([], 0, "")):
                with patch.object(world_pulse, "_get_custom_categories", return_value={}):
                    response = client.get("/admin/articles")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("إضافة قسم جديد للموقع", html)
        self.assertIn('name="action" value="create_category"', html)
        self.assertIn('name="name_ar"', html)
        self.assertIn('name="name_en"', html)

    def test_custom_category_post_requires_csrf_and_persists_through_helper(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_create_custom_category", return_value="created") as create:
                response = client.post("/admin/articles", data={
                    "csrf_token": "test-csrf-token",
                    "action": "create_category",
                    "name_ar": "أفلام",
                    "name_en": "Movies",
                    "category_key": "movies",
                })
        self.assertEqual(response.status_code, 302)
        create.assert_called_once_with("أفلام", "Movies", "movies")
        with client.session_transaction() as sess:
            self.assertIn("تم إنشاء القسم", sess["wp_admin_notice"])

    def test_custom_category_stories_can_be_rendered_with_source_and_language_checks(self):
        row = {
            "category": "movies",
            "original_language": "ar",
            "source_domain": "film-news.example",
            "source_name": "Film News",
            "source_url": "https://film-news.example/story",
            "title_ar": "خبر جديد عن السينما",
            "summary_ar": "أعلنت الجهة المنظمة موعدًا جديدًا لعرض الفيلم في المهرجان.",
            "content_ar": "تتضمن المادة تفاصيل موثقة عن العرض والموعد والجهة المنظمة، مع إحالة القارئ إلى المصدر الأصلي للمزيد من المعلومات.",
        }
        with patch.object(world_pulse, "_get_custom_categories", return_value={
            "movies": {"ar": "أفلام", "en": "Movies", "is_custom": True}
        }):
            self.assertTrue(world_pulse._row_allowed_on_language_site(row, "ar"))

    def test_admin_post_requires_csrf_before_archive_mutation(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_set_article_hidden") as hide:
                response = client.post("/admin/articles", data={
                    "action": "hide_article",
                    "slug": "story-to-hide",
                })
        self.assertEqual(response.status_code, 400)
        hide.assert_not_called()

    def test_hide_action_is_reversible_and_preserves_current_list_filters(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_set_article_hidden", return_value=True) as hide:
                response = client.post(
                    "/admin/articles?q=energy&category=world&show_hidden=0&page=2",
                    data={
                        "csrf_token": "test-csrf-token",
                        "action": "hide_article",
                        "slug": "story-to-hide",
                    },
                )
        self.assertEqual(response.status_code, 302)
        hide.assert_called_once_with("story-to-hide", True)
        location = response.headers["Location"]
        self.assertIn("q=energy", location)
        self.assertIn("category=world", location)
        self.assertIn("show_hidden=1", location)
        with client.session_transaction() as sess:
            self.assertIn("الاحتفاظ به في الأرشيف", sess["wp_admin_notice"])

    def test_manual_audit_page_renders_saved_report_without_running_new_audit(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        report = {
            "status": "complete",
            "updated_at": None,
            "report": {
                "total_articles": 240,
                "demo_records": 0,
                "issue_counts": {"missing_article_image": 2},
                "issue_samples": {"missing_article_image": ["story-example"]},
                "language_counts": {"ar": 120, "en": 120},
                "category_counts": {"world": 50},
                "catalogued_images": {"total_images": 40, "total_bytes": 1000000, "unreferenced_cached_images": 0},
            },
            "error": "",
        }
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_read_archive_audit_report", return_value=report):
                with patch.object(world_pulse, "_run_content_quality_audit_once") as audit:
                    response = client.get("/admin/audit")
        self.assertEqual(response.status_code, 200)
        self.assertIn("240", response.get_data(as_text=True))
        audit.assert_not_called()

    def test_hide_prunes_the_shared_and_local_warm_archive_snapshot(self):
        hidden = {"slug": "story-to-hide", "source_url": "https://example.test/hidden"}
        visible = {"slug": "story-visible", "source_url": "https://example.test/visible"}
        cached_rows = [hidden, visible]
        memory = {hidden["source_url"]: dict(hidden)}

        with patch.object(world_pulse, "_DB_ARTICLES_CACHE", cached_rows):
            with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", world_pulse.time.monotonic()):
                with patch.object(world_pulse, "_read_shared_archive_cache", return_value=(cached_rows, 0.01)):
                    with patch.object(world_pulse, "_write_shared_archive_cache") as write_shared:
                        with patch.object(world_pulse, "_archive_file_lock", return_value=MagicMock()):
                            with patch.object(world_pulse, "_archive_unlock"):
                                with patch.object(world_pulse, "_MEMORY_ARTICLES", memory):
                                    world_pulse._remove_article_from_archive_cache("story-to-hide")

        self.assertEqual([row["slug"] for row in write_shared.call_args.args[0]], ["story-visible"])
        self.assertNotIn(hidden["source_url"], memory)

    def test_hide_from_a_cold_worker_does_not_create_an_empty_shared_archive(self):
        with patch.object(world_pulse, "_DB_ARTICLES_CACHE", None):
            with patch.object(world_pulse, "_DB_ARTICLES_CACHE_AT", 0.0):
                with patch.object(world_pulse, "_read_shared_archive_cache", return_value=None):
                    with patch.object(world_pulse, "_write_shared_archive_cache") as write_shared:
                        with patch.object(world_pulse, "_archive_file_lock", return_value=MagicMock()):
                            with patch.object(world_pulse, "_archive_unlock"):
                                world_pulse._remove_article_from_archive_cache("story-to-hide")
        write_shared.assert_not_called()

    def test_soft_hide_updates_visibility_flag_and_never_deletes_article(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.rowcount = 1
        with patch.object(world_pulse, "_ensure_schema", return_value=True):
            with patch.object(world_pulse, "_connect_db", return_value=connection):
                with patch.object(world_pulse, "_invalidate_db_articles_cache"):
                    with patch.object(world_pulse, "_release_db_connection"):
                        result = world_pulse._admin_set_article_hidden("story-to-hide", True)
        self.assertTrue(result)
        sql = cursor.execute.call_args.args[0].casefold()
        self.assertIn("update world_pulse_articles", sql)
        self.assertIn("set is_hidden", sql)
        self.assertNotIn("delete from world_pulse_articles", sql)
        self.assertEqual(cursor.execute.call_args.args[1], (True, "story-to-hide"))
        connection.commit.assert_called_once()



    def test_admin_article_editor_exposes_image_upload_and_rights_fields(self):
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_list_articles", return_value=([], 0, "")):
                with patch.object(world_pulse, "_admin_fetch_article_by_slug", return_value={
                    "slug": "story-photo", "title_ar": "عنوان", "title_en": "Headline",
                    "original_language": "ar", "source_url": "https://publisher.example/story",
                    "source_name": "Example", "source_domain": "publisher.example",
                    "category": "world", "is_hidden": False, "headline_only": False,
                    "image_url": "", "image_source": "none",
                    "image_credit": "", "image_credit_url": "", "image_license_url": "",
                }):
                    response = client.get("/admin/articles?edit=story-photo")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="image_file"', html)
        self.assertIn('name="image_credit_url"', html)
        self.assertIn('name="image_license_url"', html)
        self.assertIn('name="rights_confirmed"', html)
        self.assertIn('حفظ الصورة وبيانات الحقوق', html)

    def test_admin_image_upload_action_requires_csrf(self):
        import io
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (400, 240), "navy").save(buffer, format="JPEG")
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_store_uploaded_image") as save_image:
                response = client.post("/admin/articles?edit=story-photo", data={
                    "action": "save_article_image",
                    "slug": "story-photo",
                    "rights_confirmed": "yes",
                    "image_credit": "Photographer",
                    "image_credit_url": "https://images.example/photo",
                    "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "image_file": (io.BytesIO(buffer.getvalue()), "photo.jpg"),
                }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        save_image.assert_not_called()

    def test_admin_image_upload_passes_rights_metadata_to_persistent_store(self):
        import io
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (400, 240), "navy").save(buffer, format="JPEG")
        client = world_pulse.app.test_client()
        self._logged_in_session(client)
        article = {
            "slug": "story-photo", "title_ar": "عنوان", "title_en": "Headline",
            "original_language": "ar", "source_url": "https://publisher.example/story",
            "source_name": "Example", "source_domain": "publisher.example",
            "category": "world", "is_hidden": False, "headline_only": False,
        }
        with patch.object(world_pulse, "_admin_enabled", return_value=True):
            with patch.object(world_pulse, "_admin_fetch_article_by_slug", return_value=article):
                with patch.object(world_pulse, "_admin_store_uploaded_image", return_value="saved") as save_image:
                    response = client.post("/admin/articles?edit=story-photo", data={
                        "csrf_token": "test-csrf-token",
                        "action": "save_article_image",
                        "slug": "story-photo",
                        "rights_confirmed": "yes",
                        "image_credit": "Example photographer",
                        "image_credit_url": "https://images.example/photo",
                        "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "image_file": (io.BytesIO(buffer.getvalue()), "photo.jpg"),
                    }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        save_image.assert_called_once_with(
            "story-photo",
            buffer.getvalue(),
            "Example photographer",
            "https://images.example/photo",
            "https://creativecommons.org/licenses/by/4.0/",
        )
        with client.session_transaction() as sess:
            self.assertIn("تم حفظ الصورة بصورة محسّنة", sess["wp_admin_notice"])

    def test_persistent_image_upload_rejects_missing_credit_and_bad_image_data(self):
        self.assertEqual(
            world_pulse._admin_store_uploaded_image(
                "story", b"not-an-image", "", "https://images.example/item",
                "https://creativecommons.org/licenses/by/4.0/",
            ),
            "invalid_image",
        )
        self.assertEqual(
            world_pulse._admin_store_uploaded_image(
                "story", b"not-an-image", "Creator", "http://images.example/item",
                "https://creativecommons.org/licenses/by/4.0/",
            ),
            "invalid_image",
        )

if __name__ == "__main__":
    unittest.main()
