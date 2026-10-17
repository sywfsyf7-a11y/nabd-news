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


if __name__ == "__main__":
    unittest.main()
