import os
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.resolver import YandexLocationResolver


def resolver_for_yandex_response(tmp_path, handler, api_key="startup-super-secret"):
    client = YandexRaspClient(
        YandexRaspConfiguration(api_key, enabled=True),
        httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.rasp.yandex-net.ru/v3.0/",
        ),
    )
    return YandexLocationResolver(
        directory_loader=client.stations_list,
        cache_path=tmp_path / "stations.json",
    )


def complete_directory():
    settlements = []
    for city, city_code, stations in (
        ("Ижевск", "c44", [("Ижевск", "s9602496")]),
        ("Пермь", "c50", [("Пермь-2", "s9602498")]),
        ("Мурманск", "c23", [("Мурманск", "s9602499")]),
        ("Москва", "c213", [("Москва Курская", "s2000001")]),
        ("Санкт-Петербург", "c2", [("Санкт-Петербург-Главн.", "s9602494")]),
        ("Кеза", "c999", [("Кеза", "s9990001")]),
        ("Сайгатка", "c998", [("Сайгатка", "s9980001")]),
        ("Яр", "c997", [("Яр", "s9970001")]),
    ):
        settlements.append({
            "title": city,
            "codes": {"yandex_code": city_code},
            "stations": [
                {"title": title, "code": code, "station_type": "railway_station", "transport_type": "train"}
                for title, code in stations
            ],
        })
    return {"countries": [{"title": "Россия", "regions": [{"title": "Тестовый регион", "settlements": settlements}]}]}


def test_complete_directory_cities_and_stations(tmp_path):
    resolver = YandexLocationResolver(directory_loader=complete_directory, cache_path=tmp_path / "stations.json")

    for query, city_code, station_code in (
        ("Ижевск", "c44", "s9602496"),
        ("Пермь", "c50", "s9602498"),
        ("Мурманск", "c23", "s9602499"),
        ("Москва", "c213", "s2000001"),
        ("Кеза", "c999", "s9990001"),
    ):
        codes = {match.code for match in resolver.resolve_all(query)}
        assert {city_code, station_code} <= codes
    assert resolver.resolve_all("совершенно-неизвестная-точка") == []
    assert (tmp_path / "stations.sqlite3").exists()


def test_suggest_endpoint_searches_built_station_index(tmp_path, monkeypatch):
    resolver = YandexLocationResolver(directory_loader=complete_directory, cache_path=tmp_path / "stations.json")
    monkeypatch.setattr("app.api.locations.yandex_location_resolver", resolver)

    client = TestClient(app)
    for query in ("Ижевск", "Пермь", "Мурманск", "Москва", "Санкт-Петербург", "Кеза", "Сайгатка", "Яр"):
        response = client.get("/api/v1/locations/suggest", params={"q": query, "limit": 20})
        assert response.status_code == 200
        assert response.json()["items"], query


@pytest.mark.skipif(not os.getenv("YANDEX_RASP_API_KEY"), reason="YANDEX_RASP_API_KEY is required for the official catalogue contract test")
def test_official_yandex_catalogue_contains_major_cities_and_small_stations(tmp_path):
    """Contract test against the complete, unmodified stations_list response."""
    client = YandexRaspClient(YandexRaspConfiguration.from_env())
    resolver = YandexLocationResolver(directory_loader=client.stations_list, cache_path=tmp_path / "stations.json")

    assert resolver.ensure_index_ready()
    assert resolver.stats()["locations"] > 10_000
    for query in ("Ижевск", "Пермь", "Мурманск", "Москва", "Санкт-Петербург", "Кеза", "Сайгатка", "Яр"):
        assert resolver.resolve_all(query), query


def test_concurrent_empty_index_has_single_sync(tmp_path):
    calls = 0
    gate = threading.Event()

    def loader():
        nonlocal calls
        calls += 1
        gate.wait(1)
        return complete_directory()

    resolver = YandexLocationResolver(directory_loader=loader, cache_path=tmp_path / "stations.json")
    threads = [threading.Thread(target=resolver.resolve_all, args=("Ижевск",)) for _ in range(8)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    gate.set()
    for thread in threads:
        thread.join()
    assert calls == 1


def test_first_startup_downloads_directory_when_cache_and_sqlite_are_absent(tmp_path, monkeypatch):
    requests = 0

    def successful_directory(request):
        nonlocal requests
        requests += 1
        assert request.url.path.endswith("/stations_list/")
        assert request.url.params["apikey"] == "configured-api-key"
        return httpx.Response(
            200,
            json=complete_directory(),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    # Reproduce a freshly booted host.  A monotonic value below the retry
    # cooldown must not be mistaken for a recent synchronization failure.
    monkeypatch.setattr("app.providers.yandex.resolver.time.monotonic", lambda: 1.0)
    resolver = resolver_for_yandex_response(
        tmp_path,
        successful_directory,
        api_key="configured-api-key",
    )

    assert not (tmp_path / "stations.json").exists()
    assert not (tmp_path / "stations.sqlite3").exists()
    assert resolver.warm_from_existing_cache()["locations"] == 0

    assert resolver.ensure_index_ready() is True
    assert requests == 1
    assert resolver.stats()["locations"] > 0
    assert resolver.startup_diagnostics()["last_source"] == "remote"


def test_failed_sync_observes_cooldown(tmp_path):
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream unavailable")

    resolver = YandexLocationResolver(directory_loader=loader, cache_path=tmp_path / "stations.json")
    assert resolver.resolve_all("Ижевск") == []  # absent from emergency defaults
    assert resolver.resolve_all("Пермь") == []
    assert calls == 1


@pytest.mark.parametrize("status", [401, 403])
def test_startup_diagnostics_identify_invalid_api_key_without_exposing_it(tmp_path, status):
    secret = "startup-super-secret"
    resolver = resolver_for_yandex_response(
        tmp_path,
        lambda request: httpx.Response(status, json={"error": secret}),
        secret,
    )

    assert resolver.ensure_index_ready() is False
    diagnostics = resolver.startup_diagnostics()
    assert diagnostics["exception_class"] == "YandexRaspAuthError"
    assert diagnostics["http_status"] == status
    assert diagnostics["endpoint"] == "stations_list"
    assert diagnostics["api_key_configured"] is True
    assert secret not in str(diagnostics)


def test_startup_diagnostics_identify_timeout(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("request timed out", request=request)

    resolver = resolver_for_yandex_response(tmp_path, timeout)
    assert resolver.ensure_index_ready() is False
    assert resolver.startup_diagnostics()["exception_class"] == "YandexRaspTimeoutError"


def test_startup_diagnostics_identify_malformed_response(tmp_path):
    resolver = resolver_for_yandex_response(
        tmp_path,
        lambda request: httpx.Response(
            200,
            text="not-json startup-super-secret",
            headers={"content-type": "application/json"},
        ),
    )

    assert resolver.ensure_index_ready() is False
    diagnostics = resolver.startup_diagnostics()
    assert diagnostics["exception_class"] == "YandexRaspInvalidResponseError"
    assert diagnostics["content_type"] == "application/json"
    assert "startup-super-secret" not in str(diagnostics)


def test_startup_diagnostics_propagate_safe_html_response_details(tmp_path, caplog):
    secret = "startup-super-secret"
    resolver = resolver_for_yandex_response(
        tmp_path,
        lambda request: httpx.Response(
            200,
            text=f"<html>{secret} apikey=another-secret Authorization: Bearer token-secret</html>",
            headers={"content-type": "text/html", "server": "Yandex-gateway"},
            request=request,
        ),
        secret,
    )

    assert resolver.ensure_index_ready() is False
    diagnostics = resolver.startup_diagnostics()
    assert diagnostics["response_final_host"] == "api.rasp.yandex-net.ru"
    assert diagnostics["response_final_path"] == "/v3.0/stations_list/"
    assert diagnostics["server_header"] == "Yandex-gateway"
    assert diagnostics["body_preview"].startswith("<html>***redacted***")
    for credential in (secret, "another-secret", "token-secret"):
        assert credential not in str(diagnostics)
        assert credential not in caplog.text


def test_corrupt_index_can_be_rebuilt(tmp_path):
    path = tmp_path / "stations.json"
    resolver = YandexLocationResolver(directory_loader=complete_directory, cache_path=path)
    assert resolver.resolve_all("Ижевск")
    resolver._stations_repository.path.write_bytes(b"not sqlite")
    resolver._stations_repository._initialized = False
    resolver._cache.clear()

    try:
        resolver.resolve_all("Пермь")
    except sqlite3.DatabaseError as exc:
        resolver.mark_index_failed(exc)
    assert {match.code for match in resolver.resolve_all("Пермь")} >= {"c50", "s9602498"}
