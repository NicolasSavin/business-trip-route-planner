from fastapi.testclient import TestClient

from app.locations import LocationNormalizer, LocationRepository
from app.main import app
from app.providers.yandex.resolver import YandexLocationResolver


def names(matches):
    return [match.title for match in matches]


def failing_loader():
    raise RuntimeError("stations_list unavailable")


def test_yandex_resolver_partial_city_queries_with_empty_cache(tmp_path):
    resolver = YandexLocationResolver(directory_loader=failing_loader, cache_path=tmp_path / "stations.json")

    assert "Бийск" in names(resolver.resolve_all("бий"))
    assert "Бийск" in names(resolver.resolve_all("Бийск"))
    assert "Москва" in names(resolver.resolve_all("моск"))
    assert "Санкт-Петербург" in names(resolver.resolve_all("санкт"))


def test_yandex_resolver_case_and_yo_normalization_with_empty_cache(tmp_path):
    resolver = YandexLocationResolver(directory_loader=failing_loader, cache_path=tmp_path / "stations.json")

    assert resolver.normalize("  САНКТ-петербург ") == "санкт петербург"
    assert LocationNormalizer.normalize("Орёл") == "орел"
    assert "Москва" in names(resolver.resolve_all("МОС"))


def test_location_repository_fallback_knows_biysk_when_yandex_cache_empty():
    result = LocationRepository().suggest("бий", 8)

    assert result
    assert result[0].name == "Бийск"


def test_suggest_endpoint_reproduced_queries_do_not_500():
    client = TestClient(app)

    for query in ["Бийск", "бий", "Москва", "моск", "санкт"]:
        response = client.get("/api/v1/locations/suggest", params={"q": query, "limit": 8})
        assert response.status_code == 200
        payload = response.json()
        assert "items" in payload
        assert payload["items"]


def test_ryazan_partial_suggest_endpoint_returns_city():
    client = TestClient(app)

    response = client.get("/api/v1/locations/suggest", params={"q": "Ряза", "limit": 8})

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["name"] == "Рязань" and item["type"] == "city" for item in items)


def test_lowercase_cyrillic_partial_queries_return_known_cities():
    client = TestClient(app)

    expected = {"ряза": "Рязань", "твер": "Тверь", "санкт": "Санкт-Петербург", "бий": "Бийск"}
    for query, city in expected.items():
        response = client.get("/api/v1/locations/suggest", params={"q": query, "limit": 8})
        assert response.status_code == 200
        assert city in [item["name"] for item in response.json()["items"]]


def test_fallback_returns_known_city_when_external_resolver_fails(tmp_path):
    resolver = YandexLocationResolver(directory_loader=failing_loader, cache_path=tmp_path / "stations.json")

    assert "Рязань" in names(resolver.resolve_all("ряза"))


def test_sqlite_search_uses_normalized_python_cyrillic_matching(tmp_path):
    resolver = YandexLocationResolver(directory_loader=failing_loader, cache_path=tmp_path / "stations.json")
    resolver._maybe_seed_repository()

    matches = resolver.resolve_all("РЯЗА")

    assert "Рязань" in names(matches)
    assert resolver.normalize("РЯЗА") == "ряза"


def test_exact_city_ranked_above_station_for_same_name():
    result = LocationRepository().suggest("тверь", 8)

    assert result[0].name == "Тверь"
    assert result[0].type == "city"
