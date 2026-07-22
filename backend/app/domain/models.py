from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class TransportType(StrEnum):
    TRAIN = "train"
    BUS = "bus"


class TransportClass(StrEnum):
    ECONOMY = "economy"
    COUPE = "coupe"
    PLATZKART = "platzkart"
    SLEEPER = "sleeper"
    SEATED = "seated"
    EXPRESS = "express"


@dataclass(frozen=True)
class City:
    name: str


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    city: City


@dataclass(frozen=True)
class Carrier:
    id: str
    name: str


@dataclass(frozen=True)
class Availability:
    available_seats: int | None


@dataclass(frozen=True)
class TransportSegment:
    id: str
    provider: str
    carrier: Carrier
    transport_type: TransportType
    transport_class: TransportClass | None
    vehicle_number: str
    origin_city: City
    origin_station: Station
    destination_city: City
    destination_station: Station
    departure_datetime: datetime
    arrival_datetime: datetime
    duration_minutes: int
    available_seats: int | None
    price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transfer:
    from_segment: TransportSegment
    to_segment: TransportSegment
    duration_minutes: int
    city: City
    is_night: bool = False
    transfer_type: str = "unknown"
    estimated_transfer_minutes: int = 0
    warnings: tuple[str, ...] = ()
    station_change: bool = False
    city_change: bool = False


@dataclass(frozen=True)
class Route:
    segments: tuple[TransportSegment, ...]
    transfers: tuple[Transfer, ...] = ()

    @property
    def total_duration_minutes(self) -> int:
        return int((self.segments[-1].arrival_datetime - self.segments[0].departure_datetime).total_seconds() // 60)

    @property
    def transfers_count(self) -> int:
        return max(0, len(self.segments) - 1)

    @property
    def min_available_seats(self) -> int:
        return min((segment.available_seats or 0) for segment in self.segments)


@dataclass(frozen=True)
class RouteOption:
    route: Route
    score: float
    rank: int = 0
    explanation: str = ""
    warnings: tuple[str, ...] = ()
    advantages: tuple[str, ...] = ()
    availability: Any | None = None


class TransportProvider(Protocol):
    def get_segments(self, *args: Any, **kwargs: Any) -> list[TransportSegment]: ...


class StationResolverProtocol(Protocol):
    def resolve_city_names(self, query: str, segments: list[TransportSegment]) -> tuple[str, ...]: ...


class NearbyCityResolverProtocol(Protocol):
    def alternatives_for(self, city: str) -> tuple[str, ...]: ...


class TransferEngineProtocol(Protocol):
    def build_transfer(self, first: TransportSegment, second: TransportSegment) -> Transfer: ...


class ExplanationServiceProtocol(Protocol):
    def explain(self, route: Route, score: float, rank: int, best_score: float | None = None) -> tuple[str, tuple[str, ...], tuple[str, ...]]: ...


class RouteComparatorProtocol(Protocol):
    def rank(self, routes: list[Route]) -> list[RouteOption]: ...
