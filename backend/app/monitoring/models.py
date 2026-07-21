from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MonitoringStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class MonitoringPolicy(BaseModel):
    include_unavailable: bool = True
    score_tolerance: float = 0.0001


class MonitoringHistory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    saved_search_id: str
    checked_at: datetime = Field(default_factory=utc_now)
    duration_ms: int
    routes_found: int
    available_routes: int
    best_score: float | None = None
    status: MonitoringStatus
    change_detected: bool = False
    summary: str
    changes: list[str] = Field(default_factory=list)
    route_ids: list[str] = Field(default_factory=list)
    free_seats: int = 0
    provider_ids: list[str] = Field(default_factory=list)


class MonitoringResult(BaseModel):
    saved_search_id: str
    is_changed: bool
    changes: list[str] = Field(default_factory=list)
    summary: str
    timestamp: datetime = Field(default_factory=utc_now)
    history: MonitoringHistory


class MonitoringRunLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    saved_search_id: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: MonitoringStatus = MonitoringStatus.SUCCESS
    summary: str = ""
