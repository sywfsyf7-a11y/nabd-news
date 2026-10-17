"""Regression coverage for the read-only, archive-wide content and image audit."""
import unittest
from datetime import datetime, timedelta, timezone

from app import _content_quality_audit_issues


class ContentQualityAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
        self.cached_id = "a" * 40
        self.good_row = {
            "slug": "nasa-asteroid-mission",
            "source_url": "https://www.nasa.gov/news-release/asteroid-mission",
            "category": "science",
            "source_name": "NASA",
            "source_domain": "nasa.gov",
            "image_url": f"/media/catalogued/{self.cached_id}",
            "image_source": "wikimedia_relevant",
            "image_credit": "Wikimedia Commons contributor",
            "image_credit_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
            "image_provider_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
            "image_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "image_checked_at": self.now - timedelta(minutes=30),
            "title_en": "NASA announces a new spacecraft mission to study a distant asteroid",
            "summary_en": "The agency outlined the mission schedule and the instruments that will study the asteroid.",
            "content_en": (
                "NASA announced a spacecraft mission designed to study a distant asteroid in detail. "
                "The spacecraft will map the surface and measure the object's composition before the "
                "team selects a sequence of close observations. Engineers are preparing the instruments "
                "and expect to publish additional mission milestones after the next review."
            ),
            "title_ar": "ناسا تعلن مهمة فضائية جديدة لدراسة كويكب بعيد",
            "summary_ar": "أعلنت الوكالة جدول المهمة والأدوات التي ستساعد على دراسة الكويكب.",
            "content_ar": (
                "أعلنت وكالة ناسا عن مهمة فضائية تهدف إلى دراسة كويكب بعيد بالتفصيل. "
                "وستعمل المركبة على رسم خرائط للسطح وقياس مكونات الجسم قبل أن يحدد الفريق "
                "مجموعة من الملاحظات القريبة. ويستعد المهندسون للأدوات العلمية، مع توقع نشر "
                "مراحل إضافية للمهمة بعد المراجعة المقبلة."
            ),
            "published_at": self.now - timedelta(hours=1),
            "fetched_at": self.now - timedelta(hours=1),
            "original_language": "en",
            "is_demo": False,
        }

    def test_complete_allowlisted_article_and_cached_licensed_image_pass(self):
        self.assertEqual(
            _content_quality_audit_issues(self.good_row, {self.cached_id}, now=self.now),
            [],
        )

    def test_legacy_feed_label_and_A_E_image_are_flagged(self):
        row = {
            "slug": "legacy-section-label",
            "source_url": "https://www.nintendolife.com/news",
            "category": "gaming",
            "source_name": "Nintendo Life",
            "source_domain": "nintendolife.com",
            "image_url": "/static/E.jpg",
            "image_source": "fallback_en",
            "title_en": "Latest Nintendo Life News",
            "summary_en": "",
            "content_en": "",
            "original_language": "en",
            "is_demo": False,
            "published_at": self.now - timedelta(days=2),
            "fetched_at": self.now - timedelta(days=2),
        }
        issues = set(_content_quality_audit_issues(row, set(), now=self.now))
        self.assertIn("publisher_section_title", issues)
        self.assertIn("legacy_A_E_fallback_image", issues)
        self.assertIn("missing_native_summary", issues)
        self.assertIn("native_body_under_180_characters", issues)

    def test_missing_cached_image_blob_and_untrusted_remote_image_are_flagged(self):
        row = dict(self.good_row)
        row["image_url"] = f"/media/catalogued/{'b' * 40}"
        self.assertIn(
            "catalogued_image_bytes_missing",
            _content_quality_audit_issues(row, {self.cached_id}, now=self.now),
        )
        row["image_url"] = "https://images.example.invalid/photo.jpg"
        row["image_source"] = "unknown_provider"
        self.assertIn(
            "image_url_without_trusted_provider",
            _content_quality_audit_issues(row, {self.cached_id}, now=self.now),
        )

    def test_demo_rows_are_counted_but_not_treated_as_live_content_issues(self):
        row = dict(self.good_row)
        row["is_demo"] = True
        self.assertEqual(_content_quality_audit_issues(row, {self.cached_id}, now=self.now), ["demo_record"])


if __name__ == "__main__":
    unittest.main()
