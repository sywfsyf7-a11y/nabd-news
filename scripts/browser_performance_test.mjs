import { chromium } from "playwright";

const BASE_URL = (process.env.SITE_URL || "https://nabd-news.onrender.com").replace(/\/+$/, "");
const TIMEOUT_MS = Number(process.env.BROWSER_AUDIT_TIMEOUT_MS || 45000);

async function measurePage(page, label, url, expectedLanguage) {
  const failedRequests = [];
  const cssResponses = [];
  const pageErrors = [];
  const onRequestFailed = (request) => {
    const type = request.resourceType();
    if (["document", "stylesheet", "script", "image", "font"].includes(type)) {
      failedRequests.push({
        type,
        url: request.url().split("?")[0],
        error: request.failure()?.errorText || "request_failed",
      });
    }
  };
  const onResponse = (response) => {
    if (response.url().includes("/static/css/site.css")) {
      cssResponses.push({ status: response.status(), url: response.url().split("?")[0] });
    }
  };
  const onPageError = (error) => pageErrors.push(error.message);

  page.on("requestfailed", onRequestFailed);
  page.on("response", onResponse);
  page.on("pageerror", onPageError);

  const startedAt = Date.now();
  let response = null;
  let navigationError = "";
  try {
    response = await page.goto(url, { waitUntil: "load", timeout: TIMEOUT_MS });
    // Let late image/font paints settle without waiting indefinitely on analytics or long polling.
    await page.waitForTimeout(1200);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }

  const browserData = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const paints = performance.getEntriesByType("paint");
    const fcp = paints.find((item) => item.name === "first-contentful-paint");
    const visibleImages = Array.from(document.images).filter((img) => {
      const rect = img.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
    });
    const firstArticle = document.querySelector('a[href*="/article/"]');
    return {
      documentLanguage: document.documentElement.lang || "",
      title: document.title || "",
      finalUrl: window.location.href,
      ttfbMs: nav ? Math.round(nav.responseStart) : null,
      domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      loadEventMs: nav && nav.loadEventEnd ? Math.round(nav.loadEventEnd) : null,
      fcpMs: fcp ? Math.round(fcp.startTime) : null,
      lcpMs: window.__worldPulseBrowserAudit ? window.__worldPulseBrowserAudit.lcpMs : null,
      cls: window.__worldPulseBrowserAudit ? Number(window.__worldPulseBrowserAudit.cls.toFixed(4)) : null,
      transferBytes: nav ? nav.transferSize : null,
      encodedDocumentBytes: nav ? nav.encodedBodySize : null,
      imageCount: document.images.length,
      visibleImageCount: visibleImages.length,
      visibleImagesLoaded: visibleImages.filter((img) => img.complete && img.naturalWidth > 0).length,
      visibleImagesBroken: visibleImages.filter((img) => img.complete && img.naturalWidth === 0 && Boolean(img.currentSrc || img.src)).length,
      documentFontsStatus: document.fonts ? document.fonts.status : "unsupported",
      firstArticleHref: firstArticle ? firstArticle.getAttribute("href") : "",
    };
  }).catch(() => ({
    documentLanguage: "",
    title: "",
    finalUrl: "",
    ttfbMs: null,
    domContentLoadedMs: null,
    loadEventMs: null,
    fcpMs: null,
    lcpMs: null,
    cls: null,
    transferBytes: null,
    encodedDocumentBytes: null,
    imageCount: 0,
    visibleImageCount: 0,
    visibleImagesLoaded: 0,
    visibleImagesBroken: 0,
    documentFontsStatus: "unavailable",
    firstArticleHref: "",
  }));

  page.off("requestfailed", onRequestFailed);
  page.off("response", onResponse);
  page.off("pageerror", onPageError);

  const status = response ? response.status() : null;
  const finalOrigin = browserData.finalUrl ? new URL(browserData.finalUrl).origin : "";
  const expectedOrigin = new URL(BASE_URL).origin;
  const warnings = [];
  if (navigationError) warnings.push("navigation_timeout_or_error");
  if (status !== 200) warnings.push("document_status_not_200");
  if (browserData.documentLanguage !== expectedLanguage) warnings.push("document_language_mismatch");
  if (finalOrigin !== expectedOrigin) warnings.push("navigated_off_site");
  if (!cssResponses.some((entry) => entry.status === 200 || entry.status === 304)) warnings.push("compiled_css_not_confirmed");
  if (browserData.lcpMs !== null && browserData.lcpMs > 2500) warnings.push("lab_lcp_over_2_5s");
  if (browserData.fcpMs !== null && browserData.fcpMs > 1800) warnings.push("lab_fcp_over_1_8s");
  if (browserData.visibleImagesBroken > 0) warnings.push("visible_image_failed");
  if (pageErrors.length > 0) warnings.push("uncaught_browser_error");

  return {
    label,
    requestedPath: new URL(url).pathname + new URL(url).search,
    status,
    navigationError,
    ...browserData,
    cssResponses,
    failedRequestCount: failedRequests.length,
    failedRequests: failedRequests.slice(0, 8),
    browserErrors: pageErrors.slice(0, 5),
    warnings,
    passed: status === 200
      && !navigationError
      && pageErrors.length === 0
      && browserData.documentLanguage === expectedLanguage
      && finalOrigin === expectedOrigin
      && cssResponses.some((entry) => entry.status === 200 || entry.status === 304),
  };
}

async function main() {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({
    viewport: { width: 1365, height: 900 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(TIMEOUT_MS);

  await page.addInitScript(() => {
    window.__worldPulseBrowserAudit = { lcpMs: null, cls: 0 };
    try {
      new PerformanceObserver((list) => {
        const entries = list.getEntries();
        if (entries.length) {
          window.__worldPulseBrowserAudit.lcpMs = Math.round(entries[entries.length - 1].startTime);
        }
      }).observe({ type: "largest-contentful-paint", buffered: true });
    } catch (_) {}
    try {
      let previous = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) {
            window.__worldPulseBrowserAudit.cls += entry.value;
            previous = entry.startTime;
          }
        }
      }).observe({ type: "layout-shift", buffered: true });
    } catch (_) {}
  });

  const results = [];
  results.push(await measurePage(page, "desktop-home-ar", BASE_URL + "/?lang=ar", "ar"));
  results.push(await measurePage(page, "desktop-home-en", BASE_URL + "/?lang=en", "en"));

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileHome = await measurePage(page, "mobile-home-ar", BASE_URL + "/?lang=ar", "ar");
  results.push(mobileHome);

  let articleUrl = "";
  try {
    const candidate = mobileHome.firstArticleHref;
    if (candidate) {
      const resolved = new URL(candidate, BASE_URL);
      if (resolved.origin === new URL(BASE_URL).origin && resolved.pathname.startsWith("/article/")) {
        if (!resolved.searchParams.has("lang")) resolved.searchParams.set("lang", "ar");
        articleUrl = resolved.toString();
      }
    }
  } catch (_) {}

  if (articleUrl) {
    results.push(await measurePage(page, "mobile-article-ar", articleUrl, "ar"));
  } else {
    results.push({
      label: "mobile-article-ar",
      status: null,
      passed: false,
      warnings: ["no_internal_article_link_found"],
    });
  }

  await browser.close();
  const report = {
    test: "Playwright Chromium synthetic visitor-browser audit",
    baseUrl: BASE_URL,
    note: "This is a headless desktop/mobile-viewport simulation from a remote runner, not real-user telemetry from a visitor's physical device.",
    results,
    passed: results.every((result) => result.passed),
  };
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
