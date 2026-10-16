"""Unit tests for the standalone scheduled-refresh trigger."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import trigger_news_refresh


class FakeResponse:
    def __init__(self, status=202, body=b'{"state":"started"}'):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, _limit=-1):
        return self.body


class TriggerRefreshTests(unittest.TestCase):
    def test_request_uses_bearer_header_and_no_token_in_url(self):
        token = "x" * 48
        req = trigger_news_refresh.build_refresh_request(
            "https://nabd-news.onrender.com/", token
        )
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://nabd-news.onrender.com/api/internal/refresh")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + token)
        self.assertNotIn(token, req.full_url)

    def test_rejects_non_https_target(self):
        with self.assertRaises(ValueError):
            trigger_news_refresh.build_refresh_request("http://example.com", "x" * 48)

    def test_missing_token_fails_before_network_call(self):
        with patch("trigger_news_refresh.urlopen") as opener:
            result = trigger_news_refresh.trigger_refresh("https://example.com", "")
        self.assertEqual(result, 2)
        opener.assert_not_called()

    def test_accepted_request_is_success(self):
        token = "t" * 48
        with patch("trigger_news_refresh.urlopen", return_value=FakeResponse()) as opener:
            result = trigger_news_refresh.trigger_refresh("https://example.com", token)
        self.assertEqual(result, 0)
        opener.assert_called_once()
        args, kwargs = opener.call_args
        self.assertIsInstance(args[0], Request)
        self.assertEqual(kwargs["timeout"], trigger_news_refresh.REQUEST_TIMEOUT_SECONDS)

    def test_auth_error_is_not_retried(self):
        token = "t" * 48
        error = HTTPError(
            "https://example.com/api/internal/refresh", 404, "Not found", {},
            io.BytesIO(b'{"error":"not_found"}')
        )
        with patch("trigger_news_refresh.urlopen", side_effect=error) as opener:
            result = trigger_news_refresh.trigger_refresh("https://example.com", token)
        self.assertEqual(result, 1)
        opener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
