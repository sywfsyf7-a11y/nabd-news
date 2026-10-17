#!/usr/bin/env python3
"""Gentle production smoke/load test for World Pulse; no writes or refresh triggers."""
from __future__ import annotations

import concurrent.futures
import json
import re
import statistics
import sys
import time
from html import unescape
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://nabd-news.onrender.com"
USER_AGENT = "WorldPulseProductionAudit/1.0 (+read-only)"
WORKERS = 6
ROUNDS = 5


def request(path: str) -> dict:
    url = BASE_URL + path
    started = time.perf_counter()
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urlopen(req, timeout=35) as response:
            body = response.read()
            status = response.status
            headers = dict(response.headers.items())
        elapsed = time.perf_counter() - started
        return {"path": path, "status": status, "seconds": elapsed,
                "bytes": len(body), "body": body.decode("utf-8", "replace"),
                "cache_control": headers.get("Cache-Control", "")}
    except Exception as exc:
        return {"path": path, "status": 0, "seconds": time.perf_counter()-started,
                "bytes": 0, "body": "", "error": type(exc).__name__ + ": " + str(exc)}


def pctl(values: list[float], pct: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    return values[min(len(values)-1, max(0, int((len(values)-1)*pct + 0.999999)))]


def main() -> int:
    print("World Pulse read-only production load test")
    print(json.dumps({"base_url": BASE_URL, "workers": WORKERS, "rounds": ROUNDS}, indent=2))
    base_results = [request("/healthz"), request("/?lang=en"), request("/?lang=ar"),
                    request("/api/news-status")]
    for result in base_results:
        print(f"BASE {result['status']:>3} {result['seconds']:.3f}s {result['bytes']:>7} bytes {result['path']}")
        if result.get("error"):
            print("  error:", result["error"])
    if any(r["status"] != 200 for r in base_results):
        print("FAIL: one or more baseline endpoints did not return HTTP 200")
        return 1
    for lang, result in (("en", base_results[1]), ("ar", base_results[2])):
        match = re.search(r'<html\s+lang=["\'](en|ar)["\']', result["body"], re.I)
        actual = match.group(1).lower() if match else "missing"
        print(f"LANG {lang}: document lang={actual}")
        if actual != lang:
            print("FAIL: homepage language mismatch")
            return 1

    article_paths: list[str] = []
    for lang, result in (("en", base_results[1]), ("ar", base_results[2])):
        for href in re.findall(r'''href=["']([^"']+)["']''', result["body"], re.I):
            href = unescape(href)
            parsed = urlparse(href)
            if parsed.netloc and parsed.hostname != urlparse(BASE_URL).hostname:
                continue
            path = parsed.path if parsed.scheme or parsed.netloc else href.split("#", 1)[0].split("?", 1)[0]
            query = parsed.query if parsed.scheme or parsed.netloc else (href.split("?", 1)[1].split("#", 1)[0] if "?" in href else "")
            if not path.startswith("/article/"):
                continue
            if "lang=" not in query:
                query = (query + "&" if query else "") + "lang=" + lang
            full = path + ("?" + query if query else "")
            if full not in article_paths:
                article_paths.append(full)
            if len(article_paths) >= 4:
                break
        if len(article_paths) >= 4:
            break
    if not article_paths:
        print("WARNING: no article links found on the homepages; measuring homepage routes only")
        article_paths = ["/?lang=en", "/?lang=ar"]
    print("Article samples:", json.dumps(article_paths, ensure_ascii=False))

    paths = ["/?lang=en", "/?lang=ar", "/healthz", "/api/news-status"] + article_paths
    samples = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(request, paths[i % len(paths)]) for i in range(ROUNDS * WORKERS)]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            samples.append(result)
            if result["status"] != 200:
                failures.append(result)
    times = [r["seconds"] for r in samples]
    print(json.dumps({
        "requests": len(samples), "workers": WORKERS,
        "successes": sum(r["status"] == 200 for r in samples),
        "failures": len(failures),
        "latency_seconds": {
            "min": round(min(times), 3) if times else 0,
            "median": round(statistics.median(times), 3) if times else 0,
            "p95": round(pctl(times, .95), 3),
            "max": round(max(times), 3) if times else 0,
            "mean": round(statistics.mean(times), 3) if times else 0,
        },
        "bytes_by_path": {p: next((r["bytes"] for r in base_results if r["path"] == p), None) for p in paths},
        "slowest_requests": sorted(
            [{"path": r["path"], "status": r["status"], "seconds": round(r["seconds"], 3), "bytes": r["bytes"]}
             for r in samples], key=lambda r: r["seconds"], reverse=True
        )[:8],
        "failed_samples": [{"path": r["path"], "status": r["status"], "error": r.get("error", "")}
                           for r in failures[:8]],
    }, indent=2, ensure_ascii=False))
    if failures:
        print("FAIL: one or more requests failed")
        return 1
    print("PASS: baseline plus concurrent read-only requests returned HTTP 200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
