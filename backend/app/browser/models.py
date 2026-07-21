from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class BrowserStatus(StrEnum):
    DISABLED = "disabled"
    READY = "ready"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPED = "stopped"


@dataclass(frozen=True)
class BrowserProviderCapability:
    javascript: bool = True
    screenshots: bool = True
    html: bool = True
    pdf: bool = True
    cookies: bool = True
    forms: bool = True
    downloads: bool = True


@dataclass(frozen=True)
class BrowserHealth:
    enabled: bool
    configured: bool
    healthy: bool
    status: BrowserStatus
    message: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str | None = None
