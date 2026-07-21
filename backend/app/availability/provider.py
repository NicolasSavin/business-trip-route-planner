from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.availability.models import AvailabilityPolicy, AvailabilityResult, SegmentAvailability
from app.domain import Route, TransportSegment


class AvailabilityProvider(Protocol):
    def check_segment(self, segment: TransportSegment, policy: AvailabilityPolicy) -> SegmentAvailability: ...

    def check_route(self, route: Route, policy: AvailabilityPolicy) -> AvailabilityResult: ...


class MockAvailabilityProvider:
    source = "mock-availability"

    def __init__(self, overrides: dict[str, int] | None = None):
        self.overrides = overrides or {}

    def check_segment(self, segment: TransportSegment, policy: AvailabilityPolicy) -> SegmentAvailability:
        checked_at = datetime.now(timezone.utc)
        seats = self.overrides.get(segment.id, segment.available_seats)
        warnings: list[str] = []
        if seats <= 0:
            warnings.append("no seats")
        elif seats < policy.passengers:
            warnings.append("not enough seats for the full group")
        if not policy.accepts_class(segment.transport_class):
            warnings.append("transport class is not allowed by policy")
        available = policy.has_enough_seats(seats) and policy.accepts_class(segment.transport_class)
        return SegmentAvailability(segment.id, available, seats, segment.transport_class, checked_at, self.source, tuple(warnings))

    def check_route(self, route: Route, policy: AvailabilityPolicy) -> AvailabilityResult:
        checked_at = datetime.now(timezone.utc)
        results = tuple(self.check_segment(segment, policy) for segment in route.segments)
        warnings = tuple(warning for result in results for warning in result.warnings)
        total = min((result.available_seats for result in results), default=0)
        return AvailabilityResult(all(result.is_available for result in results), results, checked_at, self.source, total, warnings)
