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

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None) -> list[TransportSegment]:
        merged: list[TransportSegment] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()
        for registration, provider in self.registry.enabled(allowed_transport):
            try:
                try:
                    segments = provider.get_segments(departure_date, allowed_transport, origin=origin, destination=destination)
                except TypeError:
                    segments = provider.get_segments(departure_date, allowed_transport)
                self.registry.mark_result(registration.id, segments)
            except Exception as exc:
                self.registry.mark_error(registration.id, exc)
                continue
            for segment in segments:
                normalized = self._normalize(segment, registration.id)
                key = self._dedupe_key(normalized)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
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
