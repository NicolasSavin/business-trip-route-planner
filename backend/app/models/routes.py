from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field
from app.domain import TransportType


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


class RouteSearchResponse(BaseModel):
    routes: list[RouteOption]
