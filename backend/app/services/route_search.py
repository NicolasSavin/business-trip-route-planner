from app.domain import RouteOption as DomainRouteOption
from app.engine import RouteEngine
from app.models.routes import RouteOption, RouteSearchRequest, RouteSegment
from app.providers.base import TransportProvider


class RouteSearchService:
    def __init__(self, provider: TransportProvider):
        self.engine = RouteEngine(provider)

    def search(self, request: RouteSearchRequest) -> list[RouteOption]:
        options = self.engine.search(
            departure_date=request.departure_date,
            origin=request.origin,
            destination=request.destination,
            passengers=request.passengers,
            allowed_transport=request.allowed_transport,
            max_transfers=request.max_transfers,
            minimum_transfer_minutes=request.minimum_transfer_minutes,
        )
        return [self._to_api_route(option, request.passengers) for option in options]

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
        return RouteOption(
            id="route-" + "-".join(segment.id for segment in route.segments),
            origin=route.segments[0].origin_city.name,
            destination=route.segments[-1].destination_city.name,
            segments=segments,
            transfer_city=first_transfer.city.name if first_transfer else None,
            transfer_duration_minutes=sum(transfer.duration_minutes for transfer in route.transfers) if route.transfers else None,
            total_duration_minutes=route.total_duration_minutes,
            transfers_count=route.transfers_count,
            is_available_for_group=all(segment.available_seats >= passengers for segment in route.segments),
            score=option.score,
            rank=option.rank,
            explanation=option.explanation,
            warnings=list(option.warnings),
            advantages=list(option.advantages),
        )
