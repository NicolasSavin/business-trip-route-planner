from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.locations import yandex_location_resolver
from app.main import app
from app.providers.yandex.resolver import (
    SQLiteYandexStationsRepository,
    YandexLocationMatch,
)


def test_sqlite_suggest_moscow_does_not_raise_attribute_error(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "stations.sqlite3")
    repo.rebuild_from_directory({"countries": []})

    matches = repo.resolve("Москва")

    assert matches
    assert any(match.title == "Москва" for match in matches)


def test_sqlite_suggest_saint_petersburg_returns_local_items(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "stations.sqlite3")
    repo.rebuild_from_directory({"countries": []})

    matches = repo.resolve("Санкт-Петербург")

    assert matches
    assert any(match.title == "Санкт-Петербург" for match in matches)


def test_sqlite_dedupe_removes_identical_code_and_fallback_key(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "stations.sqlite3")
    first = YandexLocationMatch("s1", "Москва Казанская", "station", settlement="Москва", region="Москва")
    second = YandexLocationMatch("s1", "Москва Казанская дубль", "station", settlement="Москва", region="Москва")
    no_code_first = YandexLocationMatch("", "Москва Казанская", "station", settlement="Москва", region="Москва")
    no_code_second = YandexLocationMatch("", "москва казанская", "station", settlement="Москва", region="Москва")

    assert repo._dedupe([first, second, no_code_first, no_code_second]) == [first, no_code_first]


def test_sqlite_dedupe_keeps_different_moscow_railway_stations(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "stations.sqlite3")
    kazansky = YandexLocationMatch("s2000003", "Москва Казанская", "station", settlement="Москва", region="Москва")
    leningradsky = YandexLocationMatch("s2006004", "Москва Ленинградская", "station", settlement="Москва", region="Москва")

    assert repo._dedupe([kazansky, leningradsky]) == [kazansky, leningradsky]


def test_sqlite_dedupe_preserves_order(tmp_path: Path):
    repo = SQLiteYandexStationsRepository(path=tmp_path / "stations.sqlite3")
    first = YandexLocationMatch("s2", "Второй", "station")
    second = YandexLocationMatch("s1", "Первый", "station")
    duplicate_first = YandexLocationMatch("s2", "Второй дубль", "station")

    assert repo._dedupe([first, second, duplicate_first]) == [first, second]


def test_location_suggest_limit_applies_after_yandex_deduplication(monkeypatch):
    first = YandexLocationMatch("s1", "Первая", "station")
    duplicate_first = YandexLocationMatch("s1", "Первая дубль", "station")
    second = YandexLocationMatch("s2", "Вторая", "station")
    deduped = SQLiteYandexStationsRepository()._dedupe([first, duplicate_first, second])
    monkeypatch.setattr(yandex_location_resolver, "resolve_all", lambda _q: deduped)

    response = TestClient(app).get("/api/v1/locations/suggest", params={"q": "Мо", "limit": 2})

    assert response.status_code == 200
    assert [item["provider_code"] for item in response.json()["items"]] == ["s1", "s2"]


def test_location_suggest_does_not_mask_programming_errors(monkeypatch):
    def fail(_q):
        raise AttributeError("programming error")

    monkeypatch.setattr(yandex_location_resolver, "resolve_all", fail)

    with pytest.raises(AttributeError):
        TestClient(app, raise_server_exceptions=True).get("/api/v1/locations/suggest", params={"q": "Москва"})
