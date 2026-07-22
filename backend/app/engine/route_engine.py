from datetime import date
from app.algorithms.search import GraphRouteSearch
from app.availability import AvailabilityEngine, AvailabilityPolicy
from app.domain import TransportProvider, TransportType
from app.graph.builder import GraphBuilder
from app.intelligence import NearbyCityResolver, RouteComparator, StationResolver, TransferEngine
from app.scoring.service import ScoringService
from app.validators.validation import ValidationService


class RouteEngine:
    def __init__(
        self,
        provider: TransportProvider,
        graph_builder: GraphBuilder | None = None,
        scorer: ScoringService | None = None,
        validator: ValidationService | None = None,
        station_resolver: StationResolver | None = None,
        nearby_city_resolver: NearbyCityResolver | None = None,
        route_comparator: RouteComparator | None = None,
        transfer_engine: TransferEngine | None = None,
        availability_engine: AvailabilityEngine | None = None,
    ):
        self.provider = provider
        self.graph_builder = graph_builder or GraphBuilder()
        self.scorer = scorer or ScoringService()
        self.validator = validator or ValidationService()
        self.station_resolver = station_resolver or StationResolver()
        self.nearby_city_resolver = nearby_city_resolver or NearbyCityResolver()
        self.transfer_engine = transfer_engine or TransferEngine(minimum_transfer_minutes=35)
        self.route_comparator = route_comparator or RouteComparator(self.scorer)
        self.search_algorithm = GraphRouteSearch(self.transfer_engine)
        self.availability_engine = availability_engine or AvailabilityEngine()
        self.last_segments_count = 0

    def search(
        self,
        departure_date: date,
        origin: str,
        destination: str,
        passengers: int,
        allowed_transport: list[TransportType],
        max_transfers: int,
        minimum_transfer_minutes: int,
        maximum_transfer_minutes: int = 360,
        maximum_total_duration_minutes: int | None = None,
        allow_overnight_transfer: bool = True,
        preferred_classes=(),
        require_group_together: bool = True,
        allow_split_group: bool = False,
        include_unavailable: bool = False,
        origin_location_id: str | None = None,
        origin_provider_code: str | None = None,
        origin_location_type: str | None = None,
        destination_location_id: str | None = None,
        destination_provider_code: str | None = None,
        destination_location_type: str | None = None,
    ):
        try:
            segments = self.provider.get_segments(departure_date, allowed_transport, origin=origin, destination=destination)
        except TypeError:
            segments = self.provider.get_segments(departure_date, allowed_transport)
        self.last_segments_count = len(segments)
        self.validator.validate_segments(segments)
        graph = self.graph_builder.build(segments)
        origin_cities = self.station_resolver.resolve_city_names(origin, segments)
        destination_cities = self.station_resolver.resolve_city_names(destination, segments)
        routes = self.search_algorithm.find_routes(graph, origin_cities, destination_cities, passengers, max_transfers, minimum_transfer_minutes, maximum_transfer_minutes, maximum_total_duration_minutes, allow_overnight_transfer, self._station_code(origin_location_id, origin_provider_code, origin_location_type), self._station_code(destination_location_id, destination_provider_code, destination_location_type))
        if not routes:
            alternatives = self.nearby_city_resolver.alternatives_for(destination_cities[0])
            for alternative in alternatives:
                routes = self.search_algorithm.find_routes(graph, origin_cities, (alternative,), passengers, max_transfers, minimum_transfer_minutes, maximum_transfer_minutes, maximum_total_duration_minutes, allow_overnight_transfer, self._station_code(origin_location_id, origin_provider_code, origin_location_type), self._station_code(destination_location_id, destination_provider_code, destination_location_type))
                if routes:
                    break
        ranked = self.route_comparator.rank(routes)
        policy = AvailabilityPolicy.for_group(
            passengers,
            preferred_classes=tuple(preferred_classes),
            require_group_together=require_group_together,
            allow_split_group=allow_split_group,
        )
        checked = [self.availability_engine.attach(option, policy) for option in ranked]
        if include_unavailable:
            return checked
        return [option for option in checked if option.availability and option.availability.is_available]

    def _station_code(self, location_id: str | None, provider_code: str | None, location_type: str | None) -> str | None:
        if location_type in {"station", "railway_station", "bus_station"}:
            return provider_code or (location_id.split(":", 1)[1] if location_id and ":" in location_id else location_id)
        return None
