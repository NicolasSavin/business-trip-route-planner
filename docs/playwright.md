# Playwright browser diagnostics

This project now connects the existing Browser Automation Infrastructure to real Playwright, but only for diagnostics.

## How the browser starts

`BrowserManager` owns the Playwright process and the Chromium browser instance. When `BrowserManager.start()` is called with `PLAYWRIGHT_ENABLED=true`, it starts `sync_playwright()`, launches headless Chromium, stores the browser version, and updates browser lifecycle metrics. `BrowserManager.stop()` closes the browser, stops Playwright, and records browser lifetime.

Render installs Playwright during the backend build with:

```bash
pip install -r requirements.txt && python -m playwright install chromium
```

The Render backend environment enables diagnostics with `PLAYWRIGHT_ENABLED=true` and `BROWSER_HEADLESS=true`.

## How the pool works

`BrowserPool` keeps the previous architecture: callers acquire and release `BrowserSession` objects through the pool. The pool enforces `BROWSER_POOL_SIZE`, starts the browser through `BrowserManager.ensure_browser()`, tracks running sessions, and returns idle sessions to the available list after cleanup.

## How sessions work

`BrowserSession` wraps a Playwright browser context and page. It supports:

- `new_page()`
- `navigate()`
- `capture_html()`
- `capture_screenshot()`
- `evaluate()`
- `close()`
- `destroy()`

Selector-driven actions remain intentionally disconnected at this stage. No CSS selectors, XPath selectors, forms, clicks, or scraping flows are implemented here.

## Why `example.com` is used now

The diagnostics API only opens `https://example.com`. This keeps the PR focused on proving that Playwright launches, creates pages, navigates, reads the page title, captures HTML length, and produces a PNG screenshot. It avoids any dependency on travel providers, anti-bot behavior, partner contracts, or scraping logic.

## API endpoints

- `GET /api/v1/browser/ping` opens `https://example.com` and returns title, final URL, HTML length, browser version, and elapsed time when Chromium is available; otherwise it returns a degraded diagnostic message instead of crashing.
- `GET /api/v1/browser/screenshot` opens `https://example.com` and returns a PNG screenshot.
- `GET /api/v1/browser/health` reports Playwright installed, browser running, browser version, status, and health.
- `GET /api/v1/browser/metrics` reports opened pages, closed pages, running sessions, browser restarts, and average page load time.

## Frontend diagnostics

The `Browser Diagnostics` page calls the ping endpoint with the `Test Browser` button and displays `Browser OK`, browser version, page title, load time, and a screenshot preview loaded from the screenshot endpoint.

## Later tutu.ru integration

A later PR can add a dedicated provider adapter that receives a `BrowserSession` from `BrowserPool`. That future adapter should contain any site-specific navigation and selector strategy. This PR deliberately does not include tutu.ru, RZD, MyAgent, Teletrain, scraping, or provider data extraction.
