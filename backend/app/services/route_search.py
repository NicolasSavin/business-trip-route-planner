from app.domain import RouteOption as DomainRouteOption
from app.engine import RouteEngine
from app.availability.journey import AvailabilityStatus, JourneyAvailabilityResult
from app.models.routes import RouteAvailability, RouteOption, RouteSearchRequest, RouteSearchResponse, RouteSegment, SegmentAvailability, SearchSummary
from app.providers.base import TransportProvider
from app.services.multimodal_journey_planner import MultimodalJourneyPlanner


class RouteSearchService:
    def __init__(self, provider: TransportProvider):
        self.engine = RouteEngine(provider)
        self.planner = MultimodalJourneyPlanner(provider)

    def search(self, request: RouteSearchRequest, include_unavailable: bool = False) -> list[RouteOption]:
        response = self.search_response(request, include_unavailable=include_unavailable)
        return response.routes + (response.partially_confirmed_routes if include_unavailable else []) + (response.rejected_routes if include_unavailable else [])

    def search_response(self, request: RouteSearchRequest, include_unavailable: bool = False) -> RouteSearchResponse:
        routes, partial, rejected, summary = self.planner.search(request)
        api_routes = [self._to_api_route(option, request.passengers) for option in routes]
        api_partial = [self._to_api_route(option, request.passengers) for option in partial]
        api_rejected = [self._to_api_route(option, request.passengers) for option in rejected]
        if not include_unavailable and not request.strict_availability:
            api_rejected = []
        diagnostic_rejected = api_rejected + (api_partial if request.strict_availability else [])
        return RouteSearchResponse(routes=api_routes, warnings=summary.warnings, provider_errors=summary.provider_errors, partially_confirmed_routes=api_partial if not request.strict_availability else [], rejected_routes=diagnostic_rejected, search_summary=summary)

    def _to_api_route(self, option: DomainRouteOption, passengers: int) -> RouteOption:
        route = option.route
        segments = [
            RouteSegment(
                id=segment.id,
                provider=segment.provider,
                origin=segment.origin_city.name,
                destination=segment.destination_city.name,
                transport_type=segment.transport_type,
                number=segment.vehicle_number,
                departure_time=segment.departure_datetime,
                arrival_time=segment.arrival_datetime,
                available_seats=segment.available_seats,
                origin_station=segment.origin_station.name,
                destination_station=segment.destination_station.name,
                carrier=segment.carrier.name,
                source=segment.metadata.get("source") or segment.metadata.get("source_provider") or segment.provider,
                availability_message="Наличие мест пока не подтверждено" if segment.metadata.get("availability_unknown") else None,
            )
            for segment in route.segments
        ]
        first_transfer = route.transfers[0] if route.transfers else None
        availability = None
        segment_availability_by_id = {}
        if option.availability:
            if isinstance(option.availability, JourneyAvailabilityResult):
                segment_results = []
                for result in option.availability.segment_results:
                    segment_availability_by_id[result.segment_id] = result
                    segment_results.append(
                        SegmentAvailability(
                            segment_id=result.segment_id,
                            is_available=result.status == AvailabilityStatus.CONFIRMED,
                            available_seats=result.available_places_count,
                            requested_passengers=passengers,
                            transport_class=None,
                            checked_at=result.checked_at,
                            source=result.provider,
                            reason=", ".join(result.reasons) or None,
                            warnings=list(result.warnings),
                            is_stale=result.is_stale,
                        )
                    )
                minimum = min((r.available_places_count for r in option.availability.segment_results), default=0)
                availability = RouteAvailability(
                    is_available=option.availability.status == AvailabilityStatus.CONFIRMED,
                    requested_passengers=passengers,
                    minimum_available_seats=minimum,
                    checked_at=option.availability.checked_at,
                    segment_results=segment_results,
                    reasons=list(option.availability.reasons),
                    warnings=list(option.availability.warnings),
                    is_stale=option.availability.status == AvailabilityStatus.STALE,
                )
                availability.segments = availability.segment_results
            else:
                availability = RouteAvailability(
                    is_available=option.availability.is_available,
                    requested_passengers=option.availability.requested_passengers,
                    minimum_available_seats=option.availability.minimum_available_seats,
                    checked_at=option.availability.checked_at,
                    segment_results=[
                        SegmentAvailability(
                            segment_id=result.segment_id,
                            is_available=result.is_available,
                            available_seats=result.available_seats,
                            requested_passengers=result.requested_passengers,
                            transport_class=result.transport_class,
                            checked_at=result.checked_at,
                            source=result.source,
                            reason=result.reason,
                            warnings=list(result.warnings),
                            stale_after_seconds=result.stale_after_seconds,
                            is_stale=result.is_stale,
                        )
                        for result in option.availability.segment_results
                    ],
                    reasons=list(option.availability.reasons),
                    warnings=list(option.availability.warnings),
                    stale_after_seconds=option.availability.stale_after_seconds,
                    is_stale=option.availability.is_stale,
                )
                availability.segments = availability.segment_results

        api_segments = []
        for item in segments:
            result = segment_availability_by_id.get(item.id)
            if result:
                item.availability_source = result.provider
                item.availability_status = result.status.value
                item.selected_places = list(result.selected_places)
                item.selected_carriages = list(result.selected_carriages)
                item.selected_compartments = list(result.selected_compartments)
                item.availability_message = {
                    AvailabilityStatus.CONFIRMED: "Все места подтверждены",
                    AvailabilityStatus.PARTIALLY_CONFIRMED: "Часть наличия не проверена",
                    AvailabilityStatus.UNAVAILABLE: "Нет подходящих мест",
                    AvailabilityStatus.UNKNOWN: "Наличие мест неизвестно",
                    AvailabilityStatus.STALE: "Проверка устарела",
                    AvailabilityStatus.PROVIDER_ERROR: "Ошибка проверки наличия",
                }.get(result.status, item.availability_message)
            api_segments.append(item)
        return RouteOption(
            id="route-" + "-".join(segment.id for segment in route.segments),
            provider=",".join(sorted({segment.provider for segment in route.segments})),
            origin=route.segments[0].origin_city.name,
            destination=route.segments[-1].destination_city.name,
            segments=api_segments,
            transfer_city=first_transfer.city.name if first_transfer else None,
            transfer_duration_minutes=sum(transfer.duration_minutes for transfer in route.transfers) if route.transfers else None,
            transfers=[self._to_api_transfer(transfer) for transfer in route.transfers],
            total_wait_minutes=sum(transfer.duration_minutes for transfer in route.transfers),
            total_price=sum((segment.price or 0) for segment in route.segments) or None,
            total_duration_minutes=route.total_duration_minutes,
            transfers_count=route.transfers_count,
            is_available_for_group=option.availability.is_available if option.availability else all(segment.available_seats >= passengers for segment in route.segments),
            score=option.score,
            rank=option.rank,
            explanation=option.explanation,
            warnings=list(option.warnings),
            advantages=list(option.advantages),
            availability=availability,
        )

    def _to_api_transfer(self, transfer) -> dict:
        return {
            "location": transfer.city.name,
            "arrival_station": transfer.from_segment.destination_station.name,
            "departure_station": transfer.to_segment.origin_station.name,
            "transfer_type": transfer.transfer_type,
            "duration_minutes": transfer.duration_minutes,
            "required_minimum_minutes": getattr(self.planner.route_engine.transfer_engine, "minimum_transfer_minutes", 35),
            "station_change_required": transfer.station_change,
            "local_transfer_minutes": transfer.estimated_transfer_minutes,
            "overnight": transfer.is_night or transfer.from_segment.arrival_datetime.date() != transfer.to_segment.departure_datetime.date(),
            "warnings": list(transfer.warnings),
        }
