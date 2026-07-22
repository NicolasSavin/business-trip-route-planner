from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.availability import AvailabilityEngine, AvailabilityPolicy
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityCache, SegmentAvailabilityResult, aggregate_journey_availability
from app.availability.seats import BerthPosition, GenderRestriction, RailwayPlace, SeatAllocationService, SeatPreferences
from app.domain import RouteOption as DomainRouteOption, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.models.routes import RouteSearchRequest, SearchSummary
from app.providers.base import TransportProvider
from app.services.segment_enrichment import SegmentEnrichmentService

MAX_CANDIDATE_JOURNEYS = 80
MAX_SEGMENTS_PER_QUERY = 500
MAX_AVAILABILITY_CHECKS_PER_QUERY = 160
MAX_PROVIDER_CONCURRENCY = 4


class MultimodalJourneyPlanner:
    """Coordinates schedule search, transfer validation, segment availability, ranking and explanations."""

    def __init__(self, provider: TransportProvider, availability_engine: AvailabilityEngine | None = None, concurrency: int = MAX_PROVIDER_CONCURRENCY):
        self.provider = provider
        self.availability_engine = availability_engine or AvailabilityEngine()
        self.route_engine = RouteEngine(provider, availability_engine=self.availability_engine)
        self.seat_allocator = SeatAllocationService()
        self.enrichment = SegmentEnrichmentService()
        self.cache = SegmentAvailabilityCache()
        self.concurrency = max(1, concurrency)
        self.last_summary = SearchSummary()

    def search(self, request: RouteSearchRequest) -> tuple[list[DomainRouteOption], list[DomainRouteOption], list[DomainRouteOption], SearchSummary]:
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
        checked = asyncio.run(self._attach_journey_availability(options, request)) if options else []
        confirmed = [o for o in checked if o.availability and o.availability.status == AvailabilityStatus.CONFIRMED]
        partial = [o for o in checked if o.availability and o.availability.status == AvailabilityStatus.PARTIALLY_CONFIRMED]
        rejected = [o for o in checked if not o.availability or o.availability.status not in {AvailabilityStatus.CONFIRMED, AvailabilityStatus.PARTIALLY_CONFIRMED}]
        routes = confirmed if request.strict_availability else confirmed + partial
        summary = SearchSummary(
            segments_loaded=min(MAX_SEGMENTS_PER_QUERY, sum(len(o.route.segments) for o in options)),
            candidate_journeys=len(options),
            availability_checks=sum(len(o.route.segments) for o in checked),
            confirmed_routes=len(confirmed),
            partially_confirmed_routes=len(partial),
            rejected_routes=len(rejected),
        )
        self.last_summary = summary
        return routes, partial, rejected, summary

    async def _attach_journey_availability(self, options: list[DomainRouteOption], request: RouteSearchRequest) -> list[DomainRouteOption]:
        sem = asyncio.Semaphore(self.concurrency)
        async def one(option: DomainRouteOption) -> DomainRouteOption:
            async with sem:
                results = []
                for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]:
                    results.append(await asyncio.to_thread(self._check_segment, segment, request))
                journey = aggregate_journey_availability(tuple(results))
                warnings = (*option.warnings, *journey.warnings)
                explanation = self._explain(option, journey)
                return replace(option, availability=journey, warnings=warnings, explanation=explanation)
        return await asyncio.gather(*(one(option) for option in options))

    def _check_segment(self, segment: TransportSegment, request: RouteSearchRequest) -> SegmentAvailabilityResult:
        key = self._cache_key(segment, request)
        cached = self.cache.get(key)
        if cached:
            return cached
        try:
            policy = AvailabilityPolicy.for_group(request.passengers, preferred_classes=tuple(self._preferred_classes(request)), require_group_together=request.require_group_together, allow_split_group=request.allow_split_group)
            legacy = self.availability_engine.provider.check_segment(segment, policy)
            result = SegmentAvailabilityResult.from_legacy(legacy, provider=segment.provider)
            if segment.transport_type == TransportType.TRAIN and request.seat_preferences:
                result = self._apply_railway_preferences(segment, request, result)
            if segment.transport_type != TransportType.TRAIN:
                result = replace(result, seat_preferences_status=AvailabilityStatus.CONFIRMED if result.passengers_supported else result.status)
        except Exception as exc:
            result = SegmentAvailabilityResult(segment_id=segment.id, provider=segment.provider, status=AvailabilityStatus.PROVIDER_ERROR, reasons=(str(exc) or "Ошибка provider availability",))
        self.cache.set(key, result)
        return result

    def _apply_railway_preferences(self, segment: TransportSegment, request: RouteSearchRequest, base: SegmentAvailabilityResult) -> SegmentAvailabilityResult:
        pref = request.seat_preferences
        assert pref is not None
        # Official providers may put concrete places into metadata; when absent, create a conservative synthetic map from confirmed free seats.
        raw = segment.metadata.get("places") or []
        places = [self._place_from_dict(segment.provider, item, segment.transport_class) for item in raw]
        if not places and segment.available_seats > 0:
            places = [RailwayPlace(provider=segment.provider, place_number=str(i + 1), carriage_number="1", transport_class=segment.transport_class, berth_position=(BerthPosition.LOWER if i % 2 == 0 else BerthPosition.UPPER), compartment_number=str(i // 4 + 1)) for i in range(segment.available_seats)]
        allocation = self.seat_allocator.match(places, SeatPreferences(passengers=request.passengers, prefer_lower=pref.berth_preference == "lower_only", prefer_upper=pref.berth_preference == "upper_only", require_same_compartment=pref.require_same_compartment, require_empty_compartment=pref.require_empty_compartment, require_same_carriage=pref.require_same_carriage, require_adjacent=pref.require_adjacent, exclude_side_berths=pref.exclude_side_berths, gender=GenderRestriction(pref.gender) if pref.gender else None))
        selected = allocation.selected_places
        status = base.status if allocation.matches_preferences else (AvailabilityStatus.UNAVAILABLE if pref.strict_preferences else AvailabilityStatus.PARTIALLY_CONFIRMED)
        reasons = (*base.reasons, *allocation.reasons)
        return replace(base, status=status, seats_confirmed=allocation.matches_preferences, passengers_supported=allocation.matches_preferences, seat_preferences_status=status, selected_places=tuple(p.place_number for p in selected), selected_carriages=tuple(sorted({p.carriage_number for p in selected})), selected_compartments=tuple(sorted({p.compartment_number or "" for p in selected if p.compartment_number})), reasons=reasons)

    def _place_from_dict(self, provider: str, item: dict, fallback_class: TransportClass) -> RailwayPlace:
        return RailwayPlace(provider=provider, place_number=str(item.get("place_number") or item.get("number")), carriage_number=str(item.get("carriage_number") or item.get("carriage") or "1"), transport_class=TransportClass(item.get("transport_class") or fallback_class), berth_position=BerthPosition(item.get("berth_position") or BerthPosition.UNKNOWN), compartment_number=item.get("compartment_number"), is_side=bool(item.get("is_side", False)), is_available=bool(item.get("is_available", True)))

    def _preferred_classes(self, request: RouteSearchRequest):
        if request.seat_preferences and request.seat_preferences.preferred_classes:
            return request.seat_preferences.preferred_classes
        return request.preferred_classes

    def _cache_key(self, segment: TransportSegment, request: RouteSearchRequest) -> str:
        return "|".join([segment.provider, segment.origin_station.id, segment.destination_station.id, segment.departure_datetime.isoformat(), segment.vehicle_number, str(request.passengers), (request.seat_preferences.model_dump_json() if request.seat_preferences else "no-seat-pref")])

    def _explain(self, option: DomainRouteOption, availability) -> str:
        if availability.status == AvailabilityStatus.CONFIRMED:
            return "Все участки маршрута и требования к местам подтверждены."
        if availability.status == AvailabilityStatus.PARTIALLY_CONFIRMED:
            return "Часть участков не проверена: маршрут можно показывать только с предупреждением."
        if availability.status == AvailabilityStatus.UNAVAILABLE:
            return "На одном из обязательных участков нет подходящих мест."
        if availability.status == AvailabilityStatus.PROVIDER_ERROR:
            return "Проверка маршрута не завершена из-за ошибки provider availability."
        return "Доступность маршрута требует повторной проверки."
