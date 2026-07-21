from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

SeatValue = int | Literal["Unknown"]


@dataclass(frozen=True)
class TutuPlaywrightSearchRequest:
    origin: str
    destination: str
    date: date
    passengers: int = 1


@dataclass(frozen=True)
class SeatAvailability:
    total: SeatValue = "Unknown"
    upper: SeatValue = "Unknown"
    lower: SeatValue = "Unknown"
    side: SeatValue = "Unknown"
    platzkart: SeatValue = "Unknown"
    coupe: SeatValue = "Unknown"
    sv: SeatValue = "Unknown"
    seated: SeatValue = "Unknown"


@dataclass(frozen=True)
class TutuPlaywrightResult:
    train_number: str
    origin_station: str
    destination_station: str
    departure: datetime
    arrival: datetime
    duration_minutes: int
    transfers: int = 0
    carriage_type: str = "Unknown"
    available_seats: SeatAvailability = field(default_factory=SeatAvailability)
    price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)
