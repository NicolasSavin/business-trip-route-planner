from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.unified.models import ProviderCapabilities, ProviderHealth, ProviderRegistration


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TransportProvider] = {}
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(self, provider: TransportProvider, *, id: str, name: str, priority: int, enabled: bool = True, capabilities: ProviderCapabilities, metadata: dict | None = None) -> ProviderRegistration:
        registration = ProviderRegistration(id=id, name=name, priority=priority, enabled=enabled, capabilities=capabilities, metadata=metadata or {})
        self._providers[id] = provider
        self._registrations[id] = registration
        return registration

    def list(self) -> list[ProviderRegistration]:
        return sorted(self._registrations.values(), key=lambda item: (-item.priority, item.id))

    def health(self) -> list[ProviderRegistration]:
        for provider_id, provider in self._providers.items():
            healthcheck = getattr(provider, "healthcheck", None)
            if healthcheck is None:
                continue
            try:
                if healthcheck():
                    registration = self._registrations[provider_id]
                    self._registrations[provider_id] = registration.model_copy(update={"health": ProviderHealth.HEALTHY, "last_checked_at": datetime.now(timezone.utc), "error": None})
                else:
                    self.mark_error(provider_id, RuntimeError("Healthcheck failed"))
            except Exception as exc:
                self.mark_error(provider_id, exc)
        return self.list()

    def enabled(self, allowed_transport: Iterable[TransportType] | None = None, schedule_only: bool = False) -> list[tuple[ProviderRegistration, TransportProvider]]:
        allowed = set(allowed_transport or [])
        result = []
        for registration in self.list():
            if not registration.enabled or registration.health == ProviderHealth.OFFLINE:
                continue
            if allowed and not allowed.intersection(registration.capabilities.supported_transport):
                continue
            if schedule_only and not registration.capabilities.supports_schedule:
                continue
            result.append((registration, self._providers[registration.id]))
        return result

    def get(self, provider_id: str) -> ProviderRegistration | None:
        return self._registrations.get(provider_id)

    def enable(self, provider_id: str) -> ProviderRegistration | None:
        return self._set_enabled(provider_id, True)

    def disable(self, provider_id: str) -> ProviderRegistration | None:
        return self._set_enabled(provider_id, False)

    def _set_enabled(self, provider_id: str, enabled: bool) -> ProviderRegistration | None:
        registration = self._registrations.get(provider_id)
        if registration is None:
            return None
        if enabled:
            ensure_can_enable = getattr(self._providers[provider_id], "ensure_can_enable", None)
            if ensure_can_enable is not None:
                ensure_can_enable()
        updated = registration.model_copy(update={"enabled": enabled})
        self._registrations[provider_id] = updated
        return updated

    def mark_result(self, provider_id: str, segments: list[TransportSegment]) -> None:
        registration = self._registrations[provider_id]
        self._registrations[provider_id] = registration.model_copy(update={"health": ProviderHealth.HEALTHY, "routes_found": len(segments), "last_checked_at": datetime.now(timezone.utc), "error": None})

    def mark_error(self, provider_id: str, exc: Exception) -> None:
        registration = self._registrations[provider_id]
        status = ProviderHealth.OFFLINE if registration.routes_found == 0 else ProviderHealth.DEGRADED
        self._registrations[provider_id] = registration.model_copy(update={"health": status, "last_checked_at": datetime.now(timezone.utc), "error": str(exc) or exc.__class__.__name__})
