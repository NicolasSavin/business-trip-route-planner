from __future__ import annotations

from datetime import datetime, timezone

from app.browser.config import BrowserConfiguration
from app.browser.metrics import BrowserMetrics
from app.browser.models import BrowserHealth, BrowserStatus


class BrowserManager:
    def __init__(self, config: BrowserConfiguration | None = None, metrics: BrowserMetrics | None = None) -> None:
        self.config = config or BrowserConfiguration.from_env()
        self.metrics = metrics or BrowserMetrics()
        self.started_at: datetime | None = None
        self._running = False

    def start(self) -> None:
        if not self.config.playwright_enabled:
            self._running = False
            return
        self._running = True
        self.started_at = datetime.now(timezone.utc)
        self.metrics.active_browsers += 1

    def stop(self) -> None:
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

    def version(self) -> str:
        return "mock-browser-infrastructure/0.1"

    def health(self) -> BrowserHealth:
        if not self.config.playwright_enabled:
            return BrowserHealth(False, False, True, BrowserStatus.DISABLED, "Playwright пока не активирован", version=self.version())
        return BrowserHealth(True, True, self._running, BrowserStatus.RUNNING if self._running else BrowserStatus.READY, "Инфраструктура готова", version=self.version())
