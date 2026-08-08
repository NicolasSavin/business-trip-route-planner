from app.providers.yandex.resolver import YandexLocationResolver


def directory():
    return {"countries": [{"title": "Россия", "regions": [
        {"title": "Московская область", "settlements": [{"title": "Москва", "codes": {"yandex_code": "c213"}, "stations": [
            {"title": "Москва Казанская", "code": "s2000003", "station_type": "railway_station", "transport_type": "train", "latitude": 55.77, "longitude": 37.65},
            {"title": "Москва Ленинградская", "code": "s2006004", "station_type": "railway_station", "transport_type": "train"},
        ]}]},
        {"title": "Удмуртия", "settlements": [{"title": "Сарапул", "codes": {"yandex_code": "c42"}, "stations": [{"title": "Сарапул", "code": "s9612363", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Алтайский край", "settlements": [{"title": "Бийск", "codes": {"yandex_code": "c197"}, "stations": [{"title": "Бийск", "code": "s9610404", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Орловская область", "settlements": [{"title": "Орёл", "codes": {"yandex_code": "c10"}, "stations": [{"title": "Орел", "code": "s10", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Пермский край", "settlements": [{"title": "Чайковский", "codes": {"yandex_code": "c20"}, "stations": [{"title": "Сайгатка", "code": "s20", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Пермский край", "settlements": [{"title": "Пермь", "codes": {"yandex_code": "c50"}, "stations": [{"title": "Пермь-2", "code": "s50", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Удмуртия", "settlements": [{"title": "Ижевск", "codes": {"yandex_code": "c44"}, "stations": [{"title": "Ижевск", "code": "s44", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Мурманская область", "settlements": [{"title": "Мурманск", "codes": {"yandex_code": "c23"}, "stations": [{"title": "Мурманск", "code": "s23", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Регион 1", "settlements": [{"title": "Мирный", "codes": {"yandex_code": "c30"}, "stations": [{"title": "Мирный", "code": "s30", "station_type": "railway_station", "transport_type": "train"}]}]},
        {"title": "Регион 2", "settlements": [{"title": "Мирный", "codes": {"yandex_code": "c31"}, "stations": [{"title": "Мирный", "code": "s31", "station_type": "railway_station", "transport_type": "train"}]}]},
    ]}]}


def resolver(tmp_path, payload=None):
    return YandexLocationResolver(directory_loader=lambda: payload or directory(), cache_path=tmp_path / "stations.json", ttl_seconds=3600)


def test_major_city_multiple_term_station_word_and_dedup(tmp_path):
    r = resolver(tmp_path)
    matches = r.resolve_all("Москва вокзал")
    assert matches[0].code == "c213"
    assert {s.code for s in matches[0].stations} >= {"s2000003", "s2006004"}
    assert len({m.code for m in r.resolve_all("Москва Казанская")}) == len(r.resolve_all("Москва Казанская"))


def test_small_city_specific_station_city_station_combo_and_yo(tmp_path):
    r = resolver(tmp_path)
    assert r.resolve("Бийск").code == "c197"
    assert r.resolve("станция Сайгатка").code == "s20"
    assert r.resolve("Чайковский Сайгатка").code == "s20"
    assert r.resolve("Орёл").code in {"c10", "s10"}
    assert r.resolve("Орел").code in {"c10", "s10"}


def test_complete_directory_supplies_russian_cities_not_in_defaults(tmp_path):
    r = resolver(tmp_path)

    for query in ("Ижевск", "Пермь", "Мурманск"):
        matches = r.resolve_all(query)
        assert matches
        assert matches[0].type == "city"
        assert matches[0].title == query

    assert r.resolve_all("совершенно-неизвестный-мусор") == []


def test_cold_start_builds_sqlite_and_returns_city_and_station_matches(tmp_path):
    path = tmp_path / "stations.json"
    r = YandexLocationResolver(directory_loader=directory, cache_path=path, ttl_seconds=3600)

    assert not path.with_suffix(".sqlite3").exists()
    assert r.resolve("Ижевск").code == "c44"
    assert path.with_suffix(".sqlite3").exists()
    assert r.stats()["locations"] > 0

    moscow = r.resolve_all("Москва")
    assert any(match.type == "city" for match in moscow)
    assert any(match.type == "station" for match in moscow)


def test_alias_unknown_ambiguous_and_diagnostics(tmp_path):
    r = resolver(tmp_path)
    assert r.resolve("мск").code == "c213"
    assert r.resolve_all("Нетакойточки") == []
    ambiguous = r.diagnostic("Мирный")
    assert ambiguous["diagnostics"]["ambiguous"] is True
    assert {m["region"] for m in ambiguous["matches"]} >= {"Регион 1", "Регион 2"}


def test_cache_remote_error_and_forced_update(tmp_path):
    calls = 0
    def loader():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("remote down")
        return directory()
    path = tmp_path / "stations.json"
    r = YandexLocationResolver(directory_loader=loader, cache_path=path, ttl_seconds=0)
    assert r.resolve("Сайгатка").code == "s20"
    r2 = YandexLocationResolver(directory_loader=loader, cache_path=path, ttl_seconds=0)
    assert r2.resolve("Сайгатка").code == "s20"
    assert r2.diagnostic("Сайгатка")["diagnostics"]["source"] == "cache"
    assert r.refresh()["total_points"] >= 8
