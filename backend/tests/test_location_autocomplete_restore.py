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
