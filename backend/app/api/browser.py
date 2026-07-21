from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.browser import BrowserConfiguration, BrowserManager, BrowserPool
from app.browser.exceptions import BrowserUnavailableError

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])

_config = BrowserConfiguration.from_env().with_playwright_enabled()
_manager = BrowserManager(config=_config)
_pool = BrowserPool(manager=_manager)


@router.get("/ping")
def browser_ping() -> dict[str, Any]:
    started = perf_counter()
    try:
        with _pool.session() as session:
            session.new_page()
            session.navigate("https://example.com")
            title = session.evaluate("() => document.title")
            url = session.evaluate("() => window.location.href")
            html = session.capture_html()
    except BrowserUnavailableError as exc:
        health = _manager.health()
        return {
            "status": health.status,
            "healthy": health.healthy,
            "message": str(exc),
            "browser_version": _manager.version(),
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        }
    return {
        "title": title,
        "url": url,
        "html_length": len(html),
        "browser_version": _manager.version(),
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
    }


@router.get("/screenshot")
def browser_screenshot() -> Response:
    try:
        with _pool.session() as session:
            session.new_page()
            session.navigate("https://example.com")
            png = session.capture_screenshot()
    except BrowserUnavailableError as exc:
        return JSONResponse({"status": _manager.health().status, "message": str(exc)}, status_code=503)
    return Response(content=png, media_type="image/png")


@router.get("/health")
def browser_health() -> dict[str, Any]:
    health = _manager.health()
    return {
        "playwright_installed": health.configured,
        "browser_running": health.status == "running",
        "browser_version": health.version,
        "status": health.status,
        "healthy": health.healthy,
    }


@router.get("/metrics")
def browser_metrics() -> dict[str, Any]:
    metrics = _manager.metrics
    return {
        "opened_pages": metrics.pages_opened,
        "closed_pages": metrics.pages_closed,
        "running_sessions": metrics.active_sessions,
        "browser_restarts": metrics.restarts,
        "average_page_load": metrics.average_page_load_ms,
    }
