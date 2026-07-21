from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain import TransportClass


@dataclass(frozen=True)
class AvailabilityPolicy:
    passengers: int
    preferred_classes: tuple[TransportClass, ...] = ()
    require_same_class_for_all_segments: bool = False
    require_group_together: bool = True
    allow_split_group: bool = False
    minimum_seats_per_segment: int | None = None

    def __post_init__(self) -> None:
        if self.passengers < 1:
            raise ValueError("passengers must be greater than zero")
        if self.minimum_seats_per_segment is not None and self.minimum_seats_per_segment < 1:
            raise ValueError("minimum_seats_per_segment must be greater than zero")
        if self.require_group_together and self.allow_split_group:
            raise ValueError("allow_split_group cannot be true when require_group_together is true")

    @classmethod
    def for_group(
        cls,
        passengers: int,
        preferred_classes: tuple[TransportClass, ...] = (),
        require_group_together: bool = True,
        allow_split_group: bool = False,
    ) -> "AvailabilityPolicy":
        return cls(
            passengers=passengers,
            preferred_classes=preferred_classes,
            require_group_together=require_group_together,
            allow_split_group=allow_split_group,
        )

    @classmethod
    def split_group(cls, passengers: int) -> "AvailabilityPolicy":
        return cls(passengers=passengers, require_group_together=False, allow_split_group=True)

    @classmethod
    def coupe_only(cls, passengers: int) -> "AvailabilityPolicy":
        return cls(passengers=passengers, preferred_classes=(TransportClass.COUPE,))

    @property
    def required_seats_per_segment(self) -> int:
        if self.minimum_seats_per_segment is not None:
            return self.minimum_seats_per_segment
        if self.allow_split_group and not self.require_group_together:
            return 1
        return self.passengers

    def accepts_class(self, transport_class: TransportClass) -> bool:
        return not self.preferred_classes or transport_class in self.preferred_classes

    def has_enough_seats(self, seats: int) -> bool:
        return seats >= self.required_seats_per_segment


@dataclass(frozen=True)
class SegmentAvailability:
    segment_id: str
    is_available: bool
    available_seats: int
    requested_passengers: int
    transport_class: TransportClass | None
    checked_at: datetime
    source: str
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    stale_after_seconds: int | None = None

    @property
    def is_stale(self) -> bool:
        if self.stale_after_seconds is None:
            return False
        checked = self.checked_at if self.checked_at.tzinfo else self.checked_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - checked).total_seconds() > self.stale_after_seconds


@dataclass(frozen=True)
class RouteAvailability:
    is_available: bool
    requested_passengers: int
    minimum_available_seats: int
    checked_at: datetime
    segment_results: tuple[SegmentAvailability, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    stale_after_seconds: int | None = None

    @property
    def is_stale(self) -> bool:
        if any(result.is_stale for result in self.segment_results):
            return True
        if self.stale_after_seconds is None:
            return False
        checked = self.checked_at if self.checked_at.tzinfo else self.checked_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - checked).total_seconds() > self.stale_after_seconds

    @property
    def min_available_seats(self) -> int:
        return self.minimum_available_seats

    @property
    def total_available_seats(self) -> int:
        return self.minimum_available_seats


AvailabilityResult = RouteAvailability
