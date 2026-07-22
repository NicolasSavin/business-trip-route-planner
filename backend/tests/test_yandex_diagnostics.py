from datetime import date
from pathlib import Path

import httpx
import pytest

from app.domain import TransportType
from app.providers.yandex import YandexLocationResolver, YandexRaspClient, YandexRaspConfiguration, YandexRaspProvider
from app.providers.yandex.diagnostics import DIAGNOSTICS_DIR

DAY = date(2026, 8, 10)


def client_for_response(response: httpx.Response) -> YandexRaspClient:
    def handler(request):
        return response
    return YandexRaspClient(YandexRaspConfiguration("secret", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex.net/v3.0"))


def run_provider(client: YandexRaspClient):
    provider = YandexRaspProvider(YandexRaspConfiguration("secret", enabled=True), client=client, resolver=YandexLocationResolver())
    with pytest.raises(Exception):
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    return provider


def assert_artifacts(details: dict):
    paths = details["artifact_paths"]
    assert Path(paths["request"]).exists()
    assert Path(paths["response_json"]).exists()
    assert Path(paths["response_body"]).exists()
    assert Path(paths["headers"]).exists()
    assert Path(paths["exception"]).exists()


def test_yandex_diagnostics_valid_json_empty_body_shape(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    provider = run_provider(client_for_response(httpx.Response(200, json={"segments": []}, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["pair_errors"] == []
    assert (DIAGNOSTICS_DIR / "yandex_response.bin").read_bytes() == b'{"segments":[]}'


def test_yandex_diagnostics_invalid_json_includes_traceback_and_artifacts(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    provider = run_provider(client_for_response(httpx.Response(200, text="not json", headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["status_code"] == 200
    assert details["raw_body_preview"] == "not json"
    assert details["parsed_json_preview"] is None
    assert "JSONDecodeError" in details["traceback"]
    assert details["request_params"]["apikey"] == "***redacted***"
    assert_artifacts(details)


def test_yandex_diagnostics_html_response(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    provider = run_provider(client_for_response(httpx.Response(200, text="<html>bad gateway</html>", headers={"content-type": "text/html"})))
    details = provider.last_error_payload["details"]
    assert details["content_type"] == "text/html"
    assert details["raw_body_preview"] == "<html>bad gateway</html>"
    assert details["exception_type"] == "JSONDecodeError"


def test_yandex_diagnostics_empty_body(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    provider = run_provider(client_for_response(httpx.Response(200, content=b"", headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["raw_body_preview"] == ""
    assert "JSONDecodeError" in details["traceback"]


def test_yandex_diagnostics_unexpected_json_structure(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    provider = run_provider(client_for_response(httpx.Response(200, json={"unexpected": []}, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["parsed_json_preview"] == '{"unexpected": []}'
    assert details["exception_type"] is None
    assert details["status_code"] == 200
    assert_artifacts(details)


def test_yandex_diagnostics_truncates_returned_body_only(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    body = "x" * (1024 * 1024 + 10)
    provider = run_provider(client_for_response(httpx.Response(200, text=body, headers={"content-type": "text/plain"})))
    details = provider.last_error_payload["details"]
    assert len(details["raw_body_preview"]) == 4000
    assert (DIAGNOSTICS_DIR / "yandex_response.bin").read_bytes() == body.encode()


def test_route_search_api_exposes_yandex_invalid_provider_response_details(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    from fastapi.testclient import TestClient

    from app.api import routes as routes_api
    from app.main import app
    from app.providers.unified.models import ProviderCapabilities, ProviderPriority
    from app.providers.unified.provider import UnifiedTransportProvider
    from app.providers.unified.registry import ProviderRegistry
    from app.services.route_search import RouteSearchService

    provider = YandexRaspProvider(
        YandexRaspConfiguration("secret", enabled=True),
        client=client_for_response(httpx.Response(200, json={"unexpected": []}, headers={"content-type": "application/json", "x-debug": "yes"})),
        resolver=YandexLocationResolver(),
    )
    registry = ProviderRegistry()
    registry.register(
        provider,
        id="yandex_rasp",
        name="Яндекс Расписания",
        priority=ProviderPriority.HIGH,
        enabled=True,
        capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN], supports_schedule=True),
    )
    monkeypatch.setattr(routes_api, "service", RouteSearchService(UnifiedTransportProvider(registry)))

    response = TestClient(app).post(
        "/api/v1/routes/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "departure_date": DAY.isoformat(),
            "passengers": 1,
            "allowed_transport": ["train"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    error = body["provider_errors"]["yandex_rasp"]
    assert error["code"] == "invalid_provider_response"
    details = error["details"]
    for key in (
        "request_url",
        "request_params",
        "status_code",
        "response_headers",
        "content_type",
        "raw_body_size_bytes",
        "parsed_json_preview",
        "exception_type",
        "artifact_paths",
    ):
        assert key in details
    assert details["request_params"]["apikey"] == "***redacted***"
    assert details["status_code"] == 200
    assert "x-debug" not in details["response_headers"]
    assert details["parsed_json_preview"] == '{"unexpected": []}'
    expected_client_diagnostics = dict(provider.client.last_response_diagnostics)
    assert {key: details[key] for key in expected_client_diagnostics} == expected_client_diagnostics
    assert_artifacts(details)


def test_yandex_diagnostics_binary_body_has_no_string_preview(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    content = b"\x00\x01\x02not-text" * 100
    provider = run_provider(client_for_response(httpx.Response(200, content=content, headers={"content-type": "application/octet-stream"})))
    details = provider.last_error_payload["details"]
    assert details["raw_body_preview"] is None
    assert details["raw_body_binary"] is True
    assert details["raw_body_size_bytes"] == len(content)
    assert "raw_body" not in details


def test_yandex_diagnostics_gzip_and_br_body_have_no_string_preview(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    for encoding in ("gzip", "br"):
        provider = run_provider(client_for_response(httpx.Response(200, content=b"compressed-payload", headers={"content-type": "application/json", "content-encoding": encoding})))
        details = provider.last_error_payload["details"]
        assert details["content_encoding"] == encoding
        assert details["raw_body_preview"] is None
        assert details["raw_body_binary"] is True


def test_yandex_diagnostics_preview_and_total_details_are_capped(monkeypatch):
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_VERBOSE", "true")
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_PREVIEW_CHARS", "4000")
    monkeypatch.setenv("YANDEX_DIAGNOSTICS_MAX_DETAILS_BYTES", "32768")
    payload = {"unexpected": ["x" * 1000 for _ in range(100)]}
    provider = run_provider(client_for_response(httpx.Response(200, json=payload, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert len(details["raw_body_preview"]) <= 4000
    assert len(details["parsed_json_preview"]) <= 10000
    assert len(__import__("json").dumps(details, ensure_ascii=False).encode("utf-8")) <= 32768
    assert "raw_body" not in details


def test_yandex_diagnostics_default_compact_response(monkeypatch):
    monkeypatch.delenv("YANDEX_DIAGNOSTICS_VERBOSE", raising=False)
    provider = run_provider(client_for_response(httpx.Response(200, json={"unexpected": []}, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert set(details) == {"status_code", "content_type", "content_encoding", "response_keys", "raw_body_size_bytes", "artifact_paths"}
    assert details["status_code"] == 200
    assert details["response_keys"] == ["unexpected"]


def test_route_search_api_compact_provider_errors_does_not_502_for_large_body(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes as routes_api
    from app.main import app
    from app.providers.unified.models import ProviderCapabilities, ProviderPriority
    from app.providers.unified.provider import UnifiedTransportProvider
    from app.providers.unified.registry import ProviderRegistry
    from app.services.route_search import RouteSearchService

    monkeypatch.delenv("YANDEX_DIAGNOSTICS_VERBOSE", raising=False)
    body = "x" * (1024 * 1024 * 2)
    provider = YandexRaspProvider(
        YandexRaspConfiguration("secret", enabled=True),
        client=client_for_response(httpx.Response(200, text=body, headers={"content-type": "text/plain"})),
        resolver=YandexLocationResolver(),
    )
    registry = ProviderRegistry()
    registry.register(provider, id="yandex_rasp", name="Яндекс Расписания", priority=ProviderPriority.HIGH, enabled=True, capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN], supports_schedule=True))
    monkeypatch.setattr(routes_api, "service", RouteSearchService(UnifiedTransportProvider(registry)))

    response = TestClient(app).post("/api/v1/routes/search", json={"origin": "Москва", "destination": "Санкт-Петербург", "departure_date": DAY.isoformat(), "passengers": 1, "allowed_transport": ["train"]})

    assert response.status_code == 200
    error = response.json()["provider_errors"]["yandex_rasp"]
    assert error["code"] == "invalid_provider_response"
    assert "raw_body" not in __import__("json").dumps(error, ensure_ascii=False)
    assert len(response.content) < 32768
