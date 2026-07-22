from __future__ import annotations

from app.availability.models import AvailabilityPolicy, RouteAvailability, SegmentAvailability
from app.domain import Route


class AvailabilityValidator:
    def validate(self, route: Route, results: tuple[SegmentAvailability, ...] | RouteAvailability, policy: AvailabilityPolicy) -> tuple[str, ...]:
        if isinstance(results, RouteAvailability):
            results = results.segment_results
        warnings: list[str] = []
        if len(route.segments) != len(results):
            warnings.append("availability result does not cover every segment")
        checked_ids = {item.segment_id for item in results}
        for segment in route.segments:
            if segment.id not in checked_ids:
                warnings.append(f"segment {segment.id} was not checked")
        if policy.require_group_together and any(result.available_seats is not None and result.available_seats < policy.passengers for result in results):
            warnings.append("route does not have enough seats for the full group")
        if any(result.is_stale for result in results):
            warnings.append("availability data is stale")
        return tuple(warnings)
