# Nabd News — Production Audit (2026-10-20)

## Executive summary

The audit found a confirmed reliability issue in the live Render service: Render recorded repeated `OOMKilled`/server-failed events with a 512 MiB memory limit on 20 October 2026. This can cause intermittent slow responses and 5xx/404 errors during restarts. The events prove memory exhaustion occurred; they do not by themselves identify one single function as the sole cause.

The current changes reduce the in-memory archive window, cap downloaded/uploaded image sizes and decoded pixels, reduce image-processing concurrency, shrink the per-worker image-byte cache, and set the Blueprint to one Gunicorn worker. The persistent Supabase archive remains the source of truth; older article pages are still looked up directly by saved slug. Cache limits do not delete archived database records.

## Changes in this audit

- Standardized the visible brand to **نبض نيوز** in Arabic and **Nabd News** in English, including page metadata, the public header/footer, admin pages, generated/fallback images, the favicon label, policy text and README.
- Added regression coverage for localized page metadata and the memory/image limits.
- Reduced the hot archive window from 150 to 60 records per category and source language by default (hard cap 90). This is only a working/display cache; Supabase remains the persistent archive.
- Limited image processing to 8 megapixels, 12 MiB source images by default, 20 MiB administrator uploads by default, two concurrent image-resolution tasks, and an 8 MiB process-local image-byte cache with a 3 MiB per-item default.
- Reduced the default image lookup budget to two per publication tick and aligned the persistent discovery queue cap with the three candidates appropriate for a 15-minute discovery interval.
- Set `MALLOC_ARENA_MAX=2` and a single-worker Gunicorn command in `render.yaml` to reduce the Blueprint's memory footprint.
- Removed the redundant Node/Tailwind build from the Render Blueprint because the compiled CSS asset is stored in the repository and the current Render Dashboard build command only installs Python dependencies.

## Important deployment configuration note

The existing Render service's Dashboard configuration has historically differed from `render.yaml`: the live service reports a Python-only build command and an explicit Gunicorn command with two workers. A Blueprint file change does not guarantee the live Dashboard's start command has changed. After merging, the memory-capping environment variables should be applied to the existing service and the live deployment verified. The service should be moved to one Gunicorn worker through the Render service's actual Start Command configuration when possible; this repository alone cannot assert that Dashboard setting has changed.

## Performance evidence and remaining validation

Render recorded repeated OOM kills at a 512 MiB memory limit. CPU usage in the sampled period was low, while reported memory approached that limit. The Render HTTP latency/count query returned no data for the inspected interval, so this audit does not claim a measured live p95 or a guaranteed speed improvement.

After deployment, measure the homepage and article page with [PageSpeed Insights](https://pagespeed.web.dev/) on both mobile and desktop, then monitor Core Web Vitals in Search Console when field data becomes available. Useful “good” field targets are LCP <= 2.5 seconds, INP <= 200 milliseconds and CLS <= 0.1; these are measurement targets, not results claimed by this audit.

## AdSense readiness: not a guarantee of approval

The site now has clearer branding, source attribution, image provenance and resource limits, but acceptance cannot be guaranteed by code changes. Before submission, manually inspect a representative sample of Arabic and English articles for original value, correct language/category, an accurate summary, useful details, valid source links and suitable rights-cleared images. Verify the real AdSense publisher ID and that the site's actual privacy/consent setup matches the regions it serves. If personalized ads are served to visitors in the EEA, UK or Switzerland, Google requires a certified CMP integrated with the IAB TCF. Review the current [AdSense Program Policies](https://support.google.com/adsense/answer/48182?hl=en) and [publisher CMP requirements](https://support.google.com/adsense/answer/13554116?hl=en) before enabling ads.

## Automated verification

The CI workflow passed **236 unit tests** on the audit branch after the branding, image-size and memory-guard updates. The production-load-test and wake/check jobs were skipped for this branch, so live load testing and post-deploy PageSpeed verification remain separate validation steps.
