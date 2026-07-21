from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TutuTrainDTO:
    train_reference: str
    train_number: str
    departure: datetime
    arrival: datetime
    origin: str
    destination: str


@dataclass(frozen=True)
class TutuCarriageDTO:
    carriage_number: str
    carriage_type: str | None
    service_class: str | None
    gender_restriction: str | None
    available_places_count: int


@dataclass(frozen=True)
class TutuPlaceDTO:
    place_number: str
    place_type: str | None
    berth_position: str | None
    compartment_number: str | None
    carriage_number: str
    is_side: bool | None
    gender_restriction: str | None
    is_available: bool
