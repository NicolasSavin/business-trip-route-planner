from datetime import date, datetime

from fastapi.testclient import TestClient

from app.api import routes as routes_api
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import Carrier, City, Station, TransportClass, TransportSegment
from app.main import app
from app.models.routes import RouteAvailability, RouteSearchRequest, SegmentAvailability, TransportType
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


def test_search_request_keeps_backward_compatibility_without_availability_fields():
    request = RouteSearchRequest.model_validate({
        "origin": "Москва",
        "destination": "Екатеринбург",
        "departure_date": date(2026, 8, 10),
        "passengers": 2,
        "allowed_transport": [TransportType.TRAIN, TransportType.BUS],
    })
    routes = RouteSearchService(MockTransportProvider()).search(request)
    assert routes
    assert routes[0].availability is not None


def test_route_search_serializes_availability_block():
    route = RouteSearchService(MockTransportProvider()).search(make_request())[0]
    payload = route.model_dump()
    assert payload["availability"]["is_available"] is True
    assert payload["availability"]["requested_passengers"] == 2
    assert payload["availability"]["segments"]


DAY = date(2026, 8, 10)


def dt(hour):
    return datetime(2026, 8, 10, hour)


def segment(id, origin, destination, dep, arr, seats=None):
    origin_city = City(origin)
    destination_city = City(destination)
    return TransportSegment(
        id=id,
        provider="yandex_rasp",
        carrier=Carrier("carrier", "Carrier"),
        transport_type=TransportType.TRAIN,
        transport_class=TransportClass.COUPE,
        vehicle_number=id,
        origin_city=origin_city,
        origin_station=Station(f"{origin}-station", f"{origin} station", origin_city),
        destination_city=destination_city,
        destination_station=Station(f"{destination}-station", f"{destination} station", destination_city),
        departure_datetime=dep,
        arrival_datetime=arr,
        duration_minutes=int((arr - dep).total_seconds() // 60),
        available_seats=seats,
        metadata={"availability_unknown": True, "source": "Яндекс Расписания"},
    )


class Provider:
    def __init__(self, segments):
        self.segments = segments
        self.last_diagnostics = {}

    def get_segments(self, *_args, **_kwargs):
        return self.segments


class TutuClient:
    def __init__(self, results):
        self.results = results

    def available(self):
        return True

    async def check_segment(self, segment, request):
        return self.results[segment.id]


def post_search_with_service(monkeypatch, service):
    monkeypatch.setattr(routes_api, "service", service)
    return TestClient(app).post(
        "/api/v1/routes/search",
        json={
            "origin": "A",
            "destination": "C",
            "departure_date": DAY.isoformat(),
            "passengers": 2,
            "allowed_transport": ["train"],
            "max_transfers": 1,
            "strict_availability": False,
        },
    )


def test_route_availability_allows_unknown_and_api_serializes_null(monkeypatch):
    model = RouteAvailability(
        is_available=None,
        requested_passengers=2,
        minimum_available_seats=None,
        checked_at=dt(8),
        segment_results=[
            SegmentAvailability(
                segment_id="ac",
                is_available=None,
                available_seats=None,
                requested_passengers=2,
                transport_class=None,
                checked_at=dt(8),
                source="tutu_playwright",
            )
        ],
    )
    assert model.model_dump()["is_available"] is None

    service = RouteSearchService(Provider([segment("ac", "A", "C", dt(8), dt(12))]))
    service.planner.tutu_playwright = TutuClient({
        "ac": SegmentAvailabilityResult(
            segment_id="ac",
            provider="tutu_playwright",
            status=AvailabilityStatus.UNCONFIRMED,
            schedule_confirmed=True,
            seats_confirmed=False,
            passengers_supported=False,
            available_places_count=None,
            seat_preferences_status=AvailabilityStatus.UNKNOWN,
            reasons=("Наличие мест не подтверждено",),
        )
    })

    response = post_search_with_service(monkeypatch, service)

    assert response.status_code == 200
    body = response.json()
    route = body["routes"][0]
    assert route["availability"]["is_available"] is None
    assert route["availability"]["segment_results"][0]["is_available"] is None
    assert route["is_available_for_group"] is None


def test_tutu_provider_error_keeps_partial_route_with_unknown_availability(monkeypatch):
    service = RouteSearchService(Provider([
        segment("ab", "A", "B", dt(8), dt(9), seats=2),
        segment("bc", "B", "C", dt(10), dt(12)),
    ]))
    service.planner.tutu_playwright = TutuClient({
        "ab": SegmentAvailabilityResult(
            segment_id="ab",
            provider="tutu_playwright",
            status=AvailabilityStatus.CONFIRMED,
            schedule_confirmed=True,
            seats_confirmed=True,
            passengers_supported=True,
            available_places_count=2,
            seat_preferences_status=AvailabilityStatus.CONFIRMED,
        ),
        "bc": SegmentAvailabilityResult(
            segment_id="bc",
            provider="tutu_playwright",
            status=AvailabilityStatus.UNCONFIRMED,
            schedule_confirmed=True,
            seats_confirmed=False,
            passengers_supported=False,
            available_places_count=None,
            seat_preferences_status=AvailabilityStatus.UNKNOWN,
            reasons=("Расписание найдено, проверка мест через Туту не выполнена",),
            warnings=("Расписание найдено, проверка мест через Туту не выполнена",),
            metadata={"provider_error": {"code": "availability_enrichment_failed", "message": "Tutu failed", "error_type": "ProviderError", "details": {"segment_id": "bc"}}},
        ),
    })

    response = post_search_with_service(monkeypatch, service)

    assert response.status_code == 200
    body = response.json()
    assert body["partially_confirmed_routes"]
    route = body["partially_confirmed_routes"][0]
    assert route["availability"]["is_available"] is None
    assert route["is_available_for_group"] is None
    assert "tutu_playwright" in body["provider_errors"]
    assert body["provider_errors"]["tutu_playwright"]["errors"][0]["details"]["segment_id"] == "bc"


def test_openapi_marks_route_availability_as_nullable():
    schema = app.openapi()
    availability_schema = schema["components"]["schemas"]["RouteAvailability-Output"]["properties"]["is_available"]
    option_schema = schema["components"]["schemas"]["RouteOption-Output"]["properties"]["is_available_for_group"]
    assert {item.get("type") for item in availability_schema["anyOf"]} == {"boolean", "null"}
    assert {item.get("type") for item in option_schema["anyOf"]} == {"boolean", "null"}
