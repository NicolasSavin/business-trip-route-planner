from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.availability.models import AvailabilityPolicy, RouteAvailability
from app.availability.provider import AvailabilityProvider, MockAvailabilityProvider
from app.availability.validator import AvailabilityValidator
from app.domain import RouteOption


class AvailabilityEngine:
    def __init__(self, provider: AvailabilityProvider | None = None, validator: AvailabilityValidator | None = None):
        self.provider = provider or MockAvailabilityProvider()
        self.validator = validator or AvailabilityValidator()

    def check(self, option: RouteOption, policy: AvailabilityPolicy) -> RouteAvailability:
        checked_at = datetime.now(timezone.utc)
        results = tuple(self.provider.check_segment(segment, policy) for segment in option.route.segments)
        known_counts = [result.available_seats for result in results if result.available_seats is not None]
        minimum = min(known_counts) if known_counts else None
        reasons = [result.reason for result in results if result.reason]
        warnings = [warning for result in results for warning in result.warnings]
        if policy.require_same_class_for_all_segments and results:
            classes = {result.transport_class for result in results}
            if len(classes) > 1:
                reasons.append("На разных сегментах доступны разные классы обслуживания")
        validation_warnings = self.validator.validate(option.route, results, policy)
        warnings.extend(validation_warnings)
        is_available = all(result.is_available for result in results) and not reasons and not validation_warnings
        return RouteAvailability(
            is_available=is_available,
            requested_passengers=policy.passengers,
            minimum_available_seats=minimum,
            checked_at=checked_at,
            segment_results=results,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    def attach(self, option: RouteOption, policy: AvailabilityPolicy) -> RouteOption:
        return replace(option, availability=self.check(option, policy))
