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


def test_yandex_diagnostics_valid_json_empty_body_shape():
    provider = run_provider(client_for_response(httpx.Response(200, json={"segments": []}, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["pair_errors"] == []
    assert (DIAGNOSTICS_DIR / "yandex_response.txt").read_text(encoding="utf-8") == '{"segments":[]}'


def test_yandex_diagnostics_invalid_json_includes_traceback_and_artifacts():
    provider = run_provider(client_for_response(httpx.Response(200, text="not json", headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["status_code"] == 200
    assert details["raw_body"] == "not json"
    assert details["json"] is None
    assert "JSONDecodeError" in details["traceback"]
    assert details["request_params"]["apikey"] == "***redacted***"
    assert_artifacts(details)


def test_yandex_diagnostics_html_response():
    provider = run_provider(client_for_response(httpx.Response(200, text="<html>bad gateway</html>", headers={"content-type": "text/html"})))
    details = provider.last_error_payload["details"]
    assert details["content_type"] == "text/html"
    assert details["raw_body"] == "<html>bad gateway</html>"
    assert "JSONDecodeError" in details["exception"]


def test_yandex_diagnostics_empty_body():
    provider = run_provider(client_for_response(httpx.Response(200, content=b"", headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["raw_body"] == ""
    assert "JSONDecodeError" in details["traceback"]


def test_yandex_diagnostics_unexpected_json_structure():
    provider = run_provider(client_for_response(httpx.Response(200, json={"unexpected": []}, headers={"content-type": "application/json"})))
    details = provider.last_error_payload["details"]
    assert details["json"] == {"unexpected": []}
    assert details["exception"] is None
    assert details["status_code"] == 200
    assert_artifacts(details)


def test_yandex_diagnostics_truncates_returned_body_only():
    body = "x" * (1024 * 1024 + 10)
    provider = run_provider(client_for_response(httpx.Response(200, text=body, headers={"content-type": "text/plain"})))
    details = provider.last_error_payload["details"]
    assert len(details["raw_body"].encode("utf-8")) < len(body.encode("utf-8"))
    assert (DIAGNOSTICS_DIR / "yandex_response.txt").read_text(encoding="utf-8") == body
