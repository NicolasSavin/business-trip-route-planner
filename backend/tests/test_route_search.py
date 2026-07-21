from datetime import date
from app.models.routes import RouteSearchRequest, TransportType
from app.providers.mock import MockTransportProvider
from app.services.route_search import RouteSearchService


def make_request(**overrides):
    data = {
        "origin": "Москва",
        "destination": "Екатеринбург",
        "departure_date": date(2026, 8, 10),
        "passengers": 2,
        "allowed_transport": [TransportType.TRAIN, TransportType.BUS],
        "max_transfers": 2,
        "minimum_transfer_minutes": 30,
    }
    data.update(overrides)
    return RouteSearchRequest(**data)


def test_finds_direct_and_transfer_routes_sorted_by_engine_score():
    routes = RouteSearchService(MockTransportProvider()).search(make_request())
    assert routes[0].transfers_count == 0
    assert {route.transfer_city for route in routes if route.transfer_city} >= {"Казань", "Самара"}


def test_respects_max_transfers_zero():
    routes = RouteSearchService(MockTransportProvider()).search(make_request(max_transfers=0))
    assert routes
    assert all(route.transfers_count == 0 for route in routes)
    assert routes[0].segments[0].number == "Поезд 016М"


def test_filters_route_unavailable_when_one_segment_lacks_seats():
    routes = RouteSearchService(MockTransportProvider()).search(make_request(passengers=5))
    assert "Нижний Новгород" not in {route.transfer_city for route in routes if route.transfer_city}
    assert all(route.is_available_for_group for route in routes)


def test_filters_by_transport_type():
    routes = RouteSearchService(MockTransportProvider()).search(make_request(allowed_transport=[TransportType.TRAIN]))
    assert routes
    assert all(segment.transport_type == TransportType.TRAIN for route in routes for segment in route.segments)


def test_respects_minimum_transfer_minutes():
    routes = RouteSearchService(MockTransportProvider()).search(make_request(minimum_transfer_minutes=181))
    assert "Нижний Новгород" not in {route.transfer_city for route in routes if route.transfer_city}
