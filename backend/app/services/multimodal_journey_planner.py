from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic

from app.availability import AvailabilityEngine, AvailabilityPolicy
from app.availability.journey import AvailabilityStatus, RequirementCheck, RequirementStatus, SegmentAvailabilityCache, SegmentAvailabilityResult, aggregate_journey_availability
from app.availability.seats import BerthPosition, GenderRestriction, RailwayPlace, SeatAllocationService, SeatPreferences
from app.domain import RouteOption as DomainRouteOption, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.intelligence.stations import city_names_match
from app.intelligence.explanations import ExplanationService
from app.models.routes import RouteSearchRequest, SearchSummary
from app.providers.base import TransportProvider
from app.services.segment_enrichment import SegmentEnrichmentService
from app.scoring import ScoringService
from app.providers.tutu_playwright import TutuPlaywrightAvailabilityClient
from app.providers.rzd_availability import RZDAvailabilityProvider

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
        self.rzd_availability = RZDAvailabilityProvider()
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
        segments = self._load_provider_segments(request)
        direct_matches = [
            segment for segment in segments
            if self._segment_matches_request(segment, request)
        ]
        provider_counts: dict[str, int] = {}
        for segment in segments:
            provider_counts[segment.provider] = provider_counts.get(segment.provider, 0) + 1
        logger.info(
            "route_search.planner_route_engine_input total_segment_count=%s "
            "direct_match_count=%s origin=%r destination=%r provider_counts=%s direct_matches=%s",
            len(segments),
            len(direct_matches),
            request.origin,
            request.destination,
            provider_counts,
            [{"id": segment.id, "train_number": segment.vehicle_number} for segment in direct_matches],
        )
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
            # Pass the complete deduplicated provider output, not a graph-derived
            # subset. The same collection supplies direct and transfer searches.
            segments=segments,
        )[:MAX_CANDIDATE_JOURNEYS]
        logger.info(
            "route_search.candidates segments_loaded=%s candidate_journeys=%s truncated_to=%s",
            self.route_engine.last_segments_count,
            len(options),
            MAX_CANDIDATE_JOURNEYS,
        )
        logger.info("route search enrichment started", extra={"candidate_journeys": len(options), "max_journeys_to_enrich": TUTU_MAX_JOURNEYS_TO_ENRICH})
        checked = await self._attach_journey_availability(options, request) if options else []
        checked = self._rank_after_availability(checked)
        confirmed = [o for o in checked if o.availability and o.availability.status == AvailabilityStatus.CONFIRMED]
        # In a non-strict search, enrichment failures must not erase a valid
        # schedule. UNAVAILABLE remains excluded because providers may emit it
        # only from conclusive, passenger-specific inventory data.
        visible_statuses = {
            AvailabilityStatus.CONFIRMED,
            AvailabilityStatus.PARTIALLY_CONFIRMED,
            AvailabilityStatus.UNCONFIRMED,
            AvailabilityStatus.UNKNOWN,
            AvailabilityStatus.PROVIDER_ERROR,
            AvailabilityStatus.STALE,
        }
        partial = [o for o in checked if o.availability and o.availability.status in visible_statuses - {AvailabilityStatus.CONFIRMED}]
        rejected = [o for o in checked if not o.availability or o.availability.status not in visible_statuses]
        # The public response keeps confirmed and partial routes in disjoint
        # collections. Presentation policy belongs to the client and must not
        # make a partial route appear in both response arrays.
        routes = confirmed
        direct_before = [o for o in checked if o.route.transfers_count == 0]
        direct_after = [o for o in routes if o.route.transfers_count == 0]
        direct_availability = [
            {
                "segment_ids": [segment.id for segment in option.route.segments],
                "status": option.availability.status.value if option.availability else "unknown",
            }
            for option in direct_before
        ]
        logger.info(
            "route_search.filters availability_checked=%s confirmed=%s partially_confirmed=%s rejected_by_confirmation=%s strict_availability=%s final_routes=%s",
            len(checked),
            len(confirmed),
            len(partial),
            len(rejected),
            request.strict_availability,
            len(routes),
        )
        logger.info(
            "route_search.direct_availability_filter direct_before=%s direct_after=%s "
            "include_unavailable=%s direct_availability=%s",
            len(direct_before),
            len(direct_after),
            not request.strict_availability,
            direct_availability,
        )
        provider_diagnostics = getattr(self.provider, "last_diagnostics", {}) or {}
        enrichment_errors = self._collect_enrichment_errors(checked)
        warnings = list(dict.fromkeys(provider_diagnostics.get("warnings", [])))
        if "tutu_playwright" in enrichment_errors:
            warnings.append("Расписание найдено, но проверить наличие мест через Туту не удалось.")
        if "rzd" in enrichment_errors:
            warnings.append("Расписание найдено, но проверить наличие мест через РЖД не удалось.")
        if self.route_engine.last_segments_count == 0 and provider_diagnostics.get("provider_errors"):
            warnings.append("Источники расписаний не вернули сегменты; подробности в provider_errors")
        candidate_diagnostics = dict(self.route_engine.last_diagnostics)
        availability_rejections = []
        for option in checked:
            if option.route.transfers_count != 0 or not option.availability:
                continue
            hidden = option.availability.status not in visible_statuses or (request.strict_availability and option.availability.status != AvailabilityStatus.CONFIRMED)
            if hidden:
                prefix = "confirmed_only" if request.strict_availability and option.availability.status != AvailabilityStatus.CONFIRMED else "availability"
                availability_rejections.append({
                    "candidate": self.route_engine._describe_segment(option.route.segments[0]),
                    "reasons": [f"{prefix}:{option.availability.status.value}", *option.availability.reasons],
                    "stage": "availability_filter",
                })
        summary = SearchSummary(
            segments_loaded=min(MAX_SEGMENTS_PER_QUERY, self.route_engine.last_segments_count),
            candidate_journeys=len(options),
            availability_checks=sum(len(o.route.segments) for o in checked),
            skipped_due_to_budget=getattr(self, "_skipped_due_to_budget", 0),
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
            raw_direct_candidates=candidate_diagnostics.get("raw_direct_candidates", []),
            filtered_direct_candidates=[self.route_engine._describe_segment(o.route.segments[0]) for o in routes if o.route.transfers_count == 0],
            rejection_reasons=[*candidate_diagnostics.get("rejection_reasons", []), *availability_rejections],
            ranked_candidates=[self.route_engine._describe_route(o.route, o.rank) for o in checked],
            resolved_origin_cities=candidate_diagnostics.get("resolved_origin_cities", []),
            resolved_destination_cities=candidate_diagnostics.get("resolved_destination_cities", []),
            direct_match_decisions=candidate_diagnostics.get("direct_match_decisions", []),
            yandex_requests_made=self._yandex_diagnostic(provider_diagnostics, "yandex_requests_made", 0),
            yandex_direct_requests_made=self._yandex_diagnostic(provider_diagnostics, "yandex_direct_requests_made", 0),
            yandex_transfer_requests_made=self._yandex_diagnostic(provider_diagnostics, "yandex_transfer_requests_made", 0),
            yandex_candidate_origin_codes=self._yandex_diagnostic(provider_diagnostics, "yandex_candidate_origin_codes", []),
            yandex_candidate_destination_codes=self._yandex_diagnostic(provider_diagnostics, "yandex_candidate_destination_codes", []),
            yandex_fanout_limited=self._yandex_diagnostic(provider_diagnostics, "yandex_fanout_limited", False),
            yandex_search_deadline_exceeded=self._yandex_diagnostic(provider_diagnostics, "yandex_search_deadline_exceeded", False),
        )
        if enrichment_errors:
            logger.info("route_search.provider error added to SearchSummary", extra={"providers": list(enrichment_errors)})
        logger.info("route search response returned", extra={"duration_ms": int((monotonic() - started_at) * 1000), "routes": len(routes), "partial": len(partial), "rejected": len(rejected)})
        self.last_summary = summary
        return routes, partial, rejected, summary

    @staticmethod
    def _yandex_diagnostic(provider_diagnostics: dict, key: str, default):
        details = provider_diagnostics.get("provider_diagnostics", {}).get("yandex_rasp", {})
        return details.get(key, default)

    def _load_provider_segments(self, request: RouteSearchRequest) -> list[TransportSegment]:
        try:
            return self.provider.get_segments(
                request.departure_date,
                request.allowed_transport,
                origin=request.origin,
                destination=request.destination,
                origin_provider_code=request.origin_provider_code,
                destination_provider_code=request.destination_provider_code,
                origin_location_id=request.origin_location_id,
                destination_location_id=request.destination_location_id,
                origin_location_type=request.origin_location_type,
                destination_location_type=request.destination_location_type,
                max_transfers=request.max_transfers,
            )
        except TypeError:
            return self.provider.get_segments(request.departure_date, request.allowed_transport)

    def _segment_matches_request(self, segment: TransportSegment, request: RouteSearchRequest) -> bool:
        return (
            city_names_match(segment.origin_city.name, request.origin)
            and city_names_match(segment.destination_city.name, request.destination)
        )

    def _rank_after_availability(self, options: list[DomainRouteOption]) -> list[DomainRouteOption]:
        """Recompute every ranking derivative from the enriched inventory."""
        confirmation_order = {AvailabilityStatus.CONFIRMED: 0, AvailabilityStatus.PARTIALLY_CONFIRMED: 1, AvailabilityStatus.UNCONFIRMED: 2, AvailabilityStatus.UNKNOWN: 2}

        scorer = ScoringService()
        refreshed = []
        for option in options:
            results = {result.segment_id: result for result in option.availability.segment_results} if option.availability else {}
            segments = tuple(
                replace(segment, available_seats=results[segment.id].available_places_count)
                if segment.id in results and results[segment.id].available_places_count is not None
                else segment
                for segment in option.route.segments
            )
            route = replace(option.route, segments=segments)
            refreshed.append(replace(option, route=route, score=scorer.score(route)))

        def key(option):
            prices = [segment.price for segment in option.route.segments]
            total_price = sum(prices) if prices and all(price is not None for price in prices) else float("inf")
            status = getattr(option.availability, "status", AvailabilityStatus.UNKNOWN)
            return (option.route.transfers_count, option.route.total_duration_minutes, confirmation_order.get(status, 3), total_price, option.score)

        ranked = sorted(refreshed, key=key)
        explanations = ExplanationService()
        best_score = ranked[0].score if ranked else None
        output = []
        for index, option in enumerate(ranked, start=1):
            _, route_warnings, advantages = explanations.explain(option.route, option.score, index, best_score)
            explanation = self._explain(option, option.availability) if option.availability else "Маршрут оценён по прозрачным правилам."
            availability_warnings = option.availability.warnings if option.availability else ()
            output.append(replace(option, rank=index, explanation=explanation,
                                  warnings=tuple(dict.fromkeys((*route_warnings, *availability_warnings))),
                                  advantages=advantages))
        return output

    def search(self, request: RouteSearchRequest) -> tuple[list[DomainRouteOption], list[DomainRouteOption], list[DomainRouteOption], SearchSummary]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.search_async(request))
        raise RuntimeError("Use search_async() inside a running event loop")

    async def _attach_journey_availability(self, options: list[DomainRouteOption], request: RouteSearchRequest) -> list[DomainRouteOption]:
        # The check budget is explicit and applies to unique rail segments. Direct
        # routes are considered first, followed by the already ranked transfers.
        enrich_options = sorted(options, key=lambda option: (option.route.transfers_count, option.rank or 10_000))
        local_cache: dict[str, SegmentAvailabilityResult] = {}
        unique_segments: dict[str, TransportSegment] = {}
        for option in enrich_options:
            for segment in option.route.segments:
                if segment.transport_type == TransportType.TRAIN:
                    key = self._cache_key(segment, request)
                    if key not in unique_segments and len(unique_segments) < MAX_AVAILABILITY_CHECKS_PER_QUERY:
                        unique_segments[key] = segment
        logger.info("unique segments count", extra={"unique_segments_count": len(unique_segments)})

        # Compute cheap/local availability for every segment first. Tutu results below may override it.
        for option in options:
            for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]:
                key = self._cache_key(segment, request)
                if key not in local_cache:
                    local_cache[key] = self._check_segment_base(segment, request)

        availability_provider = self.rzd_availability if self.rzd_availability.available() else self.tutu_playwright
        provider_available = availability_provider.available() if hasattr(availability_provider, "available") else True
        all_rail_keys = {
            self._cache_key(segment, request)
            for option in options for segment in option.route.segments
            if segment.transport_type == TransportType.TRAIN
        }
        skipped_keys = all_rail_keys - unique_segments.keys() if provider_available else set()
        self._skipped_due_to_budget = len(skipped_keys)
        for key in skipped_keys:
            base = local_cache[key]
            local_cache[key] = replace(
                base, status=AvailabilityStatus.UNCONFIRMED, seats_confirmed=False,
                passengers_supported=False, seat_preferences_status=AvailabilityStatus.UNKNOWN,
                warnings=tuple(dict.fromkeys((*base.warnings, "Проверка мест пропущена из-за лимита запроса"))),
                metadata={**base.metadata, "skipped_due_to_budget": True},
            )
        if unique_segments and provider_available:
            sem = asyncio.Semaphore(max(1, TUTU_ENRICHMENT_CONCURRENCY))

            async def enrich_one(key: str, segment: TransportSegment) -> tuple[str, SegmentAvailabilityResult | None]:
                async with sem:
                    logger.info("enrichment task started", extra={"segment_id": segment.id})
                    try:
                        result = await availability_provider.check_segment(segment, request)
                        if (
                            availability_provider is self.rzd_availability
                            and result is not None
                            and result.status in {AvailabilityStatus.UNKNOWN, AvailabilityStatus.UNCONFIRMED, AvailabilityStatus.PROVIDER_ERROR}
                            and self.tutu_playwright.available()
                        ):
                            fallback_started = monotonic()
                            log_context = {
                                "segment_id": segment.id, "primary_provider": "rzd",
                                "primary_status": result.status.value,
                                "fallback_provider": "tutu_playwright",
                            }
                            logger.info("availability_fallback.started", extra=log_context)
                            try:
                                fallback = await self.tutu_playwright.check_segment(segment, request)
                                elapsed_ms = round((monotonic() - fallback_started) * 1000, 2)
                                fallback_status = getattr(getattr(fallback, "status", None), "value", None)
                                logger.info("availability_fallback.completed", extra={**log_context, "fallback_status": fallback_status, "elapsed_ms": elapsed_ms})
                                if fallback and fallback.status in {AvailabilityStatus.CONFIRMED, AvailabilityStatus.PARTIALLY_CONFIRMED}:
                                    result = fallback
                                elif fallback:
                                    # Preserve diagnostics from both attempts in the frontend-safe contract.
                                    result = replace(result,
                                        reasons=tuple(dict.fromkeys((*result.reasons, *fallback.reasons))),
                                        warnings=tuple(dict.fromkeys((*result.warnings, *fallback.warnings))),
                                        metadata={**result.metadata, "fallback_provider_error": fallback.metadata.get("provider_error"), "fallback_status": fallback.status.value},
                                    )
                            except Exception as exc:
                                logger.warning("availability_fallback.failed", extra={**log_context, "fallback_status": "error", "elapsed_ms": round((monotonic() - fallback_started) * 1000, 2), "error_type": type(exc).__name__})
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
                    local_cache[key] = self._apply_railway_preferences(unique_segments[key], request, result) if request.seat_preferences else result
            if pending:
                logger.warning("enrichment budget exhausted", extra={"timeout_seconds": TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS, "pending_tasks": len(pending)})
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.info("tasks cancelled", extra={"cancelled_tasks": len(pending)})
                for key in unique_segments:
                    if key not in {task.result()[0] for task in done if not task.cancelled() and task.exception() is None}:
                        provider_name = "rzd" if availability_provider is self.rzd_availability else "tutu_playwright"
                        local_cache[key] = self._provider_timeout_result(unique_segments[key], provider_name)

        enriched: list[DomainRouteOption] = []
        for option in options:
            results = [local_cache[self._cache_key(segment, request)] for segment in option.route.segments[:MAX_AVAILABILITY_CHECKS_PER_QUERY]]
            journey = aggregate_journey_availability(tuple(results))
            warnings = tuple(dict.fromkeys(w for w in (*option.warnings, *journey.warnings) if w))
            explanation = self._explain(option, journey)
            enriched.append(replace(option, availability=journey, warnings=warnings, explanation=explanation))
        return enriched

    def _collect_enrichment_errors(self, options: list[DomainRouteOption]) -> dict[str, dict]:
        errors_by_provider: dict[str, list[dict]] = {}
        for option in options:
            if not option.availability:
                continue
            for result in option.availability.segment_results:
                error = result.metadata.get("provider_error") if result.metadata else None
                if isinstance(error, dict):
                    errors_by_provider.setdefault(result.provider, []).append(error)
        if not errors_by_provider:
            return {}
        output = {}
        for provider, errors in errors_by_provider.items():
            deduped, seen = [], set()
            for error in errors:
                details = error.get("details") if isinstance(error.get("details"), dict) else {}
                key = (details.get("segment_id"), error.get("code"), error.get("error_type"), error.get("message"))
                if key not in seen:
                    seen.add(key)
                    deduped.append(error)
            first = deduped[0]
            output[provider] = {"code": "availability_enrichment_failed", "message": self._public_provider_error_message(first), "error_type": first.get("error_type", "ProviderError"), "errors": deduped[:10]}
            logger.info("availability.enrichment provider_error", extra={"provider": provider, "errors_count": len(errors), "deduped_errors_count": len(deduped)})
        return output

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
        return self._provider_timeout_result(segment, "tutu_playwright")

    def _provider_timeout_result(self, segment: TransportSegment, provider: str) -> SegmentAvailabilityResult:
        label = "РЖД" if provider == "rzd" else "Туту"
        return SegmentAvailabilityResult(segment_id=segment.id, provider=provider, status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, seats_confirmed=False, passengers_supported=False, available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN, reasons=(f"Расписание найдено, проверка мест через {label} не выполнена",), warnings=(f"Расписание найдено, проверка мест через {label} не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": f"{provider} enrichment total timeout exceeded", "error_type": "TimeoutError", "details": {"segment_id": segment.id}}})

    def _apply_railway_preferences(self, segment: TransportSegment, request: RouteSearchRequest, base: SegmentAvailabilityResult) -> SegmentAvailabilityResult:
        """Evaluate each requested placement rule from normalized RZD places.

        The two checks are intentionally independent: explicit lower berths can
        be confirmed even when RZD omitted their physical compartment number.
        """
        pref = request.seat_preferences
        assert pref is not None
        raw = base.metadata.get("places") or []
        places = [self._place_from_dict(base.provider, item, segment.transport_class) for item in raw]
        train_name = f"{segment.vehicle_number} {segment.metadata.get('train_title', '')}".lower()
        seated = segment.transport_class in {TransportClass.SEATED, TransportClass.EXPRESS} or "сапсан" in train_name
        if seated and (pref.berth_preference == "lower_only" or pref.require_same_compartment):
            lower = RequirementCheck(RequirementStatus.NOT_APPLICABLE, "В поезде только сидячие места — требование нижних мест неприменимо") if pref.berth_preference == "lower_only" else None
            compartment = RequirementCheck(RequirementStatus.NOT_APPLICABLE, "Неприменимо: сидячая компоновка не имеет обычных купе") if pref.require_same_compartment else None
            rejected_status = AvailabilityStatus.UNAVAILABLE if pref.strict_preferences else AvailabilityStatus.PARTIALLY_CONFIRMED
            return replace(base, status=rejected_status, seats_confirmed=False, passengers_supported=False,
                seat_preferences_status=rejected_status, lower_berths_check=lower,
                same_compartment_check=compartment, reasons=tuple(dict.fromkeys((*base.reasons, "Для сидячего поезда требования к спальным местам неприменимы"))),
                metadata={**base.metadata, "lower_berths_confirmed": False, "same_compartment_confirmed": False})

        # Only the RZD mapper may set this marker after reading concrete response
        # fields. Arbitrary schedule metadata and other providers are never
        # promoted to explicit placement evidence here.
        trusted_explicit = [p for p in places if base.provider == "rzd" and p.explicitly_confirmed and p.place_number and p.carriage_number]
        explicit = trusted_explicit
        if pref.preferred_classes:
            explicit = [p for p in explicit if p.transport_class in pref.preferred_classes]
        available_explicit = [p for p in explicit if p.is_available]
        lower_places = [p for p in available_explicit if p.berth_position == BerthPosition.LOWER]
        required = request.passengers

        lower_check = None
        source_label = "РЖД" if base.provider == "rzd" else "Источник мест"
        if pref.berth_preference == "lower_only":
            if len(lower_places) >= required:
                lower_check = RequirementCheck(RequirementStatus.CONFIRMED, "Подтверждено: найдены отдельные нижние места")
            elif trusted_explicit:
                lower_check = RequirementCheck(RequirementStatus.REJECTED, "Не подходит: недостаточно явно подтверждённых нижних мест")
            else:
                lower_check = RequirementCheck(RequirementStatus.UNKNOWN, f"Не подтверждено: {source_label} не передал явные данные о местах")

        compartment_check = None
        selected_group: list[RailwayPlace] = []
        if pref.require_same_compartment:
            candidates = lower_places if pref.berth_preference == "lower_only" else available_explicit
            groups: dict[tuple[str, str], list[RailwayPlace]] = {}
            for place in candidates:
                if place.compartment_number:
                    groups.setdefault((place.carriage_number, place.compartment_number), []).append(place)
            selected_group = next((group for group in groups.values() if len(group) >= required), [])
            if selected_group:
                compartment_check = RequirementCheck(RequirementStatus.CONFIRMED, "Подтверждено: сотрудники размещаются в одном вагоне и физическом купе")
            elif any(not place.compartment_number for place in candidates) or not explicit:
                compartment_check = RequirementCheck(RequirementStatus.UNKNOWN, f"Не подтверждено: {source_label} не передал номер купе для достаточной группы мест")
            else:
                compartment_check = RequirementCheck(RequirementStatus.REJECTED, "Не подходит: подтверждённые места находятся в разных вагонах или купе")

        allocation = self.seat_allocator.match(explicit, SeatPreferences(
            passengers=required,
            prefer_lower=pref.berth_preference == "lower_only",
            prefer_upper=pref.berth_preference == "upper_only",
            require_same_compartment=pref.require_same_compartment,
            require_empty_compartment=pref.require_empty_compartment,
            require_same_carriage=pref.require_same_carriage and not pref.allow_split_group,
            require_adjacent=pref.require_adjacent,
            exclude_side_berths=pref.exclude_side_berths,
            gender=GenderRestriction(pref.gender) if pref.gender else None,
        ))
        if allocation.matches_preferences and pref.berth_preference == "lower_only" and not all(p.berth_position == BerthPosition.LOWER for p in allocation.selected_places):
            allocation = replace(allocation, matches_preferences=False, reasons=(*allocation.reasons, "Недостаточно явно подтверждённых нижних мест"))
        if allocation.matches_preferences and pref.berth_preference == "upper_only" and not all(p.berth_position == BerthPosition.UPPER for p in allocation.selected_places):
            allocation = replace(allocation, matches_preferences=False, reasons=(*allocation.reasons, "Недостаточно явно подтверждённых верхних мест"))
        if allocation.matches_preferences and pref.maximum_compartments is not None:
            compartments = {(p.carriage_number, p.compartment_number) for p in allocation.selected_places if p.compartment_number}
            if len(compartments) > pref.maximum_compartments:
                allocation = replace(allocation, matches_preferences=False, reasons=(*allocation.reasons, "Превышено допустимое количество купе"))

        active_checks = [check for check in (lower_check, compartment_check) if check is not None]
        checks_confirmed = all(check.status == RequirementStatus.CONFIRMED for check in active_checks)
        all_confirmed = bool(explicit) and allocation.matches_preferences and checks_confirmed
        any_rejected = bool(trusted_explicit) and (not allocation.matches_preferences or any(check.status in {RequirementStatus.REJECTED, RequirementStatus.NOT_APPLICABLE} for check in active_checks))
        status = (AvailabilityStatus.CONFIRMED if all_confirmed else
            AvailabilityStatus.UNAVAILABLE if any_rejected and pref.strict_preferences else
            AvailabilityStatus.PARTIALLY_CONFIRMED if any_rejected else
            (base.status if base.status in {AvailabilityStatus.UNCONFIRMED, AvailabilityStatus.PROVIDER_ERROR} else AvailabilityStatus.PARTIALLY_CONFIRMED))
        # ``selected_*`` is a bookable allocation, not partial diagnostic
        # evidence. Never expose places which fail any active constraint.
        selected = list(allocation.selected_places) if all_confirmed else []

        def evidence_for(items: list[RailwayPlace]) -> tuple[dict, ...]:
            return tuple({
                "train_number": segment.vehicle_number, "departure_datetime": segment.departure_datetime.isoformat(),
                "carriage_number": p.carriage_number, "carriage_type": p.transport_class.value,
                "service_class": p.metadata.get("service_class"), "compartment_number": p.compartment_number,
                "place_number": p.place_number, "place_type": p.place_type,
                "berth_position": p.berth_position.value, "source": str(p.metadata.get("source") or "rzd_explicit_place_details"),
                "explicitly_confirmed": p.explicitly_confirmed,
            } for p in items)

        evidence = evidence_for(selected) if all_confirmed else ()
        if lower_check and lower_check.status == RequirementStatus.CONFIRMED:
            lower_evidence = evidence_for(lower_places[:required])
            lower_check = replace(lower_check, message=f"Подтверждено: нижние места {', '.join(p.place_number for p in lower_places[:required])}", evidence=lower_evidence)
        if compartment_check and compartment_check.status == RequirementStatus.CONFIRMED:
            compartment_evidence = evidence_for(selected_group[:required])
            compartment_check = replace(compartment_check, message=f"Подтверждено: вагон {selected_group[0].carriage_number}, купе {selected_group[0].compartment_number}, места {', '.join(p.place_number for p in selected_group[:required])}", evidence=compartment_evidence)
        warnings = () if all_confirmed else tuple(check.message for check in active_checks if check.status == RequirementStatus.UNKNOWN)
        if lower_check and lower_check.status == RequirementStatus.UNKNOWN:
            warnings = (*warnings, f"{source_label} не предоставил номера и явное подтверждение двух нижних мест.")
        if compartment_check and compartment_check.status == RequirementStatus.UNKNOWN:
            warnings = (*warnings, f"{source_label} не предоставил номер вагона и купе для размещения всех сотрудников вместе.")
        return replace(base, status=status, seats_confirmed=all_confirmed, passengers_supported=all_confirmed,
            seat_preferences_status=AvailabilityStatus.CONFIRMED if all_confirmed else AvailabilityStatus.UNAVAILABLE if any_rejected and pref.strict_preferences else AvailabilityStatus.PARTIALLY_CONFIRMED if any_rejected else AvailabilityStatus.UNKNOWN,
            lower_berths_check=lower_check, same_compartment_check=compartment_check,
            selected_places=tuple(p.place_number for p in selected), selected_carriages=tuple(sorted({p.carriage_number for p in selected})),
            selected_compartments=tuple(sorted({p.compartment_number for p in selected if p.compartment_number})),
            reasons=tuple(dict.fromkeys((*base.reasons, *allocation.reasons))),
            warnings=tuple(dict.fromkeys((*base.warnings, *warnings))),
            metadata={**base.metadata, "selected_place_evidence": evidence,
                "lower_berths_confirmed": bool(lower_check and lower_check.status == RequirementStatus.CONFIRMED),
                "same_compartment_confirmed": bool(compartment_check and compartment_check.status == RequirementStatus.CONFIRMED)})

    def _place_from_dict(self, provider: str, item: dict, fallback_class: TransportClass | None) -> RailwayPlace:
        raw_class = str(item.get("transport_class") or item.get("carriage_type") or "").casefold()
        class_by_provider_value = {"coupe": TransportClass.COUPE, "купе": TransportClass.COUPE, "platzkart": TransportClass.PLATZKART, "плацкарт": TransportClass.PLATZKART, "sleeper": TransportClass.SLEEPER, "св": TransportClass.SLEEPER, "seated": TransportClass.SEATED, "сидячий": TransportClass.SEATED}
        transport_class = class_by_provider_value.get(raw_class, fallback_class or TransportClass.SEATED)
        gender = str(item.get("gender") or item.get("gender_restriction") or "unknown").casefold()
        return RailwayPlace(provider=provider, place_number=str(item.get("place_number") or item.get("number") or ""), carriage_number=str(item.get("carriage_number") or item.get("carriage") or ""), transport_class=transport_class, place_type=str(item.get("place_type") or "unknown"), berth_position=BerthPosition(item.get("berth_position") or BerthPosition.UNKNOWN), compartment_number=item.get("compartment_number"), is_side=bool(item.get("is_side", False)), gender_restriction=GenderRestriction(gender) if gender in {item.value for item in GenderRestriction} else GenderRestriction.UNKNOWN, is_available=bool(item.get("is_available", True)), explicitly_confirmed=bool(item.get("explicitly_confirmed", False)), metadata={"service_class": item.get("service_class"), "source": item.get("source")})

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
