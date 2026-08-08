from datetime import date, datetime, timedelta
import pytest

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.graph.builder import GraphBuilder
from app.intelligence.stations import canonical_city_name, city_names_match
from app.scoring.service import ScoringService
from app.providers.yandex.mapper import YandexRaspMapper
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


def test_max_transfers_one_includes_direct_and_transfer_routes():
    routes = RouteEngine(Provider([
        seg("sapsan", "A", "C", dt(8), dt(12)),
        seg("ab", "A", "B", dt(7), dt(12)),
        seg("bc", "B", "C", dt(13), dt(21)),
    ])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)

    assert {route.route.transfers_count for route in routes} == {0, 1}
    assert routes[0].route.segments[0].vehicle_number == "sapsan"


def test_max_transfers_zero_only_includes_direct_route():
    routes = RouteEngine(Provider([
        seg("direct", "A", "C", dt(8), dt(12)),
        seg("ab", "A", "B", dt(7), dt(9)),
        seg("bc", "B", "C", dt(10), dt(12)),
    ])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 0, 30)

    assert [route.route.transfers_count for route in routes] == [0]


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


def test_route_engine_attaches_unavailability_without_filtering_routes():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9), seats=1), seg("bc", "B", "C", dt(10), dt(11), seats=5)])).search(DAY, "A", "C", 2, [TransportType.TRAIN], 1, 30)
    assert len(routes) == 1
    assert routes[0].availability.is_available is False


def test_transfer_requires_minimum_wait_in_same_city():
    routes = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(9), dt(11))])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)
    assert routes == []


def yandex_moscow_petersburg_segment():
    payload = {"segments": [{
        # Production responses can omit settlement entirely even for valid
        # direct trains.  The station display title is not the city identity.
        "from": {"code": "s2000009", "title": "Москва (Ленинградский вокзал)"},
        "to": {"code": "s2004001", "title": "Санкт-Петербург (Московский вокзал)"},
        "departure": "2026-08-10T00:25:00+03:00",
        "arrival": "2026-08-10T08:53:00+03:00",
        "thread": {"uid": "754A", "number": "754А", "title": "Москва — Санкт-Петербург", "transport_type": "train"},
    }]}
    return YandexRaspMapper().to_segments(payload)[0]


@pytest.mark.parametrize("max_transfers", [0, 1])
def test_yandex_direct_city_route_matches_hyphen_variant_and_ranks_first(max_transfers):
    direct = yandex_moscow_petersburg_segment()
    via_ryazan = [
        seg("moscow-ryazan", "Москва", "Рязань", dt(1), dt(5)),
        seg("ryazan-petersburg", "Рязань", "Санкт-Петербург", dt(6), dt(15)),
    ]
    engine = RouteEngine(Provider([direct, *via_ryazan]))

    routes = engine.search(
        DAY, "Москва", "Санкт Петербург", 1, [TransportType.TRAIN],
        max_transfers, 30, origin_provider_code="not-a-station",
        destination_provider_code="not-a-station", origin_location_type="city",
        destination_location_type="city", include_unavailable=True,
    )

    assert routes[0].route.segments[0].vehicle_number == "754А"
    assert routes[0].route.transfers_count == 0
    assert any(item["train_number"] == "754А" for item in engine.last_diagnostics["raw_direct_candidates"])
    assert any(item["train_number"] == "754А" for item in engine.last_diagnostics["filtered_direct_candidates"])
    assert any(item["train_numbers"] == ["754А"] for item in engine.last_diagnostics["ranked_candidates"])
    assert engine.last_diagnostics["direct_candidate_source"] == {
        "collection": "provider_segments",
        "total_segment_count": 3,
        "direct_match_count": 1,
    }
    if max_transfers == 1:
        assert any(route.route.transfers_count == 1 and route.route.total_duration_minutes == 14 * 60 for route in routes)

    decision = next(item for item in engine.last_diagnostics["direct_match_decisions"] if item["candidate"]["train_number"] == "754А")
    assert decision["segment_origin_city"] == "Москва"
    assert decision["segment_destination_city"] == "Санкт-Петербург"
    assert decision["station_matching"] == {
        "origin_enforced": False, "destination_enforced": False,
        "origin_match": True, "destination_match": True,
    }
    assert decision["rejection_reason"] is None


def test_yandex_direct_station_search_resolves_settlement_and_enforces_station_ids():
    direct = yandex_moscow_petersburg_segment()
    engine = RouteEngine(Provider([direct]))

    routes = engine.search(
        DAY, "Москва (Ленинградский вокзал)", "Санкт-Петербург (Московский вокзал)", 1,
        [TransportType.TRAIN], 0, 30, origin_provider_code="s2000009",
        destination_provider_code="s2004001", origin_location_type="railway_station",
        destination_location_type="station", include_unavailable=True,
    )

    assert routes[0].route.segments == (direct,)
    decision = engine.last_diagnostics["direct_match_decisions"][0]
    assert decision["resolved_origin_cities"] == ["Москва"]
    assert decision["resolved_destination_cities"] == ["Санкт-Петербург"]
    assert decision["station_matching"]["origin_enforced"] is True
    assert decision["station_matching"]["destination_enforced"] is True


def test_city_identity_is_conservative_and_normalizes_spelling():
    assert canonical_city_name(" Москва (Ленинградский вокзал) ") == "москва"
    assert city_names_match("Санкт-Петербург", "Санкт–Петербург (Московский вокзал)")
    assert city_names_match("Орёл", "Орел")
    assert not city_names_match("Москва", "Москва-Сити")
    assert not city_names_match("Ростов", "Ростов-на-Дону")
    assert not city_names_match("Пушкин", "Пушкин (город)")


def test_graph_transfer_matches_station_qualified_city_identity():
    routes = RouteEngine(Provider([
        seg("ab", "Москва (Казанский вокзал)", "Рязань (Рязань-1 вокзал)", dt(7), dt(9)),
        seg("bc", "Рязань", "Санкт-Петербург (Московский вокзал)", dt(10), dt(14)),
    ])).search(DAY, "Москва", "Санкт-Петербург", 1, [TransportType.TRAIN], 1, 30)

    assert len(routes) == 1
    assert routes[0].route.transfers_count == 1


def test_explicit_station_code_does_not_broaden_to_city():
    direct = yandex_moscow_petersburg_segment()
    engine = RouteEngine(Provider([direct]))

    routes = engine.search(
        DAY, "Москва", "Санкт-Петербург", 1, [TransportType.TRAIN], 0, 30,
        origin_provider_code="s-other-moscow-station",
        destination_provider_code="s2004001", origin_location_type="station",
        destination_location_type="station", include_unavailable=True,
    )

    assert routes == []
    assert "origin_station_mismatch" in engine.last_diagnostics["direct_match_decisions"][0]["rejection_reason"]
