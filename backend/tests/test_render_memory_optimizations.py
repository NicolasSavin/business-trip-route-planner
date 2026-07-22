from __future__ import annotations

import asyncio
from pathlib import Path

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityCache, SegmentAvailabilityResult
from app.browser.config import BrowserConfiguration
from app.browser.manager import BrowserManager
from app.providers.tutu.playwright.provider import TutuPlaywrightProvider
from app.providers.yandex.resolver import SQLiteYandexStationsRepository, YandexLocationResolver


def _directory():
    return {"countries": [{"title": "Россия", "regions": [{"title": "Тестовый регион", "settlements": [{"title": "Тестоград", "codes": {"yandex_code": "c100"}, "stations": [{"title": "Тестоград Главный", "code": "s100", "station_type": "railway_station", "transport_type": "train"}]}]}]}]}


def test_location_resolver_uses_sqlite_lazy_once(tmp_path: Path):
    calls = 0
    def loader():
        nonlocal calls
        calls += 1
        return _directory()
    resolver = YandexLocationResolver(directory_loader=loader, cache_path=tmp_path / "stations.json")
    assert calls == 0
    assert resolver.resolve("Тестоград").code == "c100"
    assert resolver.resolve("Тестоград Главный").code == "s100"
    assert calls == 1
    assert (tmp_path / "stations.sqlite3").exists()


def test_empty_sqlite_cache_returns_no_match(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "empty.sqlite3")
    resolver = YandexLocationResolver(stations_repository=repo)
    assert resolver.resolve_all("Нетакойточки") == []
    assert repo.cache_info()["storage"] == "sqlite"


def test_browser_startup_diagnostics_does_not_start_browser():
    manager = BrowserManager(config=BrowserConfiguration(playwright_enabled=False))
    asyncio.run(manager.startup_diagnostics())
    assert manager.browser_running is False


def test_tutu_playwright_provider_client_is_lazy():
    provider = TutuPlaywrightProvider()
    assert provider._client is None


def test_segment_availability_cache_is_bounded():
    cache = SegmentAvailabilityCache(max_size=2)
    for idx in range(3):
        cache.set(str(idx), SegmentAvailabilityResult(segment_id=str(idx), provider="test", status=AvailabilityStatus.CONFIRMED))
    assert cache.get("0") is None
    assert cache.get("1") is not None
    assert cache.get("2") is not None
