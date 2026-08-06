from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RZDStation:
    code: str
    name: str


@dataclass(frozen=True)
class RZDSeat:
    number: str
    carriage_number: str
    carriage_type: str = "unknown"
    compartment_number: str | None = None
    is_available: bool = True


@dataclass(frozen=True)
class RZDTrainAvailability:
    train_number: str
    available_seats: int
    seats: tuple[RZDSeat, ...] = ()
    carriages: tuple[dict[str, Any], ...] = ()
    raw: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class RZDSearchResult:
    origin: RZDStation
    destination: RZDStation
    trains: tuple[RZDTrainAvailability, ...]
    raw: Any = field(default=None, repr=False, compare=False)
