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
    ) -> list[Route]:
        origin_cities = (origin_city,) if isinstance(origin_city, str) else origin_city
        destination_cities = (destination_city,) if isinstance(destination_city, str) else destination_city
        routes: list[Route] = []
        max_segments = max_transfers + 1
        starts = [station for station in graph.stations.values() if station.city.name in origin_cities]
        for station in starts:
            self._dfs(graph, station.id, destination_cities, passengers, max_segments, minimum_transfer_minutes, [], routes)
        return routes

    def _dfs(self, graph, station_id, destination_city, passengers, max_segments, min_transfer, path, routes):
        if len(path) >= max_segments:
            return
        candidate_station_ids = [station_id]
        if path:
            candidate_station_ids = graph.station_ids_by_city.get(path[-1].destination_city.name, [station_id])
        for candidate_station_id in candidate_station_ids:
            for segment in graph.adjacency.get(candidate_station_id, []):
                if segment in path:
                    continue
                if path and not self._can_transfer(path[-1], segment, min_transfer):
                    continue
                new_path = [*path, segment]
                if segment.destination_city.name in destination_city:
                    route = self._build_route(new_path)
                    routes.append(route)
                self._dfs(graph, segment.destination_station.id, destination_city, passengers, max_segments, min_transfer, new_path, routes)

    def _can_transfer(self, first: TransportSegment, second: TransportSegment, minimum_transfer_minutes: int) -> bool:
        same_city = first.destination_city.name == second.origin_city.name
        stations_same_city = first.destination_station.city.name == second.origin_station.city.name
        if not (same_city or stations_same_city):
            return False
        transfer_minutes = int((second.departure_datetime - first.arrival_datetime).total_seconds() // 60)
        return transfer_minutes >= minimum_transfer_minutes

    def _build_route(self, segments: list[TransportSegment]) -> Route:
        transfers: list[Transfer] = []
        for first, second in zip(segments, segments[1:]):
            transfers.append(self.transfer_engine.build_transfer(first, second))
        return Route(tuple(segments), tuple(transfers))
