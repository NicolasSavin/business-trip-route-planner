from app.locations import LocationNormalizer, LocationRepository, TtlCache


def names(items):
    return [item.display_name for item in items]


def test_moscow_suggestions_include_city_and_stations():
    result = LocationRepository().suggest("мос", 10)
    assert "Москва" in names(result)
    assert "Москва, Казанский вокзал" in names(result)


def test_sarapul_saratov_saransk_search():
    assert names(LocationRepository().suggest("сар", 10))[:3] == ["Сарапул", "Саратов", "Саранск"]


def test_case_insensitive_and_yo_normalization():
    repo = LocationRepository()
    assert names(repo.suggest("МОС", 3))[0] == "Москва"
    assert LocationNormalizer.normalize("  Ёлка  ") == "елка"


def test_spb_alias():
    assert names(LocationRepository().suggest("СПб", 5))[0] == "Санкт-Петербург"


def test_city_sorted_before_station_for_same_match():
    result = LocationRepository().suggest("москва", 5)
    assert result[0].type == "city"


def test_limit():
    assert len(LocationRepository().suggest("мос", 2)) == 2


def test_empty_and_short_query():
    repo = LocationRepository()
    assert repo.suggest("", 10) == []
    assert repo.suggest("м", 10) == []


def test_cache_returns_cached_value():
    cache = TtlCache(ttl_seconds=60, max_size=10)
    repo = LocationRepository(cache=cache)
    first = repo.suggest("мос", 3)
    repo.records = []
    assert repo.suggest("мос", 3) == first


def test_unknown_query():
    assert LocationRepository().suggest("неизвестныйгород", 10) == []
