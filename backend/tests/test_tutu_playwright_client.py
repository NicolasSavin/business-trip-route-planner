import pytest
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

@pytest.mark.asyncio
async def test_provider_unavailable_fallback(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    def boom(*args, **kwargs): raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    res=await c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.UNCONFIRMED
    assert res.metadata["provider_error"]["code"] == "availability_enrichment_failed"

@pytest.mark.asyncio
async def test_confirmed_mapping(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    async def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"status":"confirmed","matched_train":True,"available_seats":4,"selected_places":["1","3"],"selected_carriages":["5"],"selected_compartments":["1"],"message":"ok"})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res=await c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.CONFIRMED
    assert res.selected_carriages == ("5",) and res.selected_compartments == ("1",)


@pytest.mark.asyncio
async def test_provider_error_response_is_returned_as_safe_unconfirmed_result(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)
    async def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"status":"provider_error", "message":"Location suggestion not found: Рязань", "error_type":"TutuDiagnosticError", "diagnostics":{"selected_inputs":[], "popup_candidates":[], "screenshots":["a"]}})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res=await c.check_segment(segment(), request())
    assert res.status == AvailabilityStatus.UNCONFIRMED
    assert res.metadata["provider_error"]["message"] == "Location suggestion not found: Рязань"
    assert res.metadata["provider_error"]["error_type"] == "TutuDiagnosticError"
    assert "X-Service-Token" not in str(res.metadata)


@pytest.mark.asyncio
async def test_diagnostic_error_response_arrives_with_aligned_read_timeout(monkeypatch):
    observed = {}
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True, timeout=40)

    original_init = httpx.AsyncClient.__init__

    def capture_init(self, *args, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        original_init(self, *args, **kwargs)

    async def fake_post(*args, **kwargs):
        return httpx.Response(200, json={
            "status":"provider_error",
            "message":"Location suggestion not found: Рязань",
            "error_type":"TutuDiagnosticError",
            "diagnostics":{
                "station_steps":[{"requested_city":"Рязань", "failure_reason":"matching_candidate_not_found"}],
                "origin_station_selection":{"requested_city":"Рязань"},
                "destination_station_selection":{},
                "popup_candidates":{"origin":[{"text":"Тула"}]},
                "autocomplete_discovery":{"origin":{"options":[{"text":"Тула"}]}},
                "selected_inputs":{"origin":{"role":"textbox"}},
                "screenshots":["origin_after_waiting.png"],
                "html_artifacts":["origin_after_waiting.html"],
                "failure_reason":"matching_candidate_not_found",
            },
        })

    monkeypatch.setattr(httpx.AsyncClient, "__init__", capture_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    res=await c.check_segment(segment(), request())

    assert observed["timeout"].connect == 5
    assert observed["timeout"].read == 40
    assert observed["timeout"].write == 10
    assert observed["timeout"].pool == 5
    assert res.metadata["provider_error"]["error_type"] == "TutuDiagnosticError"
    assert res.metadata["provider_error"]["error_type"] != "ReadTimeout"
    details = res.metadata["provider_error"]["details"]
    assert details["station_steps"][0]["requested_city"] == "Рязань"
    assert details["origin_station_selection"]["requested_city"] == "Рязань"
    assert details["failure_reason"] == "matching_candidate_not_found"


@pytest.mark.asyncio
async def test_read_timeout_marks_missing_diagnostic_response(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True, timeout=40)

    async def fake_post(*args, **kwargs):
        raise httpx.ReadTimeout("read timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res=await c.check_segment(segment(), request())

    error = res.metadata["provider_error"]
    assert error["error_type"] == "ReadTimeout"
    details = error["details"]
    assert details["diagnostic_response_received"] is False
    assert details["timeout_stage"] == "backend_http_read"
    assert details["configured_read_timeout_seconds"] == 40
    assert details["service_url"] == "http://tutu/api/v1/availability/check"
    assert "station_steps" not in details
    assert "selected_inputs" not in details
    assert "popup_candidates" not in details


@pytest.mark.asyncio
async def test_station_steps_are_preserved_in_provider_error_details(monkeypatch):
    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)

    async def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"status":"provider_error", "message":"bad station", "error_type":"TutuDiagnosticError", "diagnostics":{"station_steps":[{"field_name":"origin", "failure_reason":"matching_candidate_not_found"}]}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    res=await c.check_segment(segment(), request())

    assert res.metadata["provider_error"]["details"]["station_steps"] == [{"field_name":"origin", "failure_reason":"matching_candidate_not_found"}]


def test_default_enrichment_budget_exceeds_backend_http_timeout():
    import app.services.multimodal_journey_planner as planner_module

    c=TutuPlaywrightAvailabilityClient(base_url="http://tutu", enabled=True)

    assert planner_module.TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS > c.timeout
