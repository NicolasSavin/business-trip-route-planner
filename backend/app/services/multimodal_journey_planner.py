from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic

from app.availability import AvailabilityEngine, AvailabilityPolicy
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityCache, SegmentAvailabilityResult, aggregate_journey_availability
from app.availability.seats import BerthPosition, GenderRestriction, RailwayPlace, SeatAllocationService, SeatPreferences
from app.domain import RouteOption as DomainRouteOption, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.models.routes import RouteSearchRequest, SearchSummary
from app.providers.base import TransportProvider
from app.services.segment_enrichment import SegmentEnrichmentService
from app.providers.tutu_playwright import TutuPlaywrightAvailabilityClient

logger = logging.getLogger(__name__)

MAX_CANDIDATE_JOURNEYS = 80
MAX_SEGMENTS_PER_QUERY = 500
MAX_AVAILABILITY_CHECKS_PER_QUERY = int(os.getenv("MAX_AVAILABILITY_CHECKS_PER_QUERY", "10"))
MAX_PROVIDER_CONCURRENCY = int(os.getenv("MAX_PROVIDER_CONCURRENCY", "2"))
TUTU_MAX_JOURNEYS_TO_ENRICH = int(os.getenv("TUTU_MAX_JOURNEYS_TO_ENRICH", "3"))
TUTU_ENRICHMENT_CONCURRENCY = int(os.getenv("TUTU_ENRICHMENT_CONCURRENCY", "2"))
TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS = float(os.getenv("TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", "50"))


