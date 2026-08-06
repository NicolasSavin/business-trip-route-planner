import asyncio
import ssl
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import rzd_debug
from app.main import app
from app.providers.rzd_availability.exceptions import RZDAvailabilityError


@dataclass
class FakeSearchResult:
    raw: dict[str, str]
    trains: list[str]


class SuccessfulClient:
    async def search(self, *args, **kwargs):
        return FakeSearchResult(raw={"provider": "rzd"}, trains=["008С"])


class FailingClient:
    async def search(self, *args, **kwargs):
        raise RZDAvailabilityError("provider unavailable")


class DiagnosticClient:
    async def search(self, *args, stop_after_stage=None, **kwargs):
        return {
            "stage": stop_after_stage,
            "result": {"origin_station": {"code": "2000000", "name": "Москва"}},
            "timings": {"sdk_init": 0.1, "origin_station_lookup": 2.5},
        }


def test_application_import_creates_fastapi_app():
    assert isinstance(app, FastAPI)


def test_debug_search_success(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", SuccessfulClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
            "passengers": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["raw"] == {"provider": "rzd"}
    assert response.json()["normalized"]["trains"] == ["008С"]


def test_debug_search_provider_failure(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", FailingClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "code": "rzd_debug_failed",
        "error_type": "RZDAvailabilityError",
        "message": "provider unavailable",
        "details": {
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    }


def test_debug_search_requires_codes_when_lookup_is_skipped(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
            "skip_station_lookup": True,
        },
    )

    assert response.status_code == 422


class StationCodeClient:
    async def resolve_station_code(self, *args, **kwargs):
        from app.providers.rzd_availability.station_resolver import (
            StationCodeResolution,
        )
        from app.providers.rzd_availability.models import RZDStation

        return StationCodeResolution(RZDStation("2000000", "Москва"), "cache")


def test_debug_station_code_reports_resolution_source(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", StationCodeClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/station-code",
        json={"query": "Москва", "provider_code": "c213"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "resolved": True,
        "rzd_code": "2000000",
        "source": "cache",
        "sdk_lookup_used": False,
    }


def test_debug_search_stop_after_stage_returns_intermediate_result(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", DiagnosticClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
            "stop_after_stage": "origin_station_lookup",
        },
    )

    assert response.status_code == 200
    assert response.json()["stage"] == "origin_station_lookup"
    assert response.json()["result"]["origin_station"]["code"] == "2000000"
    assert "origin_station_lookup" in response.json()["timings"]


def test_debug_search_is_hidden_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(rzd_debug, "RZDClient", SuccessfulClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def _probe_payload() -> rzd_debug.RZDHTTPProbeRequest:
    return rzd_debug.RZDHTTPProbeRequest(
        origin_code="2000000",
        destination_code="2004000",
        date="2026-08-10",
        passengers=2,
    )


def test_http_probe_base_and_pricing_success(monkeypatch):
    monkeypatch.delenv("RZD_HTTP_PROBE_VERIFY_SSL", raising=False)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(
                200, text="base response", headers={"x-secret": "hidden"}
            )
        return httpx.Response(
            200,
            json={"trains": []},
            headers={"content-type": "application/json", "set-cookie": "sid=secret"},
        )

    result = asyncio.run(
        rzd_debug.run_http_probes(
            _probe_payload(), transport=httpx.MockTransport(handler)
        )
    )

    assert result["base_probe"]["status"] == "ok"
    assert result["base_probe"]["status_code"] == 200
    assert result["base_probe"]["body_sample"] == "base response"
    assert result["pricing_probe"]["status"] == "ok"
    assert result["pricing_probe"]["body_sample"] == '{"trains":[]}'
    assert "headers" not in result["pricing_probe"]
    assert "cookies" not in result["pricing_probe"]
    pricing_request = requests[1]
    assert pricing_request.url.params["origin"] == "2000000"
    assert pricing_request.url.params["destination"] == "2004000"
    assert pricing_request.url.params["departureDate"] == "2026-08-10T00:00:00"
    assert pricing_request.url.params["adultPassengersQuantity"] == "2"
    assert pricing_request.headers["user-agent"] == "Mozilla/5.0"


@pytest.mark.parametrize(
    ("exception", "error_type"),
    [
        (httpx.ConnectTimeout("connect timed out"), "ConnectTimeout"),
        (httpx.ReadTimeout("read timed out"), "ReadTimeout"),
    ],
)
def test_http_probe_reports_timeout_types(exception, error_type):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200)
        raise exception

    result = asyncio.run(
        rzd_debug.run_http_probes(
            _probe_payload(), transport=httpx.MockTransport(handler)
        )
    )

    assert result["pricing_probe"]["status"] == "timeout"
    assert result["pricing_probe"]["status_code"] is None
    assert result["pricing_probe"]["error_type"] == error_type


def test_http_probe_reports_connect_and_tls_errors():
    for exception, expected_status in (
        (httpx.ConnectError("connection refused"), "connect_error"),
        (httpx.ConnectError("TLS failed", request=None), "tls_error"),
        (httpx.ConnectError("handshake", request=None), "tls_error"),
    ):
        if expected_status == "tls_error" and str(exception) == "handshake":
            exception.__cause__ = ssl.SSLError("certificate verify failed")

        def handler(request: httpx.Request) -> httpx.Response:
            raise exception

        result = asyncio.run(
            rzd_debug.run_http_probes(
                _probe_payload(), transport=httpx.MockTransport(handler)
            )
        )
        assert result["base_probe"]["status"] == expected_status
        assert result["base_probe"]["error_type"] == "ConnectError"


@pytest.mark.parametrize("status_code", [403, 429, 500])
def test_http_probe_reports_http_errors(status_code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="blocked")

    result = asyncio.run(
        rzd_debug.run_http_probes(
            _probe_payload(), transport=httpx.MockTransport(handler)
        )
    )

    assert result["base_probe"]["status"] == "http_error"
    assert result["base_probe"]["status_code"] == status_code
    assert result["base_probe"]["error_type"] == "HTTPStatusError"


def test_http_probe_is_hidden_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    response = TestClient(app).post(
        "/api/v1/debug/rzd/http-probe",
        json={
            "origin_code": "2000000",
            "destination_code": "2004000",
            "date": "2026-08-10",
            "passengers": 2,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
