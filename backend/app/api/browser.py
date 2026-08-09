from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.browser.exceptions import BrowserUnavailableError
from app.browser.runtime import browser_manager, browser_pool

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])

_manager = browser_manager
_pool = browser_pool


@router.get("/ping")
async def browser_ping() -> dict[str, Any]:
    started = perf_counter()
    try:
        async with _pool.session() as session:
            await session.new_page()
            await session.navigate("https://example.com")
            title = await session.evaluate("() => document.title")
            url = await session.evaluate("() => window.location.href")
            html = await session.capture_html()
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
async def browser_screenshot() -> Response:
    try:
        async with _pool.session() as session:
            await session.new_page()
            await session.navigate("https://example.com")
            png = await session.capture_screenshot()
    except BrowserUnavailableError as exc:
        return JSONResponse({"status": _manager.health().status, "message": str(exc)}, status_code=503)
    return Response(content=png, media_type="image/png")


@router.get("/health")
def browser_health() -> dict[str, Any]:
    health = _manager.health()
    running = _manager.browser_running
    installed = health.configured
    if not health.enabled:
        status = "stopped"
    elif not installed:
        status = "unavailable"
    else:
        status = "running" if running else "stopped"
    return {
        "configured": health.enabled,
        "installed": installed,
        "running": running,
        "healthy_if_running": health.healthy if running else None,
        "status": status,
        "browser_version": health.version,
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
