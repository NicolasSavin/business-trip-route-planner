from app.domain import RouteOption as DomainRouteOption
from app.engine import RouteEngine
from app.models.routes import RouteAvailability, RouteOption, RouteSearchRequest, RouteSegment, SegmentAvailability
from app.providers.base import TransportProvider


class RouteSearchService:
    def __init__(self, provider: TransportProvider):
        self.engine = RouteEngine(provider)

    def search(self, request: RouteSearchRequest, include_unavailable: bool = False) -> list[RouteOption]:
        options = self.engine.search(
            departure_date=request.departure_date,
            origin=request.origin,
            destination=request.destination,
            passengers=request.passengers,
            allowed_transport=request.allowed_transport,
            max_transfers=request.max_transfers,
            minimum_transfer_minutes=request.minimum_transfer_minutes,
            preferred_classes=request.preferred_classes,
            require_group_together=request.require_group_together,
            allow_split_group=request.allow_split_group,
            include_unavailable=include_unavailable,
        )
        # Preserve the original public API behavior: returned route options are usable
        # for the requested group, while each item now also carries optional details.
        api_routes = [self._to_api_route(option, request.passengers) for option in options]
        if include_unavailable:
            return api_routes
        return [route for route in api_routes if route.availability is None or route.availability.is_available]

    def _to_api_route(self, option: DomainRouteOption, passengers: int) -> RouteOption:
        route = option.route
        segments = [
            RouteSegment(
                id=segment.id,
                origin=segment.origin_city.name,
                destination=segment.destination_city.name,
                transport_type=segment.transport_type,
                number=segment.vehicle_number,
                departure_time=segment.departure_datetime,
                arrival_time=segment.arrival_datetime,
                available_seats=segment.available_seats,
            )
            for segment in route.segments
        ]
        first_transfer = route.transfers[0] if route.transfers else None
        availability = None
        if option.availability:
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
        return RouteOption(
            id="route-" + "-".join(segment.id for segment in route.segments),
            origin=route.segments[0].origin_city.name,
            destination=route.segments[-1].destination_city.name,
            segments=segments,
            transfer_city=first_transfer.city.name if first_transfer else None,
            transfer_duration_minutes=sum(transfer.duration_minutes for transfer in route.transfers) if route.transfers else None,
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
