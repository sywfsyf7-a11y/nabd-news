"""Independent adapters for querying openly licensed image catalogues.

The Openverse adapter receives app-specific helpers as callables so it can be tested
without importing the Flask application or coupling this module to database state.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import quote, urlparse


def openverse_license_url_ok(license_code: str, license_url: str) -> bool:
    """Accept only HTTPS item-level licences that allow commercial reuse."""
    code = (license_code or "").casefold().strip()
    try:
        parsed = urlparse(license_url)
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold()
        not in {"creativecommons.org", "www.creativecommons.org"}
    ):
        return False
    path = parsed.path.casefold().rstrip("/")
    if code == "cc0":
        return path == "/publicdomain/zero/1.0"
    if code == "pdm":
        return path == "/publicdomain/mark/1.0"
    if code == "by":
        return bool(re.fullmatch(r"/licenses/by/(?:2\.0|3\.0|4\.0)", path))
    if code == "by-sa":
        return bool(re.fullmatch(r"/licenses/by-sa/(?:2\.0|3\.0|4\.0)", path))
    return False


def search_openverse_image(
    title: str,
    *,
    timeout_seconds: int,
    clean_text_fn: Callable[[Any, int], str],
    query_fn: Callable[[str, int], str],
    match_score_fn: Callable[[str, str], float],
    https_url_fn: Callable[[Any, set[str] | None], str],
    request_factory: Callable[..., Any],
    urlopen_func: Callable[..., Any],
    now_fn: Callable[[], Any],
    logger: Any,
) -> dict[str, Any]:
    """Find a relevant CC0/PDM/CC BY/CC BY-SA image and retain provenance."""
    title = clean_text_fn(title, 200)
    if not title:
        return {}
    query = query_fn(title, 6) or title[:180]
    from urllib.parse import urlencode

    params = urlencode({
        "q": query,
        "license": "cc0,pdm,by,by-sa",
        "license_type": "commercial",
        "extension": "jpg,jpeg,png,webp",
        "page_size": 20,
        "page": 1,
        "mature": "false",
        "filter_dead": "true",
    })
    request_obj = request_factory(
        "https://api.openverse.org/v1/images/?" + params,
        headers={
            "Accept": "application/json",
            "User-Agent": "WorldPulseNews/2.0 (+licensed news image discovery)",
        },
    )
    try:
        with urlopen_func(request_obj, timeout=timeout_seconds) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8", errors="replace"))
        best: tuple[float, dict[str, Any]] | None = None
        for item in (data.get("results") or [])[:20]:
            if not isinstance(item, dict) or item.get("mature") is True:
                continue
            license_code = str(item.get("license") or "").casefold().strip()
            license_url = https_url_fn(item.get("license_url"), {"creativecommons.org"})
            if not openverse_license_url_ok(license_code, license_url):
                continue
            image_url = https_url_fn(item.get("url"), None)
            item_page = https_url_fn(item.get("foreign_landing_url"), None)
            if not image_url or not item_page:
                continue
            try:
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
            except (ValueError, TypeError):
                width, height = 0, 0
            if width and width < 500:
                continue
            if width and height and (height <= 0 or width / height < 0.8):
                continue
            creator = clean_text_fn(item.get("creator") or "", 180)
            creator_url = https_url_fn(item.get("creator_url"), None)
            if license_code in {"by", "by-sa"} and not creator:
                continue
            item_title = clean_text_fn(item.get("title") or "", 240)
            tags = item.get("tags") or []
            if isinstance(tags, list):
                tag_text = " ".join(
                    clean_text_fn(tag.get("name") if isinstance(tag, dict) else tag, 80)
                    for tag in tags[:20]
                )
            else:
                tag_text = clean_text_fn(tags, 500)
            evidence = " ".join((item_title, tag_text, creator))
            score = max(
                match_score_fn(query, evidence),
                match_score_fn(title, evidence),
            )
            if score <= 0:
                continue
            version = str(item.get("license_version") or "")
            if license_code == "cc0":
                license_label = "CC0 1.0"
            elif license_code == "pdm":
                license_label = "Public Domain Mark 1.0"
            elif license_code == "by-sa":
                license_label = "CC BY-SA " + version if version else "CC BY-SA"
            else:
                license_label = "CC BY " + version if version else "CC BY"
            identifier = str(item.get("id") or "").strip()
            # Fetch from Openverse's own thumbnail endpoint for safe, durable server-side caching.
            # The original item URL remains the attribution destination.
            thumbnail_url = (
                "https://api.openverse.org/v1/images/" + quote(identifier, safe="") + "/thumb/?full_size=true&compressed=true"
                if identifier and re.fullmatch(r"[A-Za-z0-9_-]{8,100}", identifier)
                else ""
            )
            result = {
                "image_url": image_url,
                "image_cache_url": thumbnail_url,
                "image_source": "openverse_licensed",
                "image_credit": creator or "Creator not listed · see original item",
                "image_credit_url": creator_url or item_page,
                "image_provider_url": item_page,
                "image_license_url": license_url,
                "image_checked_at": now_fn(),
                "image_title": item_title,
                "image_license_label": license_label,
                "_image_relevance_score": score,
            }
            if best is None or score > best[0]:
                best = (score, result)
        return best[1] if best else {}
    except Exception as exc:
        # Avoid leaking upstream response bodies, credentials or full request URLs to logs.
        logger.debug("Openverse image lookup failed (%s)", type(exc).__name__)
        return {}
