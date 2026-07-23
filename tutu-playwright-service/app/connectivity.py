from __future__ import annotations

import asyncio
import logging
import socket
import time
import traceback
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright

from .settings import settings

logger = logging.getLogger(__name__)

CONNECTIVITY_TIMEOUT_SECONDS = 10
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Target:
    key: str
    url: str


def _targets() -> list[Target]:
    base = settings.tutu_base_url.rstrip("/")
    return [Target("root", f"{base}/"), Target("poezda", f"{base}/poezda/")]


def _host() -> str:
    return urlparse(settings.tutu_base_url).hostname or "www.tutu.ru"


def _error(exc: BaseException) -> dict[str, str]:
    return {"ok": False, "error_type": type(exc).__name__, "message": str(exc), "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))}


async def _safe_cleanup(label: str, cleanup):
    try:
        await cleanup()
    except Exception:
        logger.exception("tutu connectivity cleanup failed", extra={"cleanup": label})


async def _safe_stage(name: str, stage):
    logger.info("connectivity %s started", name)
    try:
        result = await stage()
        logger.info("connectivity %s completed", name)
        return result
    except Exception as exc:
        logger.exception("connectivity %s failed", name)
        logger.info("connectivity %s completed", name)
        return _error(exc)


async def resolve_dns(host: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
        ips = sorted({item[4][0] for item in infos})
        result = {"ok": True, "host": host, "ips": ips, "duration_ms": round((time.monotonic() - started) * 1000, 2)}
        logger.info("tutu connectivity dns resolved", extra={"host": host, "resolved_ips": ips})
        return result
    except Exception as exc:
        result = {"host": host, "duration_ms": round((time.monotonic() - started) * 1000, 2), **_error(exc)}
        logger.info("tutu connectivity dns failed", extra={"host": host, "error_type": type(exc).__name__, "message": str(exc)})
        return result


async def check_tcp(host: str, port: int = 443) -> dict[str, Any]:
    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=CONNECTIVITY_TIMEOUT_SECONDS)
        writer.close()
        await _safe_cleanup("writer.wait_closed", writer.wait_closed)
        result = {"ok": True, "host": host, "port": port, "duration_ms": round((time.monotonic() - started) * 1000, 2)}
        logger.info("tutu connectivity tcp connected", extra={"host": host, "port": port})
        return result
    except Exception as exc:
        result = {"host": host, "port": port, "duration_ms": round((time.monotonic() - started) * 1000, 2), **_error(exc)}
        logger.info("tutu connectivity tcp failed", extra={"host": host, "port": port, "error_type": type(exc).__name__, "message": str(exc)})
        return result


async def check_httpx_url(client: httpx.AsyncClient, target: Target) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = await client.get(target.url)
        chain = [str(item.url) for item in response.history]
        result = {
            "ok": True,
            "status_code": response.status_code,
            "url": target.url,
            "final_url": str(response.url),
            "redirect_chain": chain,
            "headers": dict(response.headers),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
        logger.info(
            "tutu connectivity httpx completed",
            extra={"target": target.key, "url": target.url, "status_code": response.status_code, "redirect_chain": chain, "response_headers": dict(response.headers), "final_url": str(response.url)},
        )
        return result
    except Exception as exc:
        result = {"url": target.url, "duration_ms": round((time.monotonic() - started) * 1000, 2), **_error(exc)}
        logger.info("tutu connectivity httpx failed", extra={"target": target.key, "url": target.url, "error_type": type(exc).__name__, "message": str(exc)})
        return result


async def check_httpx(targets: list[Target], *, http2: bool = True, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=CONNECTIVITY_TIMEOUT_SECONDS, follow_redirects=True, http2=http2, headers=headers) as client:
            return {target.key: await check_httpx_url(client, target) for target in targets}
    except Exception as exc:
        logger.exception("tutu connectivity httpx client failed", extra={"http2": http2})
        return {target.key: {"url": target.url, **_error(exc)} for target in targets}


async def check_playwright(targets: list[Target], *, launch_args: list[str] | None = None, user_agent: str | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    pw = None
    browser = None
    context = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=settings.headless, args=launch_args or [])
        context = await browser.new_context(locale="ru-RU", user_agent=user_agent) if user_agent else await browser.new_context(locale="ru-RU")
        try:
            for target in targets:
                page = await context.new_page()
                page.set_default_timeout(CONNECTIVITY_TIMEOUT_SECONDS * 1000)
                started = time.monotonic()
                try:
                    response = await page.goto(target.url, wait_until="domcontentloaded", timeout=CONNECTIVITY_TIMEOUT_SECONDS * 1000)
                    status = response.status if response else None
                    headers = await response.all_headers() if response else {}
                    result = {"ok": True, "status_code": status, "url": target.url, "final_url": page.url, "headers": headers, "duration_ms": round((time.monotonic() - started) * 1000, 2)}
                    logger.info("tutu connectivity playwright completed", extra={"target": target.key, "url": target.url, "status_code": status, "response_headers": headers, "final_url": page.url})
                except Exception as exc:
                    result = {"url": target.url, "duration_ms": round((time.monotonic() - started) * 1000, 2), **_error(exc)}
                    logger.info("tutu connectivity playwright failed", extra={"target": target.key, "url": target.url, "error_type": type(exc).__name__, "message": str(exc)})
                finally:
                    await _safe_cleanup("page.close", page.close)
                results[target.key] = result
        finally:
            if context:
                await _safe_cleanup("context.close", context.close)
    except Exception as exc:
        logger.info("tutu connectivity playwright setup failed", extra={"error_type": type(exc).__name__, "message": str(exc), "launch_args": launch_args or [], "user_agent": user_agent})
        results = {target.key: {"url": target.url, **_error(exc)} for target in targets}
    finally:
        if browser:
            await _safe_cleanup("browser.close", browser.close)
        if pw:
            await _safe_cleanup("pw.stop", pw.stop)
    return results


def _diagnostic_items(section: dict[str, Any]):
    return [item for item in section.values() if isinstance(item, dict)]


def _all_failed_with_refused(sections: list[dict[str, Any]]) -> bool:
    failures = [item for section in sections for item in _diagnostic_items(section)]
    return bool(failures) and all(not item.get("ok") and "refused" in item.get("message", "").lower() for item in failures)


def _any_ok(section: dict[str, Any]) -> bool:
    return any(item.get("ok") for item in _diagnostic_items(section))


def _any_failed(section: dict[str, Any]) -> bool:
    return any(not item.get("ok") for item in _diagnostic_items(section))


async def run_connectivity_diagnostics() -> dict[str, Any]:
    diagnostics_completed = False
    targets = _targets()
    host = _host()
    diagnostics: dict[str, Any] = {"diagnostics_completed": False}
    try:
        diagnostics["dns"] = await _safe_stage("dns", lambda: resolve_dns(host))
        diagnostics["tcp"] = await _safe_stage("tcp", lambda: check_tcp(host, 443))
        httpx_result = await _safe_stage("httpx", lambda: check_httpx(targets))
        diagnostics["httpx"] = httpx_result
        playwright_result = await _safe_stage("playwright", lambda: check_playwright(targets))
        diagnostics["playwright"] = playwright_result

        if isinstance(httpx_result, dict) and isinstance(playwright_result, dict) and _any_ok(httpx_result) and _any_failed(playwright_result):
            diagnostics["playwright_variants"] = {
                "chromium_launch_args": await _safe_stage("playwright variants", lambda: check_playwright(targets, launch_args=["--disable-dev-shm-usage", "--no-sandbox"])),
                "ipv4_preference": await _safe_stage("playwright variants", lambda: check_playwright(targets, launch_args=["--disable-ipv6"])),
                "disable_http2": await _safe_stage("playwright variants", lambda: check_playwright(targets, launch_args=["--disable-http2"])),
                "desktop_user_agent": await _safe_stage("playwright variants", lambda: check_playwright(targets, user_agent=DESKTOP_USER_AGENT)),
            }

        if isinstance(httpx_result, dict) and isinstance(playwright_result, dict) and _all_failed_with_refused([httpx_result, playwright_result]):
            diagnostics["provider_error"] = {"message": "tutu.ru is unreachable from the current hosting network"}
            logger.info("tutu connectivity provider error", extra={"message": diagnostics["provider_error"]["message"]})

        diagnostics_completed = True
        return diagnostics
    finally:
        diagnostics["diagnostics_completed"] = diagnostics_completed
