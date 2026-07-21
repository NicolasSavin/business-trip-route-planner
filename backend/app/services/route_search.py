from datetime import timedelta
from app.models.routes import RouteOption, RouteSearchRequest, RouteSegment
from app.providers.base import TransportProvider


class RouteSearchService:
    def __init__(self, provider: TransportProvider):
        self.provider = provider

    def search(self, request: RouteSearchRequest) -> list[RouteOption]:
        segments = self.provider.get_segments(request.departure_date, request.allowed_transport)
        candidates: list[RouteOption] = []

        for segment in segments:
            if segment.origin == request.origin and segment.destination == request.destination:
                candidates.append(self._build_route([segment], request.passengers))

        if request.max_transfers >= 1:
            candidates.extend(self._search_one_transfer(segments, request))

        return sorted(candidates, key=lambda route: (route.transfers_count, route.total_duration_minutes))

    def _search_one_transfer(self, segments: list[RouteSegment], request: RouteSearchRequest) -> list[RouteOption]:
        routes: list[RouteOption] = []
        min_transfer = timedelta(minutes=request.minimum_transfer_minutes)
        first_legs = [segment for segment in segments if segment.origin == request.origin]
        second_legs = [segment for segment in segments if segment.destination == request.destination]

        for first in first_legs:
            for second in second_legs:
                if first.destination != second.origin:
                    continue
                transfer_duration = second.departure_time - first.arrival_time
                if transfer_duration < min_transfer:
                    continue
                if second.departure_time <= first.arrival_time:
                    continue
                routes.append(self._build_route([first, second], request.passengers))
        return routes

    def _build_route(self, segments: list[RouteSegment], passengers: int) -> RouteOption:
        first = segments[0]
        last = segments[-1]
        transfer_duration_minutes = None
        transfer_city = None
        if len(segments) == 2:
            transfer_city = first.destination
            transfer_duration_minutes = int((segments[1].departure_time - first.arrival_time).total_seconds() // 60)

        return RouteOption(
            id="route-" + "-".join(segment.id for segment in segments),
            origin=first.origin,
            destination=last.destination,
            segments=segments,
            transfer_city=transfer_city,
            transfer_duration_minutes=transfer_duration_minutes,
            total_duration_minutes=int((last.arrival_time - first.departure_time).total_seconds() // 60),
            transfers_count=len(segments) - 1,
            is_available_for_group=all(segment.available_seats >= passengers for segment in segments),
        )
