from collections import defaultdict
from dataclasses import dataclass
from app.domain import Station, TransportSegment


@dataclass
class TransportGraph:
    adjacency: dict[str, list[TransportSegment]]
    stations: dict[str, Station]
    station_ids_by_city: dict[str, list[str]]

    def outgoing(self, station: Station) -> list[TransportSegment]:
        return self.adjacency.get(station.id, [])


class GraphBuilder:
    def build(self, segments: list[TransportSegment]) -> TransportGraph:
        adjacency: dict[str, list[TransportSegment]] = defaultdict(list)
        stations: dict[str, Station] = {}
        station_ids_by_city: dict[str, set[str]] = defaultdict(set)
        for segment in segments:
            stations[segment.origin_station.id] = segment.origin_station
            stations[segment.destination_station.id] = segment.destination_station
            adjacency[segment.origin_station.id].append(segment)
            station_ids_by_city[segment.origin_city.name].add(segment.origin_station.id)
            station_ids_by_city[segment.destination_city.name].add(segment.destination_station.id)
        for edges in adjacency.values():
            edges.sort(key=lambda segment: segment.departure_datetime)
        return TransportGraph(adjacency=dict(adjacency), stations=stations, station_ids_by_city={city: sorted(ids) for city, ids in station_ids_by_city.items()})
