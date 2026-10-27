"""Additive public JSON API for Nabd News mobile clients.

The registration function receives the already initialized Flask app and the existing
application namespace. Database calls are delegated to the app's bounded connection
layer; this module never creates its own PostgreSQL connections.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone, timedelta
from functools import wraps
import json
import logging
import os
import re
import secrets
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Response, request

logger = logging.getLogger("nabd_news.public_api_v1")

_API_CACHE_TTL_SECONDS = 60
_API_CACHE_MAX_ENTRIES = 256
_API_RATE_WINDOW_SECONDS = 60
_API_CACHE: OrderedDict[tuple[Any, ...], tuple[float, bytes, str]] = OrderedDict()
_API_CACHE_LOCK = threading.Lock()
_API_CACHE_MISS_LOCKS: dict[tuple[Any, ...], threading.Lock] = {}
_API_RATE_BUCKETS: dict[tuple[str, str, int], int] = {}
_API_RATE_LOCK = threading.Lock()
_API_DIGEST_SEND_LOCK = threading.Lock()
_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 12
_VALID_TOKEN_PREFIXES = ("ExponentPushToken[", "ExpoPushToken[")


def _json_response(payload: Any, status: int = 200, *, cacheable: bool = False) -> Response:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    response = Response(body, status=status, content_type="application/json; charset=utf-8")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = (
        f"public, max-age={_API_CACHE_TTL_SECONDS}" if cacheable else "no-store"
    )
    return response


def _json_error(code: str, message: str, status: int) -> Response:
    return _json_response({"error": {"code": code, "message": message}}, status=status)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _iso_utc(value: Any) -> str | None:
    if value is None or value == "":
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_positive_int(name: str, default: int, *, minimum: int, maximum: int) -> tuple[int | None, Response | None]:
    raw = request.args.get(name)
    if raw is None:
        return default, None
    if not re.fullmatch(r"[0-9]+", raw.strip()):
        return None, _json_error("invalid_parameter", f"{name} must be an integer.", 400)
    value = int(raw)
    if value < minimum or value > maximum:
        return None, _json_error(
            "invalid_parameter",
            f"{name} must be between {minimum} and {maximum}.",
            400,
        )
    return value, None


def _request_lang(*, required: bool = True) -> tuple[str | None, Response | None]:
    value = (request.args.get("lang") or "").strip().lower()
    if not value and not required:
        return None, None
    if value not in {"ar", "en"}:
        return None, _json_error(
            "invalid_parameter",
            "lang is required and must be either 'ar' or 'en'.",
            400,
        )
    return value, None


def _valid_categories(raw: str | None) -> tuple[list[str] | None, Response | None]:
    categories = (raw or "").split(",") if raw is not None else []
    categories = [value.strip().lower() for value in categories if value.strip()]
    allowed = set(_deps["CATEGORY_NAMES"])
    invalid = sorted(set(categories) - allowed)
    if invalid:
        return None, _json_error(
            "invalid_parameter",
            "Unknown category slug(s): " + ", ".join(invalid),
            400,
        )
    return list(dict.fromkeys(categories)), None


def _api_client_ip() -> str:
    # Render supplies the client address through the forwarded-address chain.
    # Use Flask's parsed access_route instead of the shared reverse-proxy address.
    try:
        chain = request.access_route
        if chain:
            # Reverse proxies append the connected client to the right of any supplied
            # X-Forwarded-For values; using the last hop avoids the easy leftmost spoof.
            return str(chain[-1])[:80]
    except Exception:
        pass
    return str(request.remote_addr or "unknown")[:80]


def _rate_limited(limit: int):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            bucket = int(time.monotonic() // _API_RATE_WINDOW_SECONDS)
            key = (fn.__name__, _api_client_ip(), bucket)
            with _API_RATE_LOCK:
                count = _API_RATE_BUCKETS.get(key, 0)
                if count >= limit:
                    response = _json_error(
                        "rate_limit_exceeded",
                        f"Too many requests. Limit: {limit} per minute.",
                        429,
                    )
                    response.headers["Retry-After"] = str(
                        _API_RATE_WINDOW_SECONDS - int(time.monotonic() % _API_RATE_WINDOW_SECONDS)
                    )
                    return response
                _API_RATE_BUCKETS[key] = count + 1
                if len(_API_RATE_BUCKETS) > 10000:
                    for old_key in list(_API_RATE_BUCKETS):
                        if old_key[2] < bucket - 1:
                            _API_RATE_BUCKETS.pop(old_key, None)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def _cached_get(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        key = (request.path, tuple(sorted(request.args.items(multi=True))))

        def cached_response() -> Response | None:
            now = time.monotonic()
            with _API_CACHE_LOCK:
                cached = _API_CACHE.get(key)
                if cached and now - cached[0] < _API_CACHE_TTL_SECONDS:
                    _API_CACHE.move_to_end(key)
                    response = Response(cached[1], status=200, content_type=cached[2])
                    response.headers["Cache-Control"] = f"public, max-age={_API_CACHE_TTL_SECONDS}"
                    response.headers["X-Content-Type-Options"] = "nosniff"
                    return response
                if cached:
                    _API_CACHE.pop(key, None)
                return None

        hit = cached_response()
        if hit is not None:
            return hit
        with _API_CACHE_LOCK:
            miss_lock = _API_CACHE_MISS_LOCKS.setdefault(key, threading.Lock())
        # Coalesce concurrent cold requests for the same URL so a cache miss cannot
        # fan out into repeated search queries or connection attempts in both threads.
        with miss_lock:
            hit = cached_response()
            if hit is not None:
                return hit
            response = fn(*args, **kwargs)
            if not isinstance(response, Response) or response.status_code != 200:
                return response
            response.headers["Cache-Control"] = f"public, max-age={_API_CACHE_TTL_SECONDS}"
            body = response.get_data()
            content_type = response.headers.get("Content-Type", "application/json; charset=utf-8")
            with _API_CACHE_LOCK:
                _API_CACHE[key] = (time.monotonic(), body, content_type)
                _API_CACHE.move_to_end(key)
                while len(_API_CACHE) > _API_CACHE_MAX_ENTRIES:
                    _API_CACHE.popitem(last=False)
                _API_CACHE_MISS_LOCKS.pop(key, None)
            return response
    return wrapped


def _sort_datetime(row: dict[str, Any]) -> datetime:
    value = row.get("published_at") or row.get("fetched_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            value = None
    if not isinstance(value, datetime):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _api_source_row_allowed(row: dict[str, Any], lang: str) -> bool:
    if row.get("is_demo") or row.get("is_hidden"):
        return False
    try:
        return bool(_deps["_story_allowed_in_display_language"](row, lang))
    except Exception:
        return False


def _api_image(story: dict[str, Any]) -> dict[str, Any] | None:
    trusted_sources = _deps["TRUSTED_REUSABLE_IMAGE_SOURCES"]
    image_source = str(story.get("image_source") or "")
    if image_source not in trusted_sources:
        return None
    if not story.get("image_relevance_verified") or not _deps["_image_license_verified"](story):
        return None
    image_url = str(story.get("image_url") or "").strip()
    license_url = str(story.get("image_license_url") or "").strip()
    source_page_url = str(
        story.get("image_provider_url") or story.get("image_credit_url") or ""
    ).strip()
    if image_url.startswith("/"):
        image_url = _deps["_site_origin"]().rstrip("/") + image_url
    if (
        not image_url.startswith("https://")
        or not license_url.startswith("https://")
        or not source_page_url.startswith("https://")
    ):
        return None
    return {
        "url": image_url,
        "credit": str(story.get("image_credit") or ""),
        "license": _deps["_image_license_label"](license_url, image_source),
        "license_url": license_url,
        "source_page_url": source_page_url,
    }


def _article_object(row: dict[str, Any], lang: str) -> dict[str, Any] | None:
    if not _api_source_row_allowed(row, lang):
        return None
    try:
        story = _deps["_normalise_story"](row, lang)
    except Exception:
        return None
    title = str(story.get("title") or "").strip()
    if not title:
        return None
    category = str(story.get("category") or "world")
    if category not in _deps["CATEGORY_NAMES"]:
        category = "world"
    headline_only = bool(story.get("headline_only"))
    source_only = bool(story.get("source_only"))
    summary = None if headline_only else (str(story.get("summary") or "").strip() or None)
    display_lang = str(story.get("display_language") or lang)
    return {
        "slug": str(story.get("slug") or ""),
        "title": title,
        "summary": summary,
        "category_slug": category,
        "category_label": _deps["CATEGORY_NAMES"][category][display_lang if display_lang in {"ar", "en"} else lang],
        "lang": display_lang if display_lang in {"ar", "en"} else lang,
        "source_name": str(story.get("source_name") or ""),
        "source_url": str(story.get("source_url") or ""),
        "published_at": _iso_utc(story.get("published_at") or story.get("fetched_at")),
        "read_minutes": max(1, min(60, int(story.get("read_minutes") or 1))),
        "headline_only": headline_only,
        "ai_generated": bool(not headline_only and not source_only),
        "image": None if headline_only else _api_image(story),
    }


def _list_api_articles(lang: str, *, category: str | None = None) -> list[dict[str, Any]]:
    try:
        rows = _deps["_db_fetch_all"]()
    except Exception:
        logger.exception("API article list failed to read archive snapshot")
        rows = []
    rows = sorted(rows, key=_sort_datetime, reverse=True)
    items: list[dict[str, Any]] = []
    for row in rows:
        if category and row.get("category") != category:
            continue
        item = _article_object(row, lang)
        if item is not None:
            items.append(item)
    return items


def _paginate(items: list[dict[str, Any]], page: int, per_page: int) -> dict[str, Any]:
    start = (page - 1) * per_page
    selected = items[start:start + per_page]
    return {
        "items": selected,
        "page": page,
        "per_page": per_page,
        "has_more": start + len(selected) < len(items),
    }


def _digest_items_from_rows(
    rows: list[dict[str, Any]],
    lang: str,
    categories: list[str] | None = None,
    *,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now_utc or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    category_preferences = list(categories or [])
    category_priority = {category: index for index, category in enumerate(category_preferences)}
    candidates: list[tuple[int, datetime, dict[str, Any]]] = []
    for row in rows:
        published = _sort_datetime(row)
        if published < cutoff or published > now + timedelta(minutes=5):
            continue
        item = _article_object(row, lang)
        if item is None or item["headline_only"]:
            continue
        if not item.get("summary"):
            continue
        priority = category_priority.get(item["category_slug"], len(category_priority))
        candidates.append((priority, published, item))
    candidates.sort(key=lambda part: (part[0], part[1]), reverse=False)
    # Sort each priority group newest-first while preserving the preference order.
    candidates.sort(key=lambda part: (part[0], -part[1].timestamp()))
    selected: list[dict[str, Any]] = []
    per_category: dict[str, int] = {}
    seen_slugs: set[str] = set()
    for _priority, _published, item in candidates:
        slug = item["slug"]
        category = item["category_slug"]
        if slug in seen_slugs or per_category.get(category, 0) >= 2:
            continue
        selected.append(item)
        seen_slugs.add(slug)
        per_category[category] = per_category.get(category, 0) + 1
        if len(selected) >= 5:
            break
    return selected


def _body_json() -> tuple[dict[str, Any] | None, Response | None]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, _json_error("invalid_json", "Request body must be a JSON object.", 400)
    return value, None


def _valid_expo_token(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 512 or not value.endswith("]"):
        return False
    if not any(value.startswith(prefix) for prefix in _VALID_TOKEN_PREFIXES):
        return False
    return bool(re.fullmatch(r"(?:ExponentPushToken|ExpoPushToken)\[[^\]\r\n]{8,480}\]", value))


def _device_settings(body: dict[str, Any]) -> tuple[dict[str, Any] | None, Response | None]:
    token = body.get("token")
    if not _valid_expo_token(token):
        return None, _json_error(
            "invalid_token",
            "token must be an Expo push token beginning with ExponentPushToken[ or ExpoPushToken[.",
            400,
        )
    platform = body.get("platform")
    if platform not in {"ios", "android"}:
        return None, _json_error("invalid_parameter", "platform must be 'ios' or 'android'.", 400)
    lang = body.get("lang")
    if lang not in {"ar", "en"}:
        return None, _json_error("invalid_parameter", "lang must be 'ar' or 'en'.", 400)
    timezone_name = body.get("timezone", "Asia/Amman")
    if not isinstance(timezone_name, str) or len(timezone_name) > 100:
        return None, _json_error("invalid_parameter", "timezone must be a valid IANA time zone.", 400)
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None, _json_error("invalid_parameter", "timezone must be a valid IANA time zone.", 400)
    digest_enabled = body.get("digest_enabled", True)
    if not isinstance(digest_enabled, bool):
        return None, _json_error("invalid_parameter", "digest_enabled must be a boolean.", 400)
    hour = body.get("digest_hour_local", 8)
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        return None, _json_error("invalid_parameter", "digest_hour_local must be an integer from 0 to 23.", 400)
    categories = body.get("categories", [])
    if not isinstance(categories, list) or any(not isinstance(x, str) for x in categories):
        return None, _json_error("invalid_parameter", "categories must be an array of category slugs.", 400)
    allowed = set(_deps["CATEGORY_NAMES"])
    normalised_categories = list(dict.fromkeys(x.strip().lower() for x in categories))
    if any(not x or x not in allowed for x in normalised_categories):
        return None, _json_error("invalid_parameter", "categories contains an unknown category slug.", 400)
    return {
        "token": token,
        "platform": platform,
        "lang": lang,
        "timezone": timezone_name,
        "digest_enabled": digest_enabled,
        "digest_hour_local": hour,
        "categories": normalised_categories,
    }, None


def _devices_table_error_response() -> Response:
    return _json_error(
        "devices_migration_required",
        "The devices table is not ready. Apply the SQL migration in migrations/20261027_create_devices.sql.",
        503,
    )


def _current_date_for_timezone(timezone_name: str, now_utc: datetime) -> date:
    return now_utc.astimezone(ZoneInfo(timezone_name)).date()


def _expo_send_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not messages:
        return []
    request_obj = Request(
        _EXPO_PUSH_URL,
        data=json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request_obj, timeout=_EXPO_PUSH_TIMEOUT_SECONDS) as response:
            parsed = json.loads(response.read(2_000_000).decode("utf-8", errors="replace"))
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, dict):
            data = [data]
        return data if isinstance(data, list) else None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Expo digest push batch failed (%s)", type(exc).__name__)
        return None


def register_public_api_v1(app, dependencies: dict[str, Any]) -> None:
    """Register additive /api/v1 routes without changing existing website routes."""
    global _deps
    _deps = dependencies

    @app.get("/api/v1/categories")
    @_rate_limited(120)
    @_cached_get
    def api_v1_categories():
        return _json_response([
            {"slug": slug, "label_ar": labels["ar"], "label_en": labels["en"]}
            for slug, labels in _deps["CATEGORY_NAMES"].items()
        ], cacheable=True)

    @app.get("/api/v1/articles")
    @_rate_limited(120)
    @_cached_get
    def api_v1_articles():
        lang, error = _request_lang(required=True)
        if error:
            return error
        category = request.args.get("category")
        if category:
            category = category.strip().lower()
            if category not in _deps["CATEGORY_NAMES"]:
                return _json_error("invalid_parameter", "category is not a supported category slug.", 400)
        page, error = _parse_positive_int("page", 1, minimum=1, maximum=1_000_000)
        if error:
            return error
        per_page, error = _parse_positive_int("per_page", 20, minimum=1, maximum=50)
        if error:
            return error
        items = _list_api_articles(lang, category=category)
        return _json_response(_paginate(items, page, per_page), cacheable=True)

    @app.get("/api/v1/articles/<slug>")
    @_rate_limited(120)
    @_cached_get
    def api_v1_article(slug: str):
        if len(slug) > 220:
            return _json_error("invalid_parameter", "slug is too long.", 400)
        lang, error = _request_lang(required=False)
        if error:
            return error
        try:
            row = _deps["_db_fetch_article_by_slug"](slug)
        except Exception:
            logger.exception("API detail lookup failed")
            row = None
        if not row:
            return _json_error("not_found", "Article was not found.", 404)
        if lang is None:
            lang = str(row.get("original_language") or "en")
            if lang not in {"ar", "en"}:
                lang = "en"
        item = _article_object(row, lang)
        if item is None:
            return _json_error("not_found", "Article is not available under the publisher and language policy.", 404)
        return _json_response(item, cacheable=True)

    @app.get("/api/v1/search")
    @_rate_limited(120)
    @_cached_get
    def api_v1_search():
        lang, error = _request_lang(required=True)
        if error:
            return error
        query = str(request.args.get("q") or "").strip()
        if len(query) < 2 or len(query) > 160:
            return _json_error("invalid_parameter", "q must contain between 2 and 160 characters.", 400)
        page, error = _parse_positive_int("page", 1, minimum=1, maximum=1_000_000)
        if error:
            return error
        per_page, error = _parse_positive_int("per_page", 20, minimum=1, maximum=50)
        if error:
            return error
        try:
            rows = _deps["_db_search_articles"](query, limit=100)
        except Exception:
            logger.exception("API search query failed")
            rows = None
        if rows is None:
            # Match the public website fallback: search only the shared display pool.
            terms = [term.casefold() for term in re.findall(r"[\w\u0600-\u06ff]+", query) if len(term) > 1]
            display_rows = _deps["_get_display_stories"](lang)
            rows = [
                row for row in display_rows
                if all(
                    term in " ".join(str(row.get(key, "")) for key in ("title", "summary", "content", "source_name")).casefold()
                    for term in terms
                )
            ] if terms else []
        items = []
        for row in rows:
            if not _api_source_row_allowed(row, lang):
                continue
            item = _article_object(row, lang)
            if item is not None:
                items.append(item)
        items.sort(key=lambda item: item.get("published_at") or "", reverse=True)
        return _json_response(_paginate(items, page, per_page), cacheable=True)

    @app.get("/api/v1/digest")
    @_rate_limited(120)
    @_cached_get
    def api_v1_digest():
        lang, error = _request_lang(required=True)
        if error:
            return error
        categories, error = _valid_categories(request.args.get("categories"))
        if error:
            return error
        try:
            rows = _deps["_db_fetch_all"]()
        except Exception:
            logger.exception("API digest failed to read archive snapshot")
            rows = []
        items = _digest_items_from_rows(rows, lang, categories)
        return _json_response({
            "items": items,
            "count": len(items),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }, cacheable=True)

    @app.post("/api/v1/devices")
    @_rate_limited(20)
    def api_v1_devices_register():
        body, error = _body_json()
        if error:
            return error
        settings, error = _device_settings(body)
        if error:
            return error
        if not _deps["_ensure_schema"]():
            return _json_error("database_unavailable", "Database is temporarily unavailable.", 503)
        conn = _deps["_connect_db"]()
        if conn is None:
            return _json_error("database_unavailable", "Database is temporarily unavailable.", 503)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.devices (
                        token, platform, lang, timezone, digest_enabled, digest_hour_local,
                        categories, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (token) DO UPDATE SET
                        platform = EXCLUDED.platform,
                        lang = EXCLUDED.lang,
                        timezone = EXCLUDED.timezone,
                        digest_enabled = EXCLUDED.digest_enabled,
                        digest_hour_local = EXCLUDED.digest_hour_local,
                        categories = EXCLUDED.categories,
                        updated_at = NOW()
                """, (
                    settings["token"], settings["platform"], settings["lang"], settings["timezone"],
                    settings["digest_enabled"], settings["digest_hour_local"], settings["categories"],
                ))
            conn.commit()
            return _json_response({
                "registered": True,
                "platform": settings["platform"],
                "lang": settings["lang"],
                "timezone": settings["timezone"],
                "digest_enabled": settings["digest_enabled"],
                "digest_hour_local": settings["digest_hour_local"],
                "categories": settings["categories"],
            }, status=200)
        except Exception as exc:
            conn.rollback()
            if "devices" in str(exc).casefold() and (
                "does not exist" in str(exc).casefold() or "undefined table" in str(exc).casefold()
            ):
                return _devices_table_error_response()
            logger.warning("Device registration failed (%s)", type(exc).__name__)
            return _json_error("device_registration_failed", "Could not register this device.", 503)
        finally:
            _deps["_release_db_connection"](conn)

    @app.delete("/api/v1/devices")
    @_rate_limited(20)
    def api_v1_devices_delete():
        body, error = _body_json()
        if error:
            return error
        token = body.get("token")
        if not _valid_expo_token(token):
            return _json_error("invalid_token", "token must be a valid Expo push token.", 400)
        if not _deps["_ensure_schema"]():
            return _json_error("database_unavailable", "Database is temporarily unavailable.", 503)
        conn = _deps["_connect_db"]()
        if conn is None:
            return _json_error("database_unavailable", "Database is temporarily unavailable.", 503)
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.devices WHERE token = %s", (token,))
                deleted = cur.rowcount > 0
            conn.commit()
            return _json_response({"deleted": deleted})
        except Exception as exc:
            conn.rollback()
            if "devices" in str(exc).casefold() and (
                "does not exist" in str(exc).casefold() or "undefined table" in str(exc).casefold()
            ):
                return _devices_table_error_response()
            logger.warning("Device deletion failed (%s)", type(exc).__name__)
            return _json_error("device_deletion_failed", "Could not delete this device.", 503)
        finally:
            _deps["_release_db_connection"](conn)

    @app.post("/internal/send-digest")
    @_rate_limited(5)
    def internal_send_digest():
        expected = str(os.getenv("DIGEST_TOKEN") or "").strip()
        supplied = str(request.headers.get("X-Digest-Token") or "")
        if not expected:
            return _json_error("not_configured", "Digest sender is not configured.", 503)
        if not supplied or not secrets.compare_digest(supplied, expected):
            return _json_error("unauthorized", "Invalid internal token.", 401)

        # Load through the application's shared snapshot before reserving the one
        # database connection used to list/update devices and coordinate the sender.
        try:
            article_rows = _deps["_db_fetch_all"]()
        except Exception:
            logger.exception("Digest sender could not read article snapshot")
            article_rows = []

        if not _API_DIGEST_SEND_LOCK.acquire(blocking=False):
            return _json_response({"status": "busy", "sent": 0, "removed": 0}, status=409)
        conn = None
        advisory_locked = False
        sent_count = 0
        removed_count = 0
        skipped_count = 0
        attempted_count = 0
        failed_count = 0
        try:
            conn = _deps["_connect_db"]()
            if conn is None:
                return _json_error("database_unavailable", "Database is temporarily unavailable.", 503)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext(%s))", ("nabd-news", "daily-digest"))
                lock_row = cur.fetchone()
                advisory_locked = bool(lock_row and lock_row[0])
            conn.commit()
            if not advisory_locked:
                return _json_response({"status": "busy", "sent": 0, "removed": 0}, status=409)

            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT token, lang, timezone, digest_hour_local, categories, last_digest_sent_date
                        FROM public.devices
                        WHERE digest_enabled = TRUE
                        ORDER BY created_at ASC
                    """)
                    devices = [dict(row) if isinstance(row, dict) else {
                        "token": row[0], "lang": row[1], "timezone": row[2],
                        "digest_hour_local": row[3], "categories": row[4],
                        "last_digest_sent_date": row[5],
                    } for row in cur.fetchall()]
                conn.commit()
            except Exception as exc:
                conn.rollback()
                if "devices" in str(exc).casefold() and (
                    "does not exist" in str(exc).casefold() or "undefined table" in str(exc).casefold()
                ):
                    return _devices_table_error_response()
                logger.warning("Digest device lookup failed (%s)", type(exc).__name__)
                return _json_error("digest_query_failed", "Could not load digest subscriptions.", 503)

            now_utc = datetime.now(timezone.utc)
            eligible = []
            for device in devices:
                try:
                    local_now = now_utc.astimezone(ZoneInfo(str(device.get("timezone") or "Asia/Amman")))
                    local_today = local_now.date()
                    last_sent = device.get("last_digest_sent_date")
                    if isinstance(last_sent, datetime):
                        last_sent = last_sent.date()
                    if local_now.hour != int(device.get("digest_hour_local") or 0) or last_sent == local_today:
                        skipped_count += 1
                        continue
                    lang = str(device.get("lang") or "")
                    if lang not in {"ar", "en"}:
                        skipped_count += 1
                        continue
                    categories = list(device.get("categories") or [])
                    digest = _digest_items_from_rows(article_rows, lang, categories, now_utc=now_utc)
                    if len(digest) < 3:
                        skipped_count += 1
                        continue
                    extra_count = len(digest) - 1
                    title = "نبض الصباح" if lang == "ar" else "Morning Digest"
                    body = f"{digest[0]['title']} +{extra_count} more"
                    eligible.append({
                        "to": str(device["token"]),
                        "sound": "default",
                        "title": title,
                        "body": body[:240],
                        "data": {"type": "digest", "slug": digest[0]["slug"]},
                    })
                except (ZoneInfoNotFoundError, TypeError, ValueError, KeyError):
                    skipped_count += 1

            for start in range(0, len(eligible), 100):
                batch = eligible[start:start + 100]
                attempted_count += len(batch)
                tickets = _expo_send_batch(batch)
                if tickets is None:
                    failed_count += len(batch)
                    continue
                if len(tickets) != len(batch):
                    logger.warning("Expo digest response ticket count mismatch: sent=%d tickets=%d", len(batch), len(tickets))
                with conn.cursor() as cur:
                    for index, message in enumerate(batch):
                        ticket = tickets[index] if index < len(tickets) and isinstance(tickets[index], dict) else {}
                        status = str(ticket.get("status") or "")
                        details = ticket.get("details") if isinstance(ticket.get("details"), dict) else {}
                        error_name = str(details.get("error") or ticket.get("message") or "")
                        token = message["to"]
                        if error_name == "DeviceNotRegistered":
                            cur.execute("DELETE FROM public.devices WHERE token = %s", (token,))
                            removed_count += max(0, cur.rowcount)
                            continue
                        if status != "ok":
                            failed_count += 1
                            continue
                        try:
                            local_date = _current_date_for_timezone(
                                next(str(device.get("timezone") or "Asia/Amman") for device in devices if device.get("token") == token),
                                now_utc,
                            )
                        except (ZoneInfoNotFoundError, StopIteration, ValueError):
                            local_date = now_utc.date()
                        cur.execute("""
                            UPDATE public.devices
                            SET last_digest_sent_date = %s, updated_at = NOW()
                            WHERE token = %s AND last_digest_sent_date IS DISTINCT FROM %s
                        """, (local_date, token, local_date))
                        sent_count += max(0, cur.rowcount)
                conn.commit()

            return _json_response({
                "status": "complete",
                "eligible": len(eligible),
                "attempted": attempted_count,
                "sent": sent_count,
                "removed": removed_count,
                "skipped": skipped_count,
                "failed": failed_count,
            })
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.exception("Internal digest sender failed (%s)", type(exc).__name__)
            return _json_error("digest_sender_failed", "Digest sender failed; check server logs.", 503)
        finally:
            if conn is not None:
                if advisory_locked:
                    try:
                        with conn.cursor() as cur:
                            cur.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))", ("nabd-news", "daily-digest"))
                        conn.commit()
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                _deps["_release_db_connection"](conn)
            _API_DIGEST_SEND_LOCK.release()

    # Missing /api/v1 subpaths and unsupported methods should also respond as JSON.
    @app.route("/api/v1/", defaults={"api_path": ""}, methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
    @app.route("/api/v1/<path:api_path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
    def api_v1_not_found(api_path: str):
        return _json_error("not_found", "API endpoint was not found.", 404)

