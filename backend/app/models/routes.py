from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, AliasChoices
from app.domain import TransportClass, TransportType


class SeatPreferencesRequest(BaseModel):
    preferred_classes: list[TransportClass] = Field(default_factory=list)
    berth_preference: Literal["any", "lower_only", "upper_only"] = "any"
    require_same_compartment: bool = False
    require_empty_compartment: bool = False
    require_same_carriage: bool = True
    require_adjacent: bool = False
    exclude_side_berths: bool = False
    gender: Literal["male", "female", "mixed"] | None = None
    allow_split_group: bool = False
    maximum_compartments: int | None = Field(default=None, ge=1)
    strict_preferences: bool = True


class RouteSearchRequest(BaseModel):
    origin: str
    destination: str
    origin_location_id: str | None = None
    origin_provider_code: str | None = None
    origin_location_type: str | None = None
    destination_location_id: str | None = None
    destination_provider_code: str | None = None
    destination_location_type: str | None = None
    departure_date: date = Field(validation_alias=AliasChoices("departure_date", "date"))
    passengers: int = Field(ge=1, le=100)
    allowed_transport: list[TransportType] = Field(default_factory=lambda: [TransportType.TRAIN, TransportType.BUS], validation_alias=AliasChoices("allowed_transport", "allowed_transport_types"))
    max_transfers: Literal[0, 1, 2, 3] = 1
    minimum_transfer_minutes: int = Field(default=30, ge=0)
    maximum_transfer_minutes: int = Field(default=360, ge=0)
    maximum_total_duration_minutes: int | None = Field(default=None, ge=1)
    allow_overnight_transfer: bool = True
    strict_availability: bool = True
    seat_policy_scope: Literal["every_rail_segment", "first_rail_segment_only", "any_rail_segment"] = "every_rail_segment"
    seat_preferences: SeatPreferencesRequest | None = None
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
    availability_source: str | None = None
    availability_status: str | None = None
    selected_places: list[str] = Field(default_factory=list)
    selected_carriages: list[str] = Field(default_factory=list)
    selected_compartments: list[str] = Field(default_factory=list)
    availability_message: str | None = None


class SegmentAvailability(BaseModel):
    segment_id: str
    is_available: bool
    available_seats: int
    origin_station: str | None = None
    destination_station: str | None = None
    carrier: str | None = None
    source: str | None = None
    availability_source: str | None = None
    availability_status: str | None = None
    selected_places: list[str] = Field(default_factory=list)
    selected_carriages: list[str] = Field(default_factory=list)
    selected_compartments: list[str] = Field(default_factory=list)
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
    transfers: list[dict] = Field(default_factory=list)
    total_wait_minutes: int = 0
    total_price: float | None = None
    total_duration_minutes: int
    transfers_count: int
    is_available_for_group: bool
    score: float | None = None
    rank: int | None = None
    explanation: str | None = None
    warnings: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    availability: RouteAvailability | None = None


class SearchSummary(BaseModel):
    segments_loaded: int = 0
    candidate_journeys: int = 0
    availability_checks: int = 0
    confirmed_routes: int = 0
    partially_confirmed_routes: int = 0
    rejected_routes: int = 0


class RouteSearchResponse(BaseModel):
    routes: list[RouteOption]
    partially_confirmed_routes: list[RouteOption] = Field(default_factory=list)
    rejected_routes: list[RouteOption] = Field(default_factory=list)
    search_summary: SearchSummary = Field(default_factory=SearchSummary)
