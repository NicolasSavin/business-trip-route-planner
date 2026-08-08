from __future__ import annotations

from dataclasses import replace
from datetime import date
import logging

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.unified.registry import ProviderRegistry
from app.intelligence.stations import city_names_match


logger = logging.getLogger(__name__)


class UnifiedTransportProvider(TransportProvider):
    provider_name = "unified"

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry
        self.last_diagnostics: dict = {}

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None, **kwargs) -> list[TransportSegment]:
        merged: list[TransportSegment] = []
        seen: set[tuple[str, str, str, str, str, str, str]] = set()
        considered = [item.id for item in self.registry.list() if item.capabilities.supports_schedule]
        enabled = [item.id for item, _ in self.registry.enabled(allowed_transport, schedule_only=True)]
        called: list[str] = []
        succeeded: list[str] = []
        failed: list[str] = []
        errors: dict[str, str | dict] = {}
        segments_by_provider: dict[str, int] = {}
        input_segments: list[dict] = []
        direct_before_dedup: list[dict] = []
        direct_after_dedup: list[dict] = []
        for registration, provider in self.registry.enabled(allowed_transport, schedule_only=True):
            called.append(registration.id)
            try:
                try:
                    segments = provider.get_segments(departure_date, allowed_transport, origin=origin, destination=destination, **kwargs)
                except TypeError:
                    segments = provider.get_segments(departure_date, allowed_transport)
                self.registry.mark_result(registration.id, segments)
                succeeded.append(registration.id)
                segments_by_provider[registration.id] = len(segments)
                logger.info(
                    "route_search.provider_segments provider=%s segments=%s origin=%r destination=%r date=%s transport=%s",
                    registration.id,
                    len(segments),
                    origin,
                    destination,
                    departure_date.isoformat(),
                    [item.value for item in allowed_transport],
                )
            except Exception as exc:
                self.registry.mark_error(registration.id, exc)
                failed.append(registration.id)
                errors[registration.id] = getattr(provider, "last_error_payload", None) or (str(exc) or exc.__class__.__name__)
                segments_by_provider[registration.id] = 0
                logger.info(
                    "route_search.provider_failed provider=%s origin=%r destination=%r date=%s error=%s",
                    registration.id,
                    origin,
                    destination,
                    departure_date.isoformat(),
                    errors[registration.id],
                )
                continue
            for segment in segments:
                normalized = self._normalize(segment, registration.id)
                description = self._describe_segment(normalized)
                input_segments.append(description)
                is_direct = self._matches_endpoints(normalized, origin, destination)
                if is_direct:
                    direct_before_dedup.append(description)
                key = self._dedupe_key(normalized)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
                if is_direct:
                    direct_after_dedup.append(description)
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
            "input_segment_count": len(input_segments),
            "output_segment_count": len(merged),
            "direct_segments_before_dedup": direct_before_dedup,
            "direct_segments_after_dedup": direct_after_dedup,
            "warnings": warnings,
        }
        logger.info(
            "route_search.unified_segments input_count=%s output_count=%s input_segments=%s output_segments=%s",
            len(input_segments), len(merged), input_segments,
            [self._describe_segment(segment) for segment in merged],
        )
        logger.info(
            "route_search.unified_direct_dedup before_count=%s after_count=%s before=%s after=%s",
            len(direct_before_dedup), len(direct_after_dedup),
            direct_before_dedup, direct_after_dedup,
        )
        provider_details = {registration.id: getattr(provider, "last_diagnostics", {}) for registration, provider in self.registry.enabled(allowed_transport, schedule_only=True) if getattr(provider, "last_diagnostics", {})}
        if provider_details:
            self.last_diagnostics["provider_diagnostics"] = provider_details
        return merged

    def _normalize(self, segment: TransportSegment, provider_id: str) -> TransportSegment:
        metadata = dict(segment.metadata)
        metadata["source_provider"] = provider_id
        metadata.setdefault("original_provider", segment.provider)
        return replace(segment, provider=provider_id, metadata=metadata)

    def _dedupe_key(self, segment: TransportSegment) -> tuple[str, str, str, str, str, str, str]:
        # Equivalent records from independent schedule providers are not
        # interchangeable: their city normalization, identifiers and metadata
        # can differ, and availability enrichment relies on that provenance.
        # Only collapse repeated records emitted by the same provider.
        return (
            segment.provider.casefold(),
            segment.carrier.id.lower(),
            segment.departure_datetime.isoformat(),
            segment.origin_station.id.lower(),
            segment.destination_station.id.lower(),
            segment.vehicle_number.lower(),
            segment.transport_type.value,
        )

    def _matches_endpoints(self, segment: TransportSegment, origin: str | None, destination: str | None) -> bool:
        if not origin or not destination:
            return False
        return (
            city_names_match(segment.origin_city.name, origin)
            and city_names_match(segment.destination_city.name, destination)
        )

    def _describe_segment(self, segment: TransportSegment) -> dict[str, str]:
        return {
            "id": segment.id,
            "train_number": segment.vehicle_number,
            "provider": segment.provider,
        }
