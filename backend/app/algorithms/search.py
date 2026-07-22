from app.domain import Route, Transfer, TransportSegment
from app.graph.builder import TransportGraph
from app.intelligence.transfers import TransferEngine


class GraphRouteSearch:
    def __init__(self, transfer_engine: TransferEngine | None = None):
        self.transfer_engine = transfer_engine or TransferEngine()

    def find_routes(
        self,
        graph: TransportGraph,
        origin_city: str | tuple[str, ...],
        destination_city: str | tuple[str, ...],
        passengers: int,
        max_transfers: int,
        minimum_transfer_minutes: int,
        maximum_transfer_minutes: int = 360,
        maximum_total_duration_minutes: int | None = None,
        allow_overnight_transfer: bool = True,
        origin_station_id: str | None = None,
        destination_station_id: str | None = None,
    ) -> list[Route]:
        origin_cities = (origin_city,) if isinstance(origin_city, str) else origin_city
        destination_cities = (destination_city,) if isinstance(destination_city, str) else destination_city
        routes: list[Route] = []
        max_segments = max_transfers + 1
        if origin_station_id:
            starts = [station for station in graph.stations.values() if station.id == origin_station_id or station.id.lower() == origin_station_id.lower()]
        else:
            starts = [station for station in graph.stations.values() if station.city.name in origin_cities]
        for station in starts:
            self._dfs(graph, station.id, destination_cities, passengers, max_segments, minimum_transfer_minutes, maximum_transfer_minutes, maximum_total_duration_minutes, allow_overnight_transfer, [], routes, destination_station_id, set())
        return routes

    def _dfs(self, graph, station_id, destination_city, passengers, max_segments, min_transfer, max_transfer, max_total_duration, allow_overnight_transfer, path, routes, destination_station_id=None, visited_cities=None):
        if len(path) >= max_segments:
            return
        visited_cities = visited_cities or set()
        candidate_station_ids = [station_id]
        if path:
            candidate_station_ids = graph.station_ids_by_city.get(path[-1].destination_city.name, [station_id])
        for candidate_station_id in candidate_station_ids:
            for segment in graph.adjacency.get(candidate_station_id, []):
                if segment in path or segment.destination_city.name in visited_cities:
                    continue
                if path and not self._can_transfer(path[-1], segment, min_transfer, max_transfer, allow_overnight_transfer):
                    continue
                new_path = [*path, segment]
                destination_matches = segment.destination_city.name in destination_city
                if destination_station_id:
                    destination_matches = segment.destination_station.id == destination_station_id or segment.destination_station.id.lower() == destination_station_id.lower()
                if max_total_duration is not None and new_path:
                    total = int((new_path[-1].arrival_datetime - new_path[0].departure_datetime).total_seconds() // 60)
                    if total > max_total_duration:
                        continue
                if destination_matches:
                    route = self._build_route(new_path)
                    routes.append(route)
                next_visited = {*visited_cities, segment.origin_city.name}
                self._dfs(graph, segment.destination_station.id, destination_city, passengers, max_segments, min_transfer, max_transfer, max_total_duration, allow_overnight_transfer, new_path, routes, destination_station_id, next_visited)

    def _can_transfer(self, first: TransportSegment, second: TransportSegment, minimum_transfer_minutes: int, maximum_transfer_minutes: int = 360, allow_overnight_transfer: bool = True) -> bool:
        same_city = first.destination_city.name == second.origin_city.name
        stations_same_city = first.destination_station.city.name == second.origin_station.city.name
        if not (same_city or stations_same_city):
            return False
        transfer_minutes = int((second.departure_datetime - first.arrival_datetime).total_seconds() // 60)
        if transfer_minutes < minimum_transfer_minutes or transfer_minutes > maximum_transfer_minutes:
            return False
        if not allow_overnight_transfer and first.arrival_datetime.date() != second.departure_datetime.date():
            return False
        return True

    def _build_route(self, segments: list[TransportSegment]) -> Route:
        transfers: list[Transfer] = []
        for first, second in zip(segments, segments[1:]):
            transfers.append(self.transfer_engine.build_transfer(first, second))
        return Route(tuple(segments), tuple(transfers))
