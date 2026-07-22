from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from typing import Any
from collections import OrderedDict

from app.availability.models import SegmentAvailability as LegacySegmentAvailability


class AvailabilityStatus(StrEnum):
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    UNCONFIRMED = "unconfirmed"
    STALE = "stale"
    PROVIDER_ERROR = "provider_error"


class SeatPolicyScope(StrEnum):
    EVERY_RAIL_SEGMENT = "every_rail_segment"
    FIRST_RAIL_SEGMENT_ONLY = "first_rail_segment_only"
    ANY_RAIL_SEGMENT = "any_rail_segment"


@dataclass(frozen=True)
class SegmentAvailabilityResult:
    segment_id: str
    provider: str
    status: AvailabilityStatus
    schedule_confirmed: bool = True
    seats_confirmed: bool = False
    passengers_supported: bool = False
    available_places_count: int | None = None
    seat_preferences_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    selected_places: tuple[str, ...] = ()
    selected_carriages: tuple[str, ...] = ()
    selected_compartments: tuple[str, ...] = ()
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_stale: bool = False
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy(cls, result: LegacySegmentAvailability, provider: str | None = None) -> "SegmentAvailabilityResult":
        status = AvailabilityStatus.CONFIRMED if result.is_available else AvailabilityStatus.UNAVAILABLE
        if result.is_stale:
            status = AvailabilityStatus.STALE
        reasons = (result.reason,) if result.reason else ()
        return cls(
            segment_id=result.segment_id,
            provider=provider or result.source,
            status=status,
            schedule_confirmed=True,
            seats_confirmed=result.is_available,
            passengers_supported=result.is_available,
            available_places_count=result.available_seats,
            seat_preferences_status=status,
            checked_at=result.checked_at,
            is_stale=result.is_stale,
            reasons=reasons,
            warnings=result.warnings,
        )


@dataclass(frozen=True)
class JourneyAvailabilityResult:
    status: AvailabilityStatus
    segment_results: tuple[SegmentAvailabilityResult, ...]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.status == AvailabilityStatus.CONFIRMED


def aggregate_journey_availability(results: tuple[SegmentAvailabilityResult, ...]) -> JourneyAvailabilityResult:
    reasons = tuple(reason for result in results for reason in result.reasons)
    warnings = tuple(warning for result in results for warning in result.warnings)
    statuses = {result.status for result in results}
    if AvailabilityStatus.PROVIDER_ERROR in statuses:
        status = AvailabilityStatus.PROVIDER_ERROR
    elif AvailabilityStatus.UNAVAILABLE in statuses:
        status = AvailabilityStatus.UNAVAILABLE
    elif results and all(result.status == AvailabilityStatus.CONFIRMED for result in results):
        status = AvailabilityStatus.CONFIRMED
    elif AvailabilityStatus.STALE in statuses:
        status = AvailabilityStatus.STALE
    else:
        status = AvailabilityStatus.PARTIALLY_CONFIRMED
    return JourneyAvailabilityResult(status=status, segment_results=results, reasons=reasons, warnings=warnings)


class SegmentAvailabilityCache:
    def __init__(self, ttl_seconds: int = 600, error_ttl_seconds: int = 60, max_size: int = 256):
        self.ttl_seconds = ttl_seconds
        self.error_ttl_seconds = error_ttl_seconds
        self.max_size = max_size
        self._items: OrderedDict[str, tuple[datetime, SegmentAvailabilityResult]] = OrderedDict()

    def get(self, key: str) -> SegmentAvailabilityResult | None:
        item = self._items.get(key)
        if not item:
            return None
        stored_at, result = item
        ttl = self.error_ttl_seconds if result.status == AvailabilityStatus.PROVIDER_ERROR else self.ttl_seconds
        if datetime.now(timezone.utc) - stored_at > timedelta(seconds=ttl):
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return result

    def set(self, key: str, result: SegmentAvailabilityResult) -> None:
        now = datetime.now(timezone.utc)
        for item_key, (stored_at, cached) in list(self._items.items()):
            ttl = self.error_ttl_seconds if cached.status == AvailabilityStatus.PROVIDER_ERROR else self.ttl_seconds
            if now - stored_at > timedelta(seconds=ttl):
                self._items.pop(item_key, None)
        self._items[key] = (now, result)
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)
