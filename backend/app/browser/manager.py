from __future__ import annotations

import os
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any

from app.browser.config import BrowserConfiguration
from app.browser.exceptions import BrowserUnavailableError
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
        self._unavailable_reason: str | None = None
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

    def startup_diagnostics(self) -> dict[str, str | bool]:
        executable_path, startup_exception = self._chromium_executable_path()
        return {
            "playwright_version": self._playwright_package_version(),
            "playwright_browsers_path": os.getenv("PLAYWRIGHT_BROWSERS_PATH", "not-set"),
            "browser_executable_path": executable_path or "unavailable",
            "browser_exists": bool(executable_path and os.path.exists(executable_path)),
            "browser_manager_status": self.health().status.value,
            "startup_exception": startup_exception or "none",
        }

    def _playwright_package_version(self) -> str:
        try:
            return package_version("playwright")
        except PackageNotFoundError:
            return "not-installed"

    def _chromium_executable_path(self) -> tuple[str | None, str | None]:
        if not self._installed:
            return None, "Playwright package is not installed"
        from playwright.sync_api import sync_playwright

        playwright = None
        try:
            playwright = sync_playwright().start()
            return playwright.chromium.executable_path, None
        except Exception as exc:
            return None, str(exc) or exc.__class__.__name__
        finally:
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def start(self) -> None:
        if not self.config.playwright_enabled:
            self._running = False
            return
        if self._running and self._browser is not None:
            return
        if not self._installed:
            self._unavailable_reason = "Playwright package is not installed"
            return
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        self._unavailable_reason = None
        try:
            self._playwright = sync_playwright().start()
            launch_options: dict[str, Any] = {"headless": self.config.headless}
            if self.config.proxy:
                launch_options["proxy"] = {"server": self.config.proxy}
            self._browser = self._playwright.chromium.launch(**launch_options)
        except PlaywrightError as exc:
            self._unavailable_reason = f"Chromium is unavailable: {self._summarize_launch_error(exc)}"
            self._cleanup_failed_start()
            return
        except Exception as exc:
            self._unavailable_reason = f"Browser could not start: {exc}"
            self._cleanup_failed_start()
            return
        self._version = self._browser.version
        self._running = True
        self.started_at = datetime.now(timezone.utc)
        self.metrics.active_browsers += 1

    def _cleanup_failed_start(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._running = False
        self.started_at = None

    def _summarize_launch_error(self, exc: Exception) -> str:
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        if "Executable doesn't exist" in str(exc) or "Please run" in str(exc):
            return "Chromium browser files are not installed; run `python -m playwright install chromium` during build."
        return message

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
            raise BrowserUnavailableError(self._unavailable_reason or "Browser is disabled or unavailable")
        return self._browser

    def version(self) -> str:
        if self._version:
            return self._version
        if not self._installed:
            return "playwright-not-installed"
        if self._unavailable_reason:
            return "chromium-unavailable"
        return "playwright-not-running"

    def health(self) -> BrowserHealth:
        if not self.config.playwright_enabled:
            return BrowserHealth(False, self._installed, True, BrowserStatus.DISABLED, "Playwright disabled", version=self.version())
        if not self._installed:
            return BrowserHealth(True, False, False, BrowserStatus.DEGRADED, "Playwright package is not installed", version=self.version())
        if self._unavailable_reason:
            return BrowserHealth(True, True, False, BrowserStatus.DEGRADED, self._unavailable_reason, version=self.version())
        return BrowserHealth(True, True, self._running, BrowserStatus.RUNNING if self._running else BrowserStatus.READY, "Playwright browser is ready" if self._running else "Playwright installed; browser is ready to start", version=self.version())
