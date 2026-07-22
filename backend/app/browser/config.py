from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BrowserConfiguration:
    playwright_enabled: bool = False
    headless: bool = True
    pool_size: int = 1
    timeout: int = 30
    idle_timeout_seconds: int = 120
    lazy_start: bool = True
    user_agent: str = ""
    proxy: str = ""

    @classmethod
    def from_env(cls) -> "BrowserConfiguration":
        return cls(
            playwright_enabled=_bool(os.getenv("TUTU_PLAYWRIGHT_ENABLED"), _bool(os.getenv("PLAYWRIGHT_ENABLED"), False)),
            headless=_bool(os.getenv("BROWSER_HEADLESS"), True),
            pool_size=max(1, int(os.getenv("BROWSER_POOL_SIZE", "1"))),
            timeout=max(1, int(os.getenv("BROWSER_TIMEOUT", "30"))),
            user_agent=os.getenv("USER_AGENT", ""),
            proxy=os.getenv("PROXY", ""),
            idle_timeout_seconds=max(1, int(os.getenv("BROWSER_IDLE_TIMEOUT_SECONDS", "120"))),
            lazy_start=_bool(os.getenv("PLAYWRIGHT_LAZY_START"), True),
        )

    @property
    def configured(self) -> bool:
        return self.playwright_enabled

    def with_playwright_enabled(self) -> "BrowserConfiguration":
        return BrowserConfiguration(
            playwright_enabled=True,
            headless=self.headless,
            pool_size=self.pool_size,
            timeout=self.timeout,
            user_agent=self.user_agent,
            proxy=self.proxy,
            idle_timeout_seconds=self.idle_timeout_seconds,
            lazy_start=self.lazy_start,
        )
