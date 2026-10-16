"""Trigger the authenticated World Pulse refresh endpoint from a scheduler.

The cron process deliberately does not need Supabase or Gemini credentials. It only
holds the narrowly scoped webhook token required to ask the web service to refresh.
"""
from __future__ import annotations

import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TARGET = "https://nabd-news.onrender.com"
ENDPOINT_PATH = "/api/internal/refresh"
MIN_TOKEN_LENGTH = 32
REQUEST_TIMEOUT_SECONDS = 35
RETRY_DELAY_SECONDS = 5


def build_refresh_request(target_url: str, token: str) -> Request:
    """Build a POST request without putting the secret in the URL or logs."""
    base = (target_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("NEWS_REFRESH_TARGET_URL must use HTTPS")
    url = base if base.endswith(ENDPOINT_PATH) else base + ENDPOINT_PATH
    return Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "WorldPulse-ScheduledRefresh/1.0",
        },
    )


def trigger_refresh(target_url: str, token: str) -> int:
    """Send the refresh request, retrying only transient transport/server failures."""
    if len((token or "").strip()) < MIN_TOKEN_LENGTH:
        print("ERROR: NEWS_REFRESH_WEBHOOK_TOKEN is missing or too short.", file=sys.stderr)
        return 2

    try:
        req = build_refresh_request(target_url, token.strip())
    except ValueError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2

    for attempt in range(2):
        try:
            with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status = int(response.getcode())
                body = response.read(2048).decode("utf-8", errors="replace").strip()
            print("World Pulse refresh request: HTTP %d %s" % (status, body[:1000]))
            return 0 if 200 <= status < 300 else 1
        except HTTPError as exc:
            body = exc.read(2048).decode("utf-8", errors="replace").strip()
            transient = exc.code in {502, 503, 504}
            print("World Pulse refresh request: HTTP %d %s" % (exc.code, body[:1000]), file=sys.stderr)
            if transient and attempt == 0:
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            return 1
        except (URLError, TimeoutError, OSError) as exc:
            # Do not print request headers (which contain the webhook token).
            print("World Pulse refresh transport error: %s" % type(exc).__name__, file=sys.stderr)
            if attempt == 0:
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            return 1

    return 1


def main() -> int:
    target = os.getenv("NEWS_REFRESH_TARGET_URL", DEFAULT_TARGET)
    token = os.getenv("NEWS_REFRESH_WEBHOOK_TOKEN", "")
    return trigger_refresh(target, token)


if __name__ == "__main__":
    raise SystemExit(main())
