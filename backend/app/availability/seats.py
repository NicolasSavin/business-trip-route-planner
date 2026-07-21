from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain import TransportClass


class BerthPosition(StrEnum):
    LOWER = "lower"
    UPPER = "upper"
    UNKNOWN = "unknown"


class GenderRestriction(StrEnum):
    MALE = "male"
    FEMALE = "female"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SeatPreferences:
    passengers: int
    prefer_lower: bool = False
    prefer_upper: bool = False
    require_same_compartment: bool = False
    require_empty_compartment: bool = False
    require_same_carriage: bool = True
    require_adjacent: bool = False
    exclude_side_berths: bool = False
    gender: GenderRestriction | None = None

    def __post_init__(self) -> None:
        if self.passengers < 1:
            raise ValueError("Количество пассажиров должно быть больше нуля")


@dataclass(frozen=True)
class RailwayPlace:
    provider: str
    place_number: str
    carriage_number: str
    transport_class: TransportClass
    place_type: str = "unknown"
    berth_position: BerthPosition = BerthPosition.UNKNOWN
    compartment_number: str | None = None
    is_side: bool = False
    gender_restriction: GenderRestriction = GenderRestriction.UNKNOWN
    is_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeatAllocationResult:
    matches_preferences: bool
    selected_places: tuple[RailwayPlace, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RailwayCarriageAvailability:
    provider: str
    carriage_number: str
    transport_class: TransportClass
    service_class: str = "unknown"
    carriage_type: str = "unknown"
    gender_restriction: GenderRestriction = GenderRestriction.UNKNOWN
    available_places_count: int = 0
    places: tuple[RailwayPlace, ...] = ()
    seat_allocation: SeatAllocationResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SeatAllocationService:
    def match(self, places: list[RailwayPlace] | tuple[RailwayPlace, ...], preferences: SeatPreferences) -> SeatAllocationResult:
        candidates = [p for p in places if p.is_available]
        if preferences.exclude_side_berths:
            candidates = [p for p in candidates if not p.is_side]
        if preferences.gender is not None:
            candidates = [p for p in candidates if p.gender_restriction in {GenderRestriction.UNKNOWN, GenderRestriction.MIXED, preferences.gender}]
        if preferences.require_same_carriage:
            candidates = self._largest_group(candidates, lambda p: p.carriage_number)
        if preferences.require_same_compartment:
            candidates = self._largest_group([p for p in candidates if p.compartment_number is not None], lambda p: (p.carriage_number, p.compartment_number))
        if preferences.require_empty_compartment:
            occupied = {(p.carriage_number, p.compartment_number) for p in places if not p.is_available and p.compartment_number is not None}
            candidates = [p for p in candidates if p.compartment_number is not None and (p.carriage_number, p.compartment_number) not in occupied]
        if preferences.prefer_lower:
            lower = [p for p in candidates if p.berth_position == BerthPosition.LOWER]
            if len(lower) >= preferences.passengers:
                candidates = lower
        if preferences.prefer_upper:
            upper = [p for p in candidates if p.berth_position == BerthPosition.UPPER]
            if len(upper) >= preferences.passengers:
                candidates = upper
        candidates = sorted(candidates, key=lambda p: (p.carriage_number, p.compartment_number or "", int(p.place_number) if p.place_number.isdigit() else 10_000, p.place_number))
        if preferences.require_adjacent:
            candidates = self._adjacent(candidates, preferences.passengers)
        if len(candidates) < preferences.passengers:
            return SeatAllocationResult(False, tuple(candidates), ("Недостаточно мест, соответствующих предпочтениям",))
        return SeatAllocationResult(True, tuple(candidates[: preferences.passengers]), ())

    def _largest_group(self, places, key):
        groups = {}
        for place in places:
            groups.setdefault(key(place), []).append(place)
        return max(groups.values(), key=len) if groups else []

    def _adjacent(self, places, count):
        by_car = {}
        for place in places:
            if place.place_number.isdigit():
                by_car.setdefault(place.carriage_number, []).append(place)
        for group in by_car.values():
            nums = {int(p.place_number): p for p in group}
            for start in sorted(nums):
                block = [nums.get(n) for n in range(start, start + count)]
                if all(block):
                    return block
        return []
