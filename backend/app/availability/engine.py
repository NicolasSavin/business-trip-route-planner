from __future__ import annotations

from dataclasses import replace

from app.availability.models import AvailabilityPolicy, AvailabilityResult
from app.availability.provider import AvailabilityProvider, MockAvailabilityProvider
from app.availability.validator import AvailabilityValidator
from app.domain import RouteOption


class AvailabilityEngine:
    def __init__(self, provider: AvailabilityProvider | None = None, validator: AvailabilityValidator | None = None):
        self.provider = provider or MockAvailabilityProvider()
        self.validator = validator or AvailabilityValidator()

    def check(self, option: RouteOption, policy: AvailabilityPolicy) -> AvailabilityResult:
        result = self.provider.check_route(option.route, policy)
        validation_warnings = self.validator.validate(option.route, result, policy)
        if validation_warnings:
            return replace(result, is_available=False, warnings=(*result.warnings, *validation_warnings))
        return result

    def attach(self, option: RouteOption, policy: AvailabilityPolicy) -> RouteOption:
        return replace(option, availability=self.check(option, policy))
