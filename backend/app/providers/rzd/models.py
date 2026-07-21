from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain import TransportClass


@dataclass(frozen=True)
class RzdStation:
    code: str
    name: str
    city: str


@dataclass(frozen=True)
class RzdCarAvailability:
    car_type: TransportClass
    seats: int
    min_price: float | None = None


@dataclass(frozen=True)
class RzdTrainOption:
    train_number: str
    train_name: str | None
    origin: RzdStation
    destination: RzdStation
    departure_datetime: datetime
    arrival_datetime: datetime
    cars: tuple[RzdCarAvailability, ...]
    carrier: str = "РЖД"
