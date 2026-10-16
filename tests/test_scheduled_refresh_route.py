"""Tests for the token-protected external news-refresh endpoint."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import app as world_pulse


class ScheduledRefreshRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = world_pulse.app.test_client()
        self.old_auto_fetch = world_pulse.NEWS_AUTO_FETCH
        self.old_scheduler_enabled = world_pulse.NEWS_SCHEDULER_ENABLED
        self.old_attempt = world_pulse._LAST_REFRESH_ATTEMPT
        self.old_refreshing = world_pulse._REFRESHING
        self.old_state = world_pulse._LAST_REFRESH_STATE
        self.old_error = world_pulse._LAST_REFRESH_ERROR
        world_pulse.NEWS_AUTO_FETCH = True
        world_pulse.NEWS_SCHEDULER_ENABLED = False
        world_pulse._LAST_REFRESH_ATTEMPT = 0.0
        world_pulse._REFRESHING = False
        world_pulse._LAST_REFRESH_STATE = "idle"
        world_pulse._LAST_REFRESH_ERROR = ""

    def tearDown(self):
        world_pulse.NEWS_AUTO_FETCH = self.old_auto_fetch
        world_pulse.NEWS_SCHEDULER_ENABLED = self.old_scheduler_enabled
        world_pulse._LAST_REFRESH_ATTEMPT = self.old_attempt
        world_pulse._REFRESHING = self.old_refreshing
        world_pulse._LAST_REFRESH_STATE = self.old_state
        world_pulse._LAST_REFRESH_ERROR = self.old_error

    def test_wrong_token_is_not_disclosed(self):
        with patch.object(world_pulse, "NEWS_REFRESH_WEBHOOK_TOKEN", "s" * 48):
            response = self.client.post(
                "/api/internal/refresh",
                headers={"Authorization": "Bearer " + "x" * 48},
            )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"token", response.data.lower())

    def test_missing_server_token_fails_closed(self):
        with patch.object(world_pulse, "NEWS_REFRESH_WEBHOOK_TOKEN", ""):
            response = self.client.post("/api/internal/refresh")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["state"], "not_configured")

    def test_valid_token_starts_a_refresh(self):
        token = "r" * 48
        with patch.object(world_pulse, "NEWS_REFRESH_WEBHOOK_TOKEN", token):
            with patch.object(world_pulse.threading.Thread, "start") as start:
                response = self.client.post(
                    "/api/internal/refresh",
                    headers={"Authorization": "Bearer " + token},
                )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["state"], "started")
        start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
