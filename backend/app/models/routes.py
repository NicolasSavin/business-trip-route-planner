from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field
from app.domain import TransportClass, TransportType


class RouteSearchRequest(BaseModel):
    origin: str
    destination: str
    origin_location_id: str | None = None
    origin_provider_code: str | None = None
    origin_location_type: str | None = None
    destination_location_id: str | None = None
    destination_provider_code: str | None = None
    destination_location_type: str | None = None
    departure_date: date
    passengers: int = Field(ge=1, le=100)
    allowed_transport: list[TransportType] = Field(min_length=1)
    max_transfers: Literal[0, 1, 2] = 1
    minimum_transfer_minutes: int = Field(default=30, ge=0)
    preferred_classes: list[TransportClass] = Field(default_factory=list)
    require_group_together: bool = True
    allow_split_group: bool = False


class RouteSegment(BaseModel):
    id: str
    provider: str | None = None
    origin: str
    destination: str
    transport_type: TransportType
    number: str
    departure_time: datetime
    arrival_time: datetime
    available_seats: int
    origin_station: str | None = None
    destination_station: str | None = None
    carrier: str | None = None
    source: str | None = None
    availability_message: str | None = None


class SegmentAvailability(BaseModel):
    segment_id: str
    is_available: bool
    available_seats: int
    origin_station: str | None = None
    destination_station: str | None = None
    carrier: str | None = None
    source: str | None = None
    availability_message: str | None = None
    requested_passengers: int
    transport_class: TransportClass | None
    checked_at: datetime
    source: str
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    stale_after_seconds: int | None = None
    is_stale: bool = False


class RouteAvailability(BaseModel):
    is_available: bool
    requested_passengers: int
    minimum_available_seats: int
    checked_at: datetime
    segment_results: list[SegmentAvailability]
    segments: list[SegmentAvailability] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    stale_after_seconds: int | None = None
    is_stale: bool = False

    @property
    def total_available_seats(self) -> int:
        return self.minimum_available_seats

    @property
    def min_available_seats(self) -> int:
        return self.minimum_available_seats


class RouteOption(BaseModel):
    id: str
    provider: str | None = None
    origin: str
    destination: str
    segments: list[RouteSegment]
    transfer_city: str | None = None
    transfer_duration_minutes: int | None = None
    total_duration_minutes: int
    transfers_count: int
    is_available_for_group: bool
    score: float | None = None
    rank: int | None = None
    explanation: str | None = None
    warnings: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    availability: RouteAvailability | None = None


class RouteSearchResponse(BaseModel):
    routes: list[RouteOption]
