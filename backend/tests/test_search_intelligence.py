from datetime import date, datetime

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.engine import RouteEngine
from app.intelligence import ExplanationService, NearbyCityResolver, RouteComparator, StationResolver, TransferEngine

DAY = date(2026, 8, 10)


def dt(hour, minute=0):
    return datetime(2026, 8, 10, hour, minute)


def seg(id, origin, destination, dep, arr, seats=5, origin_station=None, destination_station=None, ttype=TransportType.TRAIN):
    oc, dc = City(origin), City(destination)
    return TransportSegment(id=id, provider="test", carrier=Carrier("c", "Carrier"), transport_type=ttype, transport_class=TransportClass.SEATED, vehicle_number=id, origin_city=oc, origin_station=origin_station or Station(f"{origin}-s", f"{origin} station", oc), destination_city=dc, destination_station=destination_station or Station(f"{destination}-s", f"{destination} station", dc), departure_datetime=dep, arrival_datetime=arr, duration_minutes=int((arr - dep).total_seconds() // 60), available_seats=seats)


class Provider:
    def __init__(self, segments):
        self.segments = segments
    def get_segments(self, *_args, **_kwargs):
        return self.segments


def test_station_resolver_maps_station_to_city_and_all_city_stations():
    moscow = City("Москва")
    segment = seg("ab", "Москва", "Казань", dt(8), dt(12), origin_station=Station("msk-kaz", "Казанский вокзал", moscow))
    resolver = StationResolver()
    assert resolver.resolve_city_names("Казанский вокзал", [segment]) == ("Москва",)
    assert {station.name for station in resolver.stations_for_city("Москва", [segment])} >= {"Казанский вокзал", "Ленинградский вокзал"}


def test_nearby_city_resolver_returns_mock_alternatives():
    assert NearbyCityResolver().alternatives_for("Геленджик")[:2] == ("Новороссийск", "Краснодар")


def test_transfer_engine_marks_station_change_and_short_transfer():
    first = seg("ab", "A", "B", dt(8), dt(9), destination_station=Station("b-rail", "B rail", City("B")))
    second = seg("bc", "B", "C", dt(9, 20), dt(11), origin_station=Station("b-bus", "B bus", City("B")), ttype=TransportType.BUS)
    transfer = TransferEngine(minimum_transfer_minutes=35).build_transfer(first, second)
    assert transfer.transfer_type == "metro"
    assert transfer.station_change is True
    assert "Пересадка менее 35 минут" in transfer.warnings


def test_explanation_service_returns_warnings_and_advantages():
    route = RouteEngine(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(10), dt(11), seats=1)])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)[0].route
    explanation, warnings, advantages = ExplanationService().explain(route, 1, 2, 0)
    assert explanation.startswith("Маршрут найден")
    assert "Недостаточно мест" in warnings
    assert "Маршрут проиграл другому по score" in warnings
    assert "Самый быстрый" in advantages


def test_route_comparator_ranks_by_multi_factor_score():
    routes = RouteEngine(Provider([seg("direct", "A", "C", dt(8), dt(13), seats=10), seg("ab", "A", "B", dt(8), dt(9), seats=10), seg("bc", "B", "C", dt(10), dt(11), seats=10)])).search(DAY, "A", "C", 1, [TransportType.TRAIN], 1, 30)
    ranked = RouteComparator().rank([option.route for option in routes])
    assert [option.rank for option in ranked] == [1, 2]
    assert ranked[0].score <= ranked[1].score


def test_route_engine_uses_nearby_city_when_destination_has_no_direct_route():
    routes = RouteEngine(Provider([seg("mn", "Москва", "Новороссийск", dt(8), dt(12), seats=3)])).search(DAY, "Москва", "Геленджик", 1, [TransportType.TRAIN], 0, 30)
    assert len(routes) == 1
    assert routes[0].route.segments[-1].destination_city.name == "Новороссийск"
