from __future__ import annotations

from app.availability.models import AvailabilityPolicy, AvailabilityResult
from app.domain import Route


class AvailabilityValidator:
    def validate(self, route: Route, result: AvailabilityResult, policy: AvailabilityPolicy) -> tuple[str, ...]:
        warnings: list[str] = []
        if len(route.segments) != len(result.segment_results):
            warnings.append("availability result does not cover every segment")
        checked_ids = {item.segment_id for item in result.segment_results}
        for segment in route.segments:
            if segment.id not in checked_ids:
                warnings.append(f"segment {segment.id} was not checked")
        for transfer in route.transfers:
            if transfer.duration_minutes < 0:
                warnings.append("transfer has negative duration")
            if transfer.to_segment.departure_datetime < transfer.from_segment.arrival_datetime:
                warnings.append("transfer departs before previous segment arrives")
        if result.total_available_seats < policy.passengers and policy.group_must_travel_together:
            warnings.append("route does not have enough seats for the full group")
        return tuple(warnings)
