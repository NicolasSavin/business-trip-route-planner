from datetime import date, datetime, timedelta
import pytest

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.graph.builder import GraphBuilder
from app.scoring.service import ScoringService
from app.validators.validation import ValidationService

DAY = date(2026, 8, 10)


def dt(hour):
    return datetime(2026, 8, 10, hour)


def seg(id, origin, destination, dep, arr, seats=5):
    oc, dc = City(origin), City(destination)
    return TransportSegment(
        id=id,
        provider="test",
        carrier=Carrier("c", "Carrier"),
        transport_type=TransportType.TRAIN,
        transport_class=TransportClass.SEATED,
        vehicle_number=id,
        origin_city=oc,
        origin_station=Station(f"{origin}-s", f"{origin} station", oc),
        destination_city=dc,
        destination_station=Station(f"{destination}-s", f"{destination} station", dc),
        departure_datetime=dep,
        arrival_datetime=arr,
        duration_minutes=int((arr - dep).total_seconds() // 60),
        available_seats=seats,
        price=None,
        metadata={},
    )


class Provider:
    def __init__(self, segments):
        self.segments = segments

    def get_segments(self, *_args, **_kwargs):
        return self.segments


def test_graph_builder_creates_station_vertices_and_segment_edges():
    segment = seg("ab", "Москва", "Казань", dt(8), dt(12))
    graph = GraphBuilder().build([segment])
    assert segment.origin_station.id in graph.stations
    assert graph.outgoing(segment.origin_station) == [segment]


def test_validation_service_rejects_bad_segment_times_and_negative_seats():
    validator = ValidationService()
    with pytest.raises(ValueError):
        validator.validate_segment(seg("bad-time", "A", "B", dt(12), dt(11)))
    with pytest.raises(ValueError):
        validator.validate_segment(seg("bad-seats", "A", "B", dt(10), dt(11), seats=-1))


def test_scoring_prefers_fewer_transfers_then_shorter_duration():
    direct = RouteEngine(Provider([seg("direct", "A", "C", dt(8), dt(12))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 0, 30)[0]
    one = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(10), dt(11))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)[0]
    assert ScoringService().score(direct.route) < ScoringService().score(one.route)


def test_route_engine_finds_one_transfer_route():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(10), dt(11))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)
    assert len(routes) == 1
    assert routes[0].route.transfers_count == 1


def test_route_engine_finds_two_transfer_route():
    routes = RouteEngine(Provider([
        seg("ab", "A", "B", dt(6), dt(7)),
        seg("bc", "B", "C", dt(8), dt(9)),
        seg("cd", "C", "D", dt(10), dt(11)),
    ])).search(DAY, "A", "D", 1, [TransportType.TRAIN], 2, 30)
    assert len(routes) == 1
    assert routes[0].route.transfers_count == 2


def test_route_engine_returns_no_route_when_path_absent():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 2, 30)
    assert routes == []


def test_route_engine_filters_routes_without_enough_seats():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9), seats=1), seg("bc", "B", "C", dt(10), dt(11), seats=5)])).search(DAY, "A", "C", 2, [TransportType.TRAIN], 1, 30)
    assert routes == []


def test_transfer_requires_minimum_wait_in_same_city():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(9), dt(11))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)
    assert routes == []
