from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain import TransportClass


@dataclass(frozen=True)
class AvailabilityPolicy:
    passengers: int
    group_must_travel_together: bool = True
    allow_split_group: bool = False
    required_classes: tuple[TransportClass, ...] = ()

    @classmethod
    def for_group(cls, passengers: int) -> "AvailabilityPolicy":
        return cls(passengers=passengers)

    @classmethod
    def split_group(cls, passengers: int) -> "AvailabilityPolicy":
        return cls(passengers=passengers, group_must_travel_together=False, allow_split_group=True)

    @classmethod
    def coupe_only(cls, passengers: int) -> "AvailabilityPolicy":
        return cls(passengers=passengers, required_classes=(TransportClass.COUPE,))

    def accepts_class(self, transport_class: TransportClass) -> bool:
        return not self.required_classes or transport_class in self.required_classes

    def has_enough_seats(self, seats: int) -> bool:
        if self.allow_split_group and not self.group_must_travel_together:
            return seats > 0
        return seats >= self.passengers


@dataclass(frozen=True)
class SegmentAvailability:
    segment_id: str
    is_available: bool
    available_seats: int
    transport_class: TransportClass
    checked_at: datetime
    source: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AvailabilityResult:
    is_available: bool
    segment_results: tuple[SegmentAvailability, ...]
    checked_at: datetime
    source: str
    total_available_seats: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def min_available_seats(self) -> int:
        if not self.segment_results:
            return 0
        return min(result.available_seats for result in self.segment_results)
