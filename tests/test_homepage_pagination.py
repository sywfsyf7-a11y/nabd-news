"""Regression tests for homepage pagination and reduced initial rendering payload."""
import unittest
from unittest.mock import patch

import app as world_pulse


class HomepagePaginationTests(unittest.TestCase):
    def test_homepage_shows_only_one_page_and_keeps_older_stories_navigable(self):
        items = [
            {"slug": f"story-{i}", "category": "world", "title": f"Story {i}"}
            for i in range(1, 61)
        ]
        with patch.object(world_pulse, "_maybe_start_refresh"):
            with patch.object(world_pulse, "current_language", return_value="en"):
                with patch.object(world_pulse, "_get_display_stories", return_value=items):
                    with patch.object(world_pulse, "render_template", return_value="home rendered") as render:
                        response = world_pulse.app.test_client().get("/?lang=en&page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "home rendered")
        kwargs = render.call_args.kwargs
        self.assertEqual(len(kwargs["stories"]), 24)
        self.assertEqual(kwargs["stories"][0]["slug"], "story-25")
        self.assertEqual(kwargs["stories"][-1]["slug"], "story-48")
        self.assertEqual(kwargs["home_page"], 2)
        self.assertEqual(kwargs["home_pages"], 3)
        self.assertEqual(kwargs["home_total_stories"], 60)

    def test_invalid_homepage_page_number_is_clamped_safely(self):
        items = [
            {"slug": f"story-{i}", "category": "world", "title": f"Story {i}"}
            for i in range(1, 30)
        ]
        with patch.object(world_pulse, "_maybe_start_refresh"):
            with patch.object(world_pulse, "current_language", return_value="en"):
                with patch.object(world_pulse, "_get_display_stories", return_value=items):
                    with patch.object(world_pulse, "render_template", return_value="home rendered") as render:
                        response = world_pulse.app.test_client().get("/?lang=en&page=999")

        self.assertEqual(response.status_code, 200)
        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["home_page"], 2)
        self.assertEqual(len(kwargs["stories"]), 5)

    def test_pagination_controls_are_present_in_the_home_template(self):
        template = world_pulse.app.jinja_env.get_template("index.html")
        source = template.source
        self.assertIn("News pagination", source)
        self.assertIn("home_page + 1", source)
        self.assertIn("home_page - 1", source)


if __name__ == "__main__":
    unittest.main()
