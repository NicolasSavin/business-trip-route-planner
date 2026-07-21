from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.browser.config import BrowserConfiguration
from app.browser.metrics import BrowserMetrics
from app.browser.models import BrowserHealth, BrowserStatus


class BrowserManager:
    def __init__(self, config: BrowserConfiguration | None = None, metrics: BrowserMetrics | None = None) -> None:
        self.config = config or BrowserConfiguration.from_env()
        self.metrics = metrics or BrowserMetrics()
        self.started_at: datetime | None = None
        self._running = False
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._version: str | None = None
        self._installed = self._detect_playwright()

    @property
    def browser(self) -> Any | None:
        return self._browser

    def _detect_playwright(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return True

    def start(self) -> None:
        if not self.config.playwright_enabled:
            self._running = False
            return
        if self._running and self._browser is not None:
            return
        if not self._installed:
            raise RuntimeError("Playwright package is not installed")
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_options: dict[str, Any] = {"headless": self.config.headless}
        if self.config.proxy:
            launch_options["proxy"] = {"server": self.config.proxy}
        self._browser = self._playwright.chromium.launch(**launch_options)
        self._version = self._browser.version
        self._running = True
        self.started_at = datetime.now(timezone.utc)
        self.metrics.active_browsers += 1

    def stop(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        if self._running and self.started_at is not None:
            lifetime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
            self.metrics.record_browser_closed(lifetime)
            self.metrics.active_browsers = max(0, self.metrics.active_browsers - 1)
        self._running = False
        self.started_at = None

    def graceful_shutdown(self) -> None:
        self.stop()

    def restart(self) -> None:
        self.stop()
        self.metrics.record_restart()
        self.start()

    def ensure_browser(self) -> Any:
        if not self._running or self._browser is None:
            self.start()
        if self._browser is None:
            raise RuntimeError("Browser is disabled or unavailable")
        return self._browser

    def version(self) -> str:
        if self._version:
            return self._version
        return "playwright-not-running" if self._installed else "playwright-not-installed"

    def health(self) -> BrowserHealth:
        if not self.config.playwright_enabled:
            return BrowserHealth(False, self._installed, True, BrowserStatus.DISABLED, "Playwright disabled", version=self.version())
        if not self._installed:
            return BrowserHealth(True, False, False, BrowserStatus.DEGRADED, "Playwright package is not installed", version=self.version())
        return BrowserHealth(True, True, self._running, BrowserStatus.RUNNING if self._running else BrowserStatus.READY, "Playwright browser is ready" if self._running else "Playwright installed; browser is ready to start", version=self.version())
