from __future__ import annotations
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

class AvailabilityStatus(str, Enum):
    CONFIRMED="confirmed"; PARTIALLY_CONFIRMED="partially_confirmed"; UNAVAILABLE="unavailable"; UNKNOWN="unknown"; PROVIDER_ERROR="provider_error"

class AvailabilityCheckRequest(BaseModel):
    origin: str; destination: str; departure_date: date; train_number: str | None = None; departure_time: datetime | None = None
    passengers: int = Field(default=1, ge=1, le=8)
    preferred_classes: list[str] = Field(default_factory=list)
    berth_preference: Literal["any","lower_only","upper_only"] = "any"
    require_same_carriage: bool = True; require_same_compartment: bool = False; maximum_compartments: int | None = Field(default=None, ge=1)

class JourneyAvailabilityRequest(BaseModel):
    segments: list[AvailabilityCheckRequest]

class Diagnostics(BaseModel):
    matched_by: str | None = None; page_url: str | None = None; screenshots: list[str] = Field(default_factory=list); html_artifacts: list[str] = Field(default_factory=list)
    selected_inputs: dict[str, Any] = Field(default_factory=dict)
    station_steps: list[dict[str, Any]] = Field(default_factory=list)
    origin_station_selection: dict[str, Any] = Field(default_factory=dict)
    destination_station_selection: dict[str, Any] = Field(default_factory=dict)
    popup_candidates: dict[str, list[Any]] = Field(default_factory=dict)
    autocomplete_discovery: dict[str, Any] = Field(default_factory=dict)
    field_resolution_collision: dict[str, Any] | None = None
    origin_destination_same_element: bool | None = None
    form_reacquired_after_origin: bool | None = None
    final_origin_value: str | None = None
    final_destination_value: str | None = None
    route_fields_verification: dict[str, Any] = Field(default_factory=dict)
    route_submit_button: dict[str, Any] = Field(default_factory=dict)
    before_submit_url: str | None = None
    after_submit_url: str | None = None
    submit_selector: str | None = None
    navigation_result: str | None = None
    network_events: dict[str, Any] = Field(default_factory=dict)
    autocomplete_requests: dict[str, Any] = Field(default_factory=dict)
    autocomplete_responses: dict[str, Any] = Field(default_factory=dict)
    autocomplete_request_failures: dict[str, Any] = Field(default_factory=dict)
    network_summary: dict[str, Any] = Field(default_factory=dict)
    post_submit_steps: list[dict[str, Any]] = Field(default_factory=list)
    post_submit_result: dict[str, Any] = Field(default_factory=dict)
    post_submit_network_events: list[dict[str, Any]] = Field(default_factory=list)
    post_submit_network_summary: dict[str, Any] = Field(default_factory=dict)
    url_observations: dict[str, str] = Field(default_factory=dict)
    remaining_budget_ms: int | None = None
    deadline_exceeded: bool = False
    timeout_stage: str | None = None
    route_field_invariants: dict[str, Any] = Field(default_factory=dict)
    sale_period_route_collision_detected: bool = False
    elapsed_ms: int | None = None
    destination_attempt_count: int | None = None
    origin_recovery_count: int | None = None
    origin_guard: dict[str, Any] = Field(default_factory=dict)
    route_form_diagnostics: dict[str, Any] = Field(default_factory=dict)
    route_form_contract: dict[str, Any] = Field(default_factory=dict)
    direct_route_navigation: dict[str, Any] = Field(default_factory=dict)
    route_open_attempts: list[dict[str, Any]] = Field(default_factory=list)
    tutu_dom_contract: dict[str, Any] = Field(default_factory=dict)
    tutu_dom_contract_hash: str | None = None
    submit_strategy: str | None = None
    artifacts_capture_skipped: bool | None = None
    artifacts_capture_skip_reason: str | None = None
    artifacts_capture_elapsed_ms: int | None = None
    terminal_failure_reason: str | None = None

class AvailabilityCheckResponse(BaseModel):
    status: AvailabilityStatus; matched_train: bool = False; train_number: str | None = None; available_seats: int | None = None
    selected_places: list[str] = Field(default_factory=list); selected_carriages: list[str] = Field(default_factory=list); selected_compartments: list[str] = Field(default_factory=list)
    transport_class: str | None = None; same_carriage: bool = False; same_compartment: bool = False; lower_berths_confirmed: bool = False
    price: float | None = None; currency: str = "RUB"; message: str = ""; warnings: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)); diagnostics: Diagnostics = Field(default_factory=Diagnostics)

class JourneyAvailabilityResponse(BaseModel):
    status: AvailabilityStatus; segments: list[AvailabilityCheckResponse]; checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)); warnings: list[str] = Field(default_factory=list)