class MultimodalJourneyPlanner:
    """Coordinates schedule search, transfer validation, segment availability, ranking and explanations."""

    def __init__(self, provider: TransportProvider, availability_engine: AvailabilityEngine | None = None, concurrency: int = MAX_PROVIDER_CONCURRENCY):
        self.provider = provider
        self.availability_engine = availability_engine or AvailabilityEngine()
        self.route_engine = RouteEngine(provider, availability_engine=self.availability_engine)
        self.seat_allocator = SeatAllocationService()
        self.enrichment = SegmentEnrichmentService()
        self.tutu_playwright = TutuPlaywrightAvailabilityClient()
        self.cache = SegmentAvailabilityCache()
        self.concurrency = max(1, concurrency)
        self.last_summary = SearchSummary()

    async def search_async(self, request: RouteSearchRequest) -> tuple[list[DomainRouteOption], list[DomainRouteOption], list[DomainRouteOption], SearchSummary]:
        try:
            return await self._search_async_impl(request)
        except Exception:
            logger.exception("Unhandled exception inside search_async")
            raise

    async def _search_async_impl(self, request: RouteSearchRequest) -> tuple[list[DomainRouteOption], list[DomainRouteOption], list[DomainRouteOption], SearchSummary]:
        started_at = monotonic()
        options = self.route_engine.search(
            departure_date=request.departure_date,
            origin=request.origin,
            destination=request.destination,
            passengers=request.passengers,
            allowed_transport=request.allowed_transport,
            max_transfers=request.max_transfers,
            minimum_transfer_minutes=request.minimum_transfer_minutes,
            maximum_transfer_minutes=request.maximum_transfer_minutes,
            maximum_total_duration_minutes=request.maximum_total_duration_minutes,
            allow_overnight_transfer=request.allow_overnight_transfer,
            preferred_classes=self._preferred_classes(request),
            require_group_together=request.require_group_together,
            allow_split_group=request.allow_split_group,
            include_unavailable=True,
            origin_location_id=request.origin_location_id,
            origin_provider_code=request.origin_provider_code,
            origin_location_type=request.origin_location_type,
            destination_location_id=request.destination_location_id,
            destination_provider_code=request.destination_provider_code,
            destination_location_type=request.destination_location_type,
        )[:MAX_CANDIDATE_JOURNEYS]
        logger.info(
            "route_search.candidates segments_loaded=%s candidate_journeys=%s truncated_to=%s",
            self.route_engine.last_segments_count,
            len(options),
            MAX_CANDIDATE_JOURNEYS,
        )
        logger.info("route search enrichment started", extra={"candidate_journeys": len(options), "max_journeys_to_enrich": TUTU_MAX_JOURNEYS_TO_ENRICH})
        checked = await self._attach_journey_availability(options, request) if options else []
        confirmed = [o for o in checked if o.availability and o.availability.status == AvailabilityStatus.CONFIRMED]
        partial = [o for o in checked if o.availability and o.availability.status in {AvailabilityStatus.PARTIALLY_CONFIRMED, AvailabilityStatus.UNCONFIRMED}]
        rejected = [o for o in checked if not o.availability or o.availability.status not in {AvailabilityStatus.CONFIRMED, AvailabilityStatus.PARTIALLY_CONFIRMED, AvailabilityStatus.UNCONFIRMED}]
        routes = confirmed if request.strict_availability else confirmed + partial
        logger.info(
            "route_search.filters availability_checked=%s confirmed=%s partially_confirmed=%s rejected_by_confirmation=%s strict_availability=%s final_routes=%s",
            len(checked),
            len(confirmed),
            len(partial),
            len(rejected),
            request.strict_availability,
            len(routes),
        )
        provider_diagnostics = getattr(self.provider, "last_diagnostics", {}) or {}
        enrichment_errors = self._collect_enrichment_errors(checked)
        warnings = list(dict.fromkeys(provider_diagnostics.get("warnings", [])))
        if "tutu_playwright" in enrichment_errors:
            warnings.append("Расписание найдено, но проверить наличие мест через Туту не удалось.")
        if self.route_engine.last_segments_count == 0 and provider_diagnostics.get("provider_errors"):
            warnings.append("Источники расписаний не вернули сегменты; подробности в provider_errors")
        summary = SearchSummary(
            segments_loaded=min(MAX_SEGMENTS_PER_QUERY, self.route_engine.last_segments_count),
            candidate_journeys=len(options),
            availability_checks=sum(len(o.route.segments) for o in checked),
            confirmed_routes=len(confirmed),
            partially_confirmed_routes=len(partial),
            rejected_routes=len(rejected),
            providers_considered=provider_diagnostics.get("providers_considered", []),
            providers_enabled=provider_diagnostics.get("providers_enabled", []),
            providers_called=provider_diagnostics.get("providers_called", []),
            providers_succeeded=provider_diagnostics.get("providers_succeeded", []),
            providers_failed=provider_diagnostics.get("providers_failed", []),
            provider_errors={**provider_diagnostics.get("provider_errors", {}), **enrichment_errors},
            segments_by_provider=provider_diagnostics.get("segments_by_provider", {}),
            provider_diagnostics=provider_diagnostics.get("provider_diagnostics", {}),
            warnings=list(dict.fromkeys(warnings)),
        )
        if enrichment_errors:
            logger.info("route_search.provider error added to SearchSummary", extra={"providers": list(enrichment_errors)})
        logger.info("route search response returned", extra={"duration_ms": int((monotonic() - started_at) * 1000), "routes": len(routes), "partial": len(partial), "rejected": len(rejected)})
        self.last_summary = summary
        return routes, partial, rejected, summary

    def search(self, request: RouteSearchRequest) -> tuple[list[DomainRouteOption], list[DomainRouteOption], list[DomainRouteOption], SearchSummary]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.search_async(request))
        raise RuntimeError("Use search_async() inside a running event loop")

    async def _attach_journey_availability(self, options: list[DomainRouteOption], request: RouteSearchRequest) -> list[DomainRouteOption]:
        enrich_options = options[:TUTU_MAX_JOURNEYS_TO_ENRICH]
        local_cache: dict[str, SegmentAvailabilityResult] = {}
        unique_segments: dict[str, TransportSegment] = {}
        for option in enrich_options:
            for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]:
                if segment.transport_type == TransportType.TRAIN:
                    key = self._cache_key(segment, request)
                    unique_segments.setdefault(key, segment)
        logger.info("unique segments count", extra={"unique_segments_count": len(unique_segments)})

        # Compute cheap/local availability for every segment first. Tutu results below may override it.
        for option in options:
            for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]:
                key = self._cache_key(segment, request)
                if key not in local_cache:
                    local_cache[key] = self._check_segment_base(segment, request)

        tutu_available = self.tutu_playwright.available() if hasattr(self.tutu_playwright, "available") else True
        if unique_segments and tutu_available:
            sem = asyncio.Semaphore(max(1, TUTU_ENRICHMENT_CONCURRENCY))

            async def enrich_one(key: str, segment: TransportSegment) -> tuple[str, SegmentAvailabilityResult | None]:
                async with sem:
                    logger.info("enrichment task started", extra={"segment_id": segment.id})
                    try:
                        result = await self.tutu_playwright.check_segment(segment, request)
                        logger.info("enrichment task completed", extra={"segment_id": segment.id, "status": getattr(getattr(result, "status", None), "value", None)})
                        return key, result
                    except asyncio.CancelledError:
                        logger.info("enrichment timeout", extra={"segment_id": segment.id})
                        raise

            tasks = [asyncio.create_task(enrich_one(key, segment)) for key, segment in unique_segments.items()]
            done, pending = await asyncio.wait(tasks, timeout=TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS)
            for task in done:
                try:
                    key, result = task.result()
                except Exception as exc:
                    logger.warning("tutu_playwright.enrichment exception captured", extra={"error_type": type(exc).__name__})
                    continue
                if result is not None:
                    local_cache[key] = result
            if pending:
                logger.warning("enrichment budget exhausted", extra={"timeout_seconds": TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS, "pending_tasks": len(pending)})
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.info("tasks cancelled", extra={"cancelled_tasks": len(pending)})
                for key in unique_segments:
                    if key not in {task.result()[0] for task in done if not task.cancelled() and task.exception() is None}:
                        local_cache[key] = self._tutu_timeout_result(unique_segments[key])

        enriched: list[DomainRouteOption] = []
        for option in options:
            results = [local_cache[self._cache_key(segment, request)] for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]]
            journey = aggregate_journey_availability(tuple(results))
            warnings = tuple(dict.fromkeys(w for w in (*option.warnings, *journey.warnings) if w))
            explanation = self._explain(option, journey)
            enriched.append(replace(option, availability=journey, warnings=warnings, explanation=explanation))
        return enriched

    def _collect_enrichment_errors(self, options: list[DomainRouteOption]) -> dict[str, dict]:
        errors: list[dict] = []
        for option in options:
            if not option.availability:
                continue
            for result in option.availability.segment_results:
                error = result.metadata.get("provider_error") if result.metadata else None
                if isinstance(error, dict):
                    errors.append(error)
        if not errors:
            return {}
        deduped = []
        seen = set()
        for error in errors:
            details = error.get("details") if isinstance(error.get("details"), dict) else {}
            key = (details.get("segment_id"), error.get("code"), error.get("error_type"), error.get("message"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(error)
        logger.info("tutu_playwright.enrichment provider_error", extra={"errors_count": len(errors), "deduped_errors_count": len(deduped)})
        first = deduped[0]
        public_message = self._public_provider_error_message(first)
        return {"tutu_playwright": {"code": "availability_enrichment_failed", "message": public_message, "error_type": first.get("error_type", "ProviderError"), "errors": deduped[:10]}}

    def _public_provider_error_message(self, error: dict) -> str:
        message = str(error.get("message") or "")
        error_type = str(error.get("error_type") or "")
        if "ReadTimeout" in message or "ReadTimeout" in error_type or "timeout" in message.lower() or "timeout" in error_type.lower():
            return "Сервис проверки мест не ответил вовремя. Расписание доступно, наличие мест не подтверждено."
        return message or "Сервис проверки мест временно недоступен. Расписание доступно, наличие мест не подтверждено."

    def _check_segment_base(self, segment: TransportSegment, request: RouteSearchRequest) -> SegmentAvailabilityResult:
        key = self._cache_key(segment, request)
        cached = self.cache.get(key)
        if cached:
            return cached
        try:
            policy = AvailabilityPolicy.for_group(request.passengers, preferred_classes=tuple(self._preferred_classes(request)), require_group_together=request.require_group_together, allow_split_group=request.allow_split_group)
            legacy = self.availability_engine.provider.check_segment(segment, policy)
            result = SegmentAvailabilityResult.from_legacy(legacy, provider=segment.provider)
            if segment.metadata.get("availability_unknown") or "Источник расписаний не подтверждает наличие и расположение мест" in result.warnings:
                result = replace(result, status=AvailabilityStatus.UNCONFIRMED, seats_confirmed=False, passengers_supported=False, available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN, reasons=(), warnings=(*result.warnings, "Нижние места и одно купе требуют дополнительной проверки" if request.seat_preferences else ""))
                result = replace(result, warnings=tuple(dict.fromkeys(w for w in result.warnings if w)))
            if segment.available_seats == 999:
                result = replace(result, status=AvailabilityStatus.UNCONFIRMED, seats_confirmed=False, passengers_supported=False, available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN, warnings=(*result.warnings, "Yandex returned 999 seats placeholder; real availability is unconfirmed"))
            if segment.transport_type == TransportType.TRAIN and request.seat_preferences:
                result = self._apply_railway_preferences(segment, request, result)
            if segment.transport_type != TransportType.TRAIN:
                result = replace(result, seat_preferences_status=AvailabilityStatus.CONFIRMED if result.passengers_supported else result.status)
        except Exception as exc:
            result = SegmentAvailabilityResult(segment_id=segment.id, provider=segment.provider, status=AvailabilityStatus.PROVIDER_ERROR, reasons=(str(exc) or "Ошибка provider availability",))
        self.cache.set(key, result)
        return result

    def _tutu_timeout_result(self, segment: TransportSegment) -> SegmentAvailabilityResult:
        return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, seats_confirmed=False, passengers_supported=False, available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN, reasons=("Расписание найдено, проверка мест через Туту не выполнена",), warnings=("Расписание найдено, проверка мест через Туту не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": "Tutu enrichment total timeout exceeded", "error_type": "TimeoutError", "details": {"segment_id": segment.id}}})

    def _apply_railway_preferences(self, segment: TransportSegment, request: RouteSearchRequest, base: SegmentAvailabilityResult) -> SegmentAvailabilityResult:
        pref = request.seat_preferences
        assert pref is not None
        raw = segment.metadata.get("places") or []
        places = [self._place_from_dict(segment.provider, item, segment.transport_class) for item in raw]
        if not places and base.status in {AvailabilityStatus.PARTIALLY_CONFIRMED, AvailabilityStatus.UNCONFIRMED}:
            return replace(base, seat_preferences_status=AvailabilityStatus.UNKNOWN)
        if not places and segment.available_seats and segment.available_seats > 0:
            places = [RailwayPlace(provider=segment.provider, place_number=str(i + 1), carriage_number="1", transport_class=segment.transport_class or TransportClass.SEATED, berth_position=(BerthPosition.LOWER if i % 2 == 0 else BerthPosition.UPPER), compartment_number=str(i // 4 + 1)) for i in range(segment.available_seats)]
        allocation = self.seat_allocator.match(places, SeatPreferences(passengers=request.passengers, prefer_lower=pref.berth_preference == "lower_only", prefer_upper=pref.berth_preference == "upper_only", require_same_compartment=pref.require_same_compartment, require_empty_compartment=pref.require_empty_compartment, require_same_carriage=pref.require_same_carriage, require_adjacent=pref.require_adjacent, exclude_side_berths=pref.exclude_side_berths, gender=GenderRestriction(pref.gender) if pref.gender else None))
        selected = allocation.selected_places
        status = base.status if allocation.matches_preferences else (AvailabilityStatus.UNAVAILABLE if pref.strict_preferences else AvailabilityStatus.PARTIALLY_CONFIRMED)
        reasons = (*base.reasons, *allocation.reasons)
        return replace(base, status=status, seats_confirmed=allocation.matches_preferences, passengers_supported=allocation.matches_preferences, seat_preferences_status=status, selected_places=tuple(p.place_number for p in selected), selected_carriages=tuple(sorted({p.carriage_number for p in selected})), selected_compartments=tuple(sorted({p.compartment_number or "" for p in selected if p.compartment_number})), reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)))

    def _place_from_dict(self, provider: str, item: dict, fallback_class: TransportClass | None) -> RailwayPlace:
        return RailwayPlace(provider=provider, place_number=str(item.get("place_number") or item.get("number")), carriage_number=str(item.get("carriage_number") or item.get("carriage") or "1"), transport_class=TransportClass(item.get("transport_class") or fallback_class or TransportClass.SEATED), berth_position=BerthPosition(item.get("berth_position") or BerthPosition.UNKNOWN), compartment_number=item.get("compartment_number"), is_side=bool(item.get("is_side", False)), is_available=bool(item.get("is_available", True)))

    def _preferred_classes(self, request: RouteSearchRequest):
        if request.seat_preferences and request.seat_preferences.preferred_classes:
            return request.seat_preferences.preferred_classes
        return request.preferred_classes

    def _cache_key(self, segment: TransportSegment, request: RouteSearchRequest) -> str:
        return "|".join([segment.provider, segment.origin_station.id, segment.destination_station.id, segment.departure_datetime.isoformat(), segment.vehicle_number, str(request.passengers), (request.seat_preferences.model_dump_json() if request.seat_preferences else "no-seat-pref")])

    def _explain(self, option: DomainRouteOption, availability) -> str:
        if availability.status == AvailabilityStatus.CONFIRMED:
            return "Все участки маршрута и требования к местам подтверждены."
        if availability.status in {AvailabilityStatus.PARTIALLY_CONFIRMED, AvailabilityStatus.UNCONFIRMED}:
            return "Расписание найдено, наличие мест не подтверждено."
        if availability.status == AvailabilityStatus.UNAVAILABLE:
            return "На одном из обязательных участков нет подходящих мест."
        if availability.status == AvailabilityStatus.PROVIDER_ERROR:
            return "Проверка маршрута не завершена из-за ошибки provider availability."
        return "Доступность маршрута требует повторной проверки."
