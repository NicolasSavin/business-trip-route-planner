from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field
from app.domain import TransportClass, TransportType


class RouteSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: date
    passengers: int = Field(ge=1, le=100)
    allowed_transport: list[TransportType] = Field(min_length=1)
    max_transfers: Literal[0, 1, 2] = 1
    minimum_transfer_minutes: int = Field(default=30, ge=0)


class RouteSegment(BaseModel):
    id: str
    origin: str
    destination: str
    transport_type: TransportType
    number: str
    departure_time: datetime
    arrival_time: datetime
    available_seats: int


class SegmentAvailability(BaseModel):
    segment_id: str
    is_available: bool
    available_seats: int
    transport_class: TransportClass
    checked_at: datetime
    source: str
    warnings: list[str] = Field(default_factory=list)


class RouteAvailability(BaseModel):
    is_available: bool
    total_available_seats: int
    min_available_seats: int
    checked_at: datetime
    source: str
    segment_results: list[SegmentAvailability]
    warnings: list[str] = Field(default_factory=list)


class RouteOption(BaseModel):
    id: str
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
