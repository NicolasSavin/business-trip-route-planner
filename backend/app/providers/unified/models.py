from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain import TransportType


class ProviderPriority(IntEnum):
    HIGH = 100
    NORMAL = 50
    LOW = 10


class ProviderHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class ProviderCapabilities(BaseModel):
    supported_transport: list[TransportType] = Field(default_factory=list)
    supports_availability: bool = False
    supports_realtime: bool = False


class ProviderRegistration(BaseModel):
    id: str
    name: str
    priority: int = ProviderPriority.NORMAL
    enabled: bool = True
    health: ProviderHealth = ProviderHealth.HEALTHY
    capabilities: ProviderCapabilities
    routes_found: int = 0
    last_checked_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
