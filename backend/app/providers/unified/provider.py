from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.unified.registry import ProviderRegistry


class UnifiedTransportProvider(TransportProvider):
    provider_name = "unified"

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry
        self.last_diagnostics: dict = {}

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None) -> list[TransportSegment]:
        merged: list[TransportSegment] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()
        considered = [item.id for item in self.registry.list() if item.capabilities.supports_schedule]
        enabled = [item.id for item, _ in self.registry.enabled(allowed_transport, schedule_only=True)]
        called: list[str] = []
        succeeded: list[str] = []
        failed: list[str] = []
        errors: dict[str, str | dict] = {}
        segments_by_provider: dict[str, int] = {}
        for registration, provider in self.registry.enabled(allowed_transport, schedule_only=True):
            called.append(registration.id)
            try:
                try:
                    segments = provider.get_segments(departure_date, allowed_transport, origin=origin, destination=destination)
                except TypeError:
                    segments = provider.get_segments(departure_date, allowed_transport)
                self.registry.mark_result(registration.id, segments)
                succeeded.append(registration.id)
                segments_by_provider[registration.id] = len(segments)
            except Exception as exc:
                self.registry.mark_error(registration.id, exc)
                failed.append(registration.id)
                errors[registration.id] = getattr(provider, "last_error_payload", None) or (str(exc) or exc.__class__.__name__)
                segments_by_provider[registration.id] = 0
                continue
            for segment in segments:
                normalized = self._normalize(segment, registration.id)
                key = self._dedupe_key(normalized)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
        warnings = []
        real_enabled = [pid for pid in enabled if pid != "mock"]
        if not merged and not real_enabled:
            warnings.append("Не подключён ни один реальный источник расписаний")
        self.last_diagnostics = {
            "providers_considered": considered,
            "providers_enabled": enabled,
            "providers_called": called,
            "providers_succeeded": succeeded,
            "providers_failed": failed,
            "provider_errors": errors,
            "segments_by_provider": segments_by_provider,
            "warnings": warnings,
        }
        provider_details = {registration.id: getattr(provider, "last_diagnostics", {}) for registration, provider in self.registry.enabled(allowed_transport, schedule_only=True) if getattr(provider, "last_diagnostics", {})}
        if provider_details:
            self.last_diagnostics["provider_diagnostics"] = provider_details
        return merged

    def _normalize(self, segment: TransportSegment, provider_id: str) -> TransportSegment:
        metadata = dict(segment.metadata)
        metadata["source_provider"] = provider_id
        metadata.setdefault("original_provider", segment.provider)
        return replace(segment, provider=provider_id, metadata=metadata)

    def _dedupe_key(self, segment: TransportSegment) -> tuple[str, str, str, str, str, str]:
        return (
            segment.carrier.id.lower(),
            segment.departure_datetime.isoformat(),
            segment.origin_station.id.lower(),
            segment.destination_station.id.lower(),
            segment.vehicle_number.lower(),
            segment.transport_type.value,
        )
