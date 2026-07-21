from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.routes import RouteOption, RouteSearchRequest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LastCheckStatus(StrEnum):
    NEVER_CHECKED = "never_checked"
    CHECKING = "checking"
    ROUTES_FOUND = "routes_found"
    NO_AVAILABLE_ROUTES = "no_available_routes"
    FAILED = "failed"


class SavedSearch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    origin: str
    destination: str
    departure_date: RouteSearchRequest.model_fields["departure_date"].annotation
    passengers: int = Field(ge=1, le=100)
    allowed_transport: RouteSearchRequest.model_fields["allowed_transport"].annotation = Field(min_length=1)
    max_transfers: Literal[0, 1, 2] = 1
    minimum_transfer_minutes: int = Field(default=30, ge=0)
    preferred_classes: RouteSearchRequest.model_fields["preferred_classes"].annotation = Field(default_factory=list)
    require_group_together: bool = True
    allow_split_group: bool = False
    monitoring_enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_checked_at: datetime | None = None
    last_check_status: LastCheckStatus = LastCheckStatus.NEVER_CHECKED
    last_routes_count: int = 0
    last_available_routes_count: int = 0
    last_error: str | None = None

    def to_search_request(self) -> RouteSearchRequest:
        return RouteSearchRequest(
            origin=self.origin,
            destination=self.destination,
            departure_date=self.departure_date,
            passengers=self.passengers,
            allowed_transport=self.allowed_transport,
            max_transfers=self.max_transfers,
            minimum_transfer_minutes=self.minimum_transfer_minutes,
            preferred_classes=self.preferred_classes,
            require_group_together=self.require_group_together,
            allow_split_group=self.allow_split_group,
        )


class SavedSearchCreate(RouteSearchRequest):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    monitoring_enabled: bool = True


class SavedSearchUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    monitoring_enabled: bool | None = None
    origin: str | None = None
    destination: str | None = None
    departure_date: RouteSearchRequest.model_fields["departure_date"].annotation | None = None
    passengers: int | None = Field(default=None, ge=1, le=100)
    allowed_transport: RouteSearchRequest.model_fields["allowed_transport"].annotation | None = None
    max_transfers: Literal[0, 1, 2] | None = None
    minimum_transfer_minutes: int | None = Field(default=None, ge=0)
    preferred_classes: RouteSearchRequest.model_fields["preferred_classes"].annotation | None = None
    require_group_together: bool | None = None
    allow_split_group: bool | None = None


class SavedSearchCheckResponse(BaseModel):
    saved_search: SavedSearch
    routes: list[RouteOption]
