from datetime import date
import logging
from app.algorithms.search import GraphRouteSearch
from app.availability import AvailabilityEngine, AvailabilityPolicy
from app.domain import Route, TransportProvider, TransportType
from app.graph.builder import GraphBuilder
from app.intelligence import NearbyCityResolver, RouteComparator, StationResolver, TransferEngine
from app.scoring.service import ScoringService
from app.validators.validation import ValidationService


logger = logging.getLogger(__name__)


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
        self.last_diagnostics: dict = {}

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
            segments = self.provider.get_segments(departure_date, allowed_transport, origin=origin, destination=destination, origin_provider_code=origin_provider_code, destination_provider_code=destination_provider_code, origin_location_id=origin_location_id, destination_location_id=destination_location_id, origin_location_type=origin_location_type, destination_location_type=destination_location_type)
        except TypeError:
            segments = self.provider.get_segments(departure_date, allowed_transport)
        self.last_segments_count = len(segments)
        logger.info("route_search.segments_loaded count=%s origin=%r destination=%r", len(segments), origin, destination)
        self.validator.validate_segments(segments)
        graph = self.graph_builder.build(segments)
        origin_cities = self.station_resolver.resolve_city_names(origin, segments)
        destination_cities = self.station_resolver.resolve_city_names(destination, segments)
        origin_station = self._station_code(origin_location_id, origin_provider_code, origin_location_type)
        destination_station = self._station_code(destination_location_id, destination_provider_code, destination_location_type)
        # Direct candidates are generated independently of the transfer graph.
        # max_transfers is an upper bound, so these are valid for every value.
        direct_routes, direct_rejections = self._direct_routes(
            segments, origin_cities, destination_cities, origin_station,
            destination_station, maximum_total_duration_minutes,
        )
        graph_routes = self.search_algorithm.find_routes(graph, origin_cities, destination_cities, passengers, max_transfers, minimum_transfer_minutes, maximum_transfer_minutes, maximum_total_duration_minutes, allow_overnight_transfer, origin_station, destination_station)
        routes = self._dedupe_routes([*direct_routes, *graph_routes])
        logger.info("route_search.transfer_filter direct_and_transfer_candidates=%s max_transfers=%s min_transfer=%s max_transfer=%s", len(routes), max_transfers, minimum_transfer_minutes, maximum_transfer_minutes)
        if not routes:
            alternatives = self.nearby_city_resolver.alternatives_for(destination_cities[0])
            for alternative in alternatives:
                routes = self.search_algorithm.find_routes(graph, origin_cities, (alternative,), passengers, max_transfers, minimum_transfer_minutes, maximum_transfer_minutes, maximum_total_duration_minutes, allow_overnight_transfer, self._station_code(origin_location_id, origin_provider_code, origin_location_type), self._station_code(destination_location_id, destination_provider_code, destination_location_type))
                if routes:
                    break
        ranked = self.route_comparator.rank(routes)
        self.last_diagnostics = {
            "raw_direct_candidates": [self._describe_segment(segment) for segment in segments if segment.origin_city.name in origin_cities and segment.destination_city.name in destination_cities],
            "filtered_direct_candidates": [self._describe_segment(route.segments[0]) for route in direct_routes],
            "rejection_reasons": direct_rejections,
            "ranked_candidates": [self._describe_route(option.route, option.rank) for option in ranked],
        }
        logger.info("route_search.dedup_rank routes_before_rank=%s routes_after_rank=%s", len(routes), len(ranked))
        policy = AvailabilityPolicy.for_group(
            passengers,
            preferred_classes=tuple(preferred_classes),
            require_group_together=require_group_together,
            allow_split_group=allow_split_group,
        )
        checked = [self.availability_engine.attach(option, policy) for option in ranked]
        available = [option for option in checked if option.availability and option.availability.is_available]
        logger.info("route_search.availability_filter checked=%s removed=%s include_unavailable=%s", len(checked), len(checked) - len(available), include_unavailable)
        if include_unavailable:
            return checked
        return available

    def _direct_routes(self, segments, origin_cities, destination_cities, origin_station, destination_station, maximum_duration):
        routes, rejected = [], []
        for segment in segments:
            if segment.origin_city.name not in origin_cities or segment.destination_city.name not in destination_cities:
                continue
            reasons = []
            if origin_station and segment.origin_station.id.lower() != origin_station.lower():
                reasons.append("origin_station_mismatch")
            if destination_station and segment.destination_station.id.lower() != destination_station.lower():
                reasons.append("destination_station_mismatch")
            if maximum_duration is not None and segment.duration_minutes > maximum_duration:
                reasons.append("maximum_total_duration_exceeded")
            if reasons:
                rejected.append({"candidate": self._describe_segment(segment), "reasons": reasons, "stage": "schedule_filter"})
            else:
                routes.append(Route((segment,)))
        return routes, rejected

    def _dedupe_routes(self, routes):
        output, seen = [], set()
        for route in routes:
            key = tuple(segment.id for segment in route.segments)
            if key not in seen:
                seen.add(key)
                output.append(route)
        return output

    def _describe_segment(self, segment):
        return {
            "id": segment.id, "train_number": segment.vehicle_number,
            "title": segment.metadata.get("train_title"),
            "departure": segment.departure_datetime.isoformat(),
            "arrival": segment.arrival_datetime.isoformat(),
            "duration_minutes": segment.duration_minutes, "provider": segment.provider,
            "transport_type": segment.transport_type.value,
            "transport_subtype": segment.metadata.get("transport_subtype") or segment.metadata.get("raw_transport_type"),
        }

    def _describe_route(self, route, rank):
        return {"rank": rank, "segment_ids": [s.id for s in route.segments], "train_numbers": [s.vehicle_number for s in route.segments], "transfers": route.transfers_count, "duration_minutes": route.total_duration_minutes}

    def _station_code(self, location_id: str | None, provider_code: str | None, location_type: str | None) -> str | None:
        if location_type in {"station", "railway_station", "bus_station"}:
            return provider_code or (location_id.split(":", 1)[1] if location_id and ":" in location_id else location_id)
        return None
