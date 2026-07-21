from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NotificationType(StrEnum):
    NEW_ROUTE = "new_route"
    SEATS_AVAILABLE = "seats_available"
    BETTER_ROUTE = "better_route"
    PRICE_CHANGED = "price_changed"
    MONITORING_FAILED = "monitoring_failed"
    MONITORING_RESUMED = "monitoring_resumed"


class NotificationSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    saved_search_id: str
    type: NotificationType
    title: str
    message: str
    is_read: bool = False
    severity: NotificationSeverity = NotificationSeverity.INFO
    metadata: dict[str, Any] = Field(default_factory=dict)
