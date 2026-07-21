from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrowserMetrics:
    active_browsers: int = 0
    active_sessions: int = 0
    pages_opened: int = 0
    crashes: int = 0
    restarts: int = 0
    total_lifetime_seconds: float = 0.0
    completed_browsers: int = 0

    @property
    def average_lifetime(self) -> float:
        if self.completed_browsers == 0:
            return 0.0
        return self.total_lifetime_seconds / self.completed_browsers

    def record_page_opened(self) -> None:
        self.pages_opened += 1

    def record_restart(self) -> None:
        self.restarts += 1

    def record_crash(self) -> None:
        self.crashes += 1

    def record_browser_closed(self, lifetime_seconds: float) -> None:
        self.completed_browsers += 1
        self.total_lifetime_seconds += max(0.0, lifetime_seconds)
