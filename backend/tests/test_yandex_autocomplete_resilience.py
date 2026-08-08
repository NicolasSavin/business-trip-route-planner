import sqlite3
import threading
import time

from app.providers.yandex.resolver import YandexLocationResolver


def complete_directory():
    settlements = []
    for city, city_code, stations in (
        ("Ижевск", "c44", [("Ижевск", "s9602496")]),
        ("Пермь", "c50", [("Пермь-2", "s9602498")]),
        ("Мурманск", "c23", [("Мурманск", "s9602499")]),
        ("Москва", "c213", [("Москва Курская", "s2000001")]),
        ("Кеза", "c999", [("Кеза", "s9990001")]),
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
