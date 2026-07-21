from __future__ import annotations

from typing import Any

from app.browser.manager import BrowserManager


class BrowserAutomationProvider:
    def __init__(self, manager: BrowserManager | None = None) -> None:
        self.manager = manager or BrowserManager()

    def healthcheck(self) -> bool:
        return self.manager.health().healthy

    def status(self) -> dict[str, Any]:
        health = self.manager.health()
        return {
            "enabled": health.enabled,
            "configured": health.configured,
            "healthy": health.healthy,
            "status": health.status.value,
            "message": health.message,
            "version": health.version,
        }

    def get_segments(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []
