import time

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.resolver import YandexLocationResolver


def _directory(city="Ижевск", code="c44"):
    return {"countries": [{"title": "Россия", "regions": [{"title": "Регион", "settlements": [{
        "title": city,
        "codes": {"yandex_code": code},
        "stations": [{"title": city, "code": "s44", "station_type": "railway_station", "transport_type": "train"}],
    }]}]}]}


def _wait(thread):
    assert thread is not None
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_no_cache_rate_limit_keeps_offline_catalogue_usable(tmp_path):
    client = YandexRaspClient(
        YandexRaspConfiguration("do-not-leak", enabled=True),
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, json={"error": "limited"})),
            base_url="https://api.rasp.yandex-net.ru/v3.0/",
        ),
    )
    resolver = YandexLocationResolver(client.stations_list, cache_path=tmp_path / "stations.json")

    resolver.initialize_for_startup()
    assert resolver.resolve("Москва").code == "c213"
    assert resolver.resolve("Санкт-Петербург").code == "c2"
    _wait(resolver.startup_refresh_background())

    diagnostics = resolver.startup_diagnostics()
    assert diagnostics["catalogue_status"] == "degraded"
    assert diagnostics["http_status"] == 429
    assert diagnostics["retry_after_seconds"] > 0
    assert "do-not-leak" not in str(diagnostics)


def test_no_cache_timeout_keeps_startup_usable(tmp_path):
    calls = 0

    def timeout():
        nonlocal calls
        calls += 1
        raise TimeoutError("temporarily unavailable")

    resolver = YandexLocationResolver(timeout, cache_path=tmp_path / "stations.json")
    assert resolver.initialize_for_startup()["locations"] > 0
    _wait(resolver.startup_refresh_background())
    assert resolver.startup_diagnostics()["catalogue_status"] == "degraded"
    assert calls == 1


def test_existing_sqlite_needs_no_startup_network_request(tmp_path):
    first = YandexLocationResolver(lambda: _directory(), cache_path=tmp_path / "stations.json")
    assert first.ensure_index_ready()
    calls = 0

    def forbidden():
        nonlocal calls
        calls += 1
        raise AssertionError("network called during startup")

    restarted = YandexLocationResolver(forbidden, cache_path=tmp_path / "stations.json")
    assert restarted.initialize_for_startup()["locations"] > 0
    assert calls == 0


def test_background_refresh_replaces_degraded_local_catalogue(tmp_path):
    resolver = YandexLocationResolver(lambda: _directory(), cache_path=tmp_path / "stations.json")
    resolver.initialize_for_startup()
    assert resolver.resolve_all("Ижевск") == []
    _wait(resolver.startup_refresh_background())
    assert resolver.resolve("Ижевск").code == "c44"
    diagnostics = resolver.startup_diagnostics()
    assert diagnostics["catalogue_status"] == "ready"
    assert diagnostics["cache_source"] == "remote"


def test_suggest_does_not_wait_for_background_catalogue(tmp_path):
    import threading
    release = threading.Event()
    started = threading.Event()
    def slow_loader():
        started.set()
        release.wait(2)
        return _directory()
    resolver = YandexLocationResolver(slow_loader, cache_path=tmp_path / "stations.json")
    resolver.initialize_for_startup()
    thread = resolver.startup_refresh_background()
    assert started.wait(1)
    before = time.monotonic()
    assert resolver.resolve("Казань").code == "c43"
    assert time.monotonic() - before < .2
    assert resolver.startup_refresh_background() is None
    release.set()
    _wait(thread)


def test_background_failure_cooldown_prevents_repeated_calls(tmp_path):
    calls = 0

    def unavailable():
        nonlocal calls
        calls += 1
        raise RuntimeError("unavailable")

    resolver = YandexLocationResolver(unavailable, cache_path=tmp_path / "stations.json")
    resolver.initialize_for_startup()
    _wait(resolver.startup_refresh_background())
    assert resolver.startup_refresh_background() is None
    time.sleep(0.01)
    assert calls == 1


def test_smoke_startup_network_flag_performs_zero_calls(tmp_path):
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return _directory()

    resolver = YandexLocationResolver(loader, cache_path=tmp_path / "stations.json")
    resolver.initialize_for_startup()
    assert resolver.startup_refresh_background(network_enabled=False) is None
    assert calls == 0


def test_application_health_survives_catalogue_rate_limit(tmp_path, monkeypatch):
    calls = 0

    def limited():
        nonlocal calls
        calls += 1
        raise RuntimeError("Yandex Rasp API rate limit exceeded")

    resolver = YandexLocationResolver(limited, cache_path=tmp_path / "stations.json")
    monkeypatch.setattr("app.main.yandex_location_resolver", resolver)
    monkeypatch.setenv("YANDEX_STATIONS_STARTUP_NETWORK_ENABLED", "true")

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
    for _ in range(100):
        if calls:
            break
        time.sleep(0.01)
    assert calls == 1
