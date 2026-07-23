from datetime import datetime, timezone
import httpx
from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.models.routes import RouteSearchRequest, SeatPreferencesRequest
from app.providers.tutu_playwright import TutuPlaywrightAvailabilityClient
from app.availability.journey import AvailabilityStatus


def segment(seats=None):
    m=City("Москва"); p=City("Санкт-Петербург")
    return TransportSegment(id="s1", provider="yandex", carrier=Carrier("rzd","РЖД"), transport_type=TransportType.TRAIN, transport_class=TransportClass.COUPE, vehicle_number="008С", origin_city=m, origin_station=Station("1","Москва",m), destination_city=p, destination_station=Station("2","СПб",p), departure_datetime=datetime(2026,8,10,20,6,tzinfo=timezone.utc), arrival_datetime=datetime(2026,8,11,4,0,tzinfo=timezone.utc), duration_minutes=474, available_seats=seats)

def request(strict=True):
    return RouteSearchRequest(origin="Москва", destination="Санкт-Петербург", departure_date="2026-08-10", passengers=2, strict_availability=strict, allowed_transport=["train"], seat_preferences=SeatPreferencesRequest(preferred_classes=["coupe"], berth_preference="lower_only", require_same_carriage=True, require_same_compartment=True, maximum_compartments=1))

def test_provider_unavailable_fallback(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    def boom(*args, **kwargs): raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.Client, "post", boom)
    res=c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.UNCONFIRMED
    assert res.metadata["provider_error"]["code"] == "availability_enrichment_failed"

def test_confirmed_mapping(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"status":"confirmed","matched_train":True,"available_seats":4,"selected_places":["1","3"],"selected_carriages":["5"],"selected_compartments":["1"],"message":"ok"})
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    res=c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.CONFIRMED
    assert res.selected_carriages == ("5",) and res.selected_compartments == ("1",)


def test_provider_error_response_is_returned_as_safe_unconfirmed_result(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"status":"provider_error", "message":"Location suggestion not found: Рязань", "error_type":"TutuDiagnosticError", "diagnostics":{"selected_inputs":[], "popup_candidates":[], "screenshots":["a"]}})
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    res=c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.UNCONFIRMED
    assert res.metadata["provider_error"]["message"] == "Location suggestion not found: Рязань"
    assert res.metadata["provider_error"]["error_type"] == "TutuDiagnosticError"
    assert "X-Service-Token" not in str(res.metadata)
