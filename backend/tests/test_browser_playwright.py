from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.browser import BrowserConfiguration, BrowserManager, BrowserMetrics, BrowserPool, BrowserStatus
from app.providers.unified import build_default_registry


class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
    def set_default_timeout(self, _timeout: int) -> None: pass
    async def goto(self, url: str, **_kwargs): self.url = url; return object()
    async def wait_for_load_state(self, _state: str, **_kwargs) -> None: pass
    async def content(self) -> str: return "<html><head><title>Example Domain</title></head><body>ok</body></html>"
    async def screenshot(self, **_kwargs) -> bytes: return b"\x89PNG\r\n\x1a\nfake"
    async def evaluate(self, expression: str, *args):
        if "document.title" in expression: return "Example Domain"
        if "window.location.href" in expression: return self.url
        return None
    async def close(self) -> None: pass

class FakeContext:
    async def new_page(self): return FakePage()
    async def close(self) -> None: pass
    async def cookies(self): return []

class FakeBrowser:
    version = "chromium-fake"
    async def new_context(self, **_kwargs): return FakeContext()
    async def close(self) -> None: pass

class FakeManager(BrowserManager):
    def __init__(self):
        super().__init__(BrowserConfiguration(playwright_enabled=True, pool_size=1), BrowserMetrics())
        self._browser = FakeBrowser(); self._running = True; self._installed = True; self._version = "chromium-fake"
    async def ensure_browser(self): return self._browser


def test_browser_manager_health_ready_when_playwright_enabled():
    manager = BrowserManager(BrowserConfiguration(playwright_enabled=True), BrowserMetrics())
    manager._installed = True
    health = manager.health()
    assert health.configured is True
    assert health.status == BrowserStatus.READY


def test_browser_pool_uses_real_browser_boundary_and_metrics():
    async def run():
        pool = BrowserPool(FakeManager(), max_size=1)
        async with pool.session() as session:
            await session.new_page()
            await session.navigate("https://example.com")
            assert await session.evaluate("() => document.title") == "Example Domain"
            assert len(await session.capture_html()) > 10
            assert (await session.capture_screenshot()).startswith(b"\x89PNG")
        assert pool.metrics.pages_opened == 1
        assert pool.metrics.pages_closed == 1
        assert pool.metrics.active_sessions == 0
        assert pool.metrics.average_page_load_ms >= 0
    asyncio.run(run())


def test_browser_ping_and_screenshot_api(monkeypatch):
    from app.api import browser as browser_api
    from app.main import app
    fake_manager = FakeManager()
    monkeypatch.setattr(browser_api, "_manager", fake_manager)
    monkeypatch.setattr(browser_api, "_pool", BrowserPool(fake_manager, max_size=1))
    client = TestClient(app)
    ping = client.get("/api/v1/browser/ping")
    assert ping.status_code == 200
    payload = ping.json()
    assert payload["title"] == "Example Domain"
    assert payload["url"] == "https://example.com"
    assert payload["html_length"] > 10
    assert payload["browser_version"] == "chromium-fake"
    screenshot = client.get("/api/v1/browser/screenshot")
    assert screenshot.status_code == 200
    assert screenshot.headers["content-type"] == "image/png"
    assert screenshot.content.startswith(b"\x89PNG")


def test_browser_health_endpoint_reports_runtime_singleton(monkeypatch):
    from app.api import browser as browser_api
    from app.main import app

    fake_manager = FakeManager()
    monkeypatch.setattr(browser_api, "_manager", fake_manager)
    monkeypatch.setattr(browser_api, "_pool", BrowserPool(fake_manager, max_size=1))

    payload = TestClient(app).get("/api/v1/browser/health").json()

    assert payload == {
        "playwright_installed": True,
        "browser_running": True,
        "browser_version": "chromium-fake",
        "status": "running",
        "healthy": True,
    }


def test_browser_health_metrics_and_provider_registry_metadata():
    registration = build_default_registry().get("browser_automation")
    assert registration is not None
    assert "playwright_installed" in registration.metadata
    assert "browser_running" in registration.metadata
    assert "browser_version" in registration.metadata
