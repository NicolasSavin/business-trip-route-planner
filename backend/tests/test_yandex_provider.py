from datetime import date

import httpx

from app.domain import TransportType
from app.engine import RouteEngine
from app.providers.yandex import YandexLocationResolver, YandexRaspClient, YandexRaspConfiguration, YandexRaspProvider

DAY = date(2026, 8, 10)


def station(title, code):
    return {"title": title, "code": code, "settlement": {"title": title}}


def segment(ttype="train", number="001А", origin="Москва", destination="Санкт-Петербург"):
    return {
        "thread": {"uid": f"{number}-{ttype}", "number": number, "transport_type": ttype, "carrier": {"code": "carrier", "title": "Перевозчик"}},
        "from": station(origin, "s1"),
        "to": station(destination, "s2"),
        "departure": "2026-08-10T08:00:00+03:00",
        "arrival": "2026-08-10T12:00:00+03:00",
    }


def provider_with_payload(payload):
    class Client:
        def stations_list(self):
            return {}
        def search(self, **kwargs):
            self.kwargs = kwargs
            return payload
    client = Client()
    resolver = YandexLocationResolver()
    return YandexRaspProvider(YandexRaspConfiguration("key", enabled=True), client=client, resolver=resolver), client


def test_successful_search_maps_train_route():
    provider, client = provider_with_payload({"segments": [segment()]})
    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    assert len(segments) == 1
    assert segments[0].transport_type == TransportType.TRAIN
    assert segments[0].carrier.name == "Перевозчик"
    assert segments[0].metadata["source"] == "Яндекс Расписания"
    assert client.kwargs["transfers"] is True


def test_bus_segment_is_supported():
    provider, _ = provider_with_payload({"segments": [segment("bus", "МБ-10")]})
    segments = provider.get_segments(DAY, [TransportType.BUS], origin="Москва", destination="Санкт-Петербург")
    assert segments[0].transport_type == TransportType.BUS
    assert segments[0].vehicle_number == "МБ-10"


def test_multiple_transfer_details_are_mapped_for_route_engine():
    payload = {"segments": [{"has_transfers": True, "details": [segment("train", "001А", "Москва", "Казань"), segment("bus", "К-2", "Казань", "Санкт-Петербург")]}]}
    provider, _ = provider_with_payload(payload)
    routes = RouteEngine(provider).search(DAY, "Москва", "Санкт-Петербург", 1, [TransportType.TRAIN, TransportType.BUS], 1, 30)
    assert routes and routes[0].route.transfers_count == 1


def test_empty_response_returns_structured_error():
    provider, _ = provider_with_payload({"segments": []})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    except Exception:
        assert provider.last_error_payload["code"] == "empty_provider_response"
    else:
        raise AssertionError("expected empty provider response")


def test_provider_raises_auth_timeout_429_and_500_errors():
    for exc in (httpx.Response(403), httpx.TimeoutException("timeout"), httpx.Response(429), httpx.Response(500)):
        def handler(request, exc=exc):
            if isinstance(exc, httpx.Response):
                return exc
            raise exc
        client = YandexRaspClient(YandexRaspConfiguration("key", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex.net/v3.0"))
        provider = YandexRaspProvider(YandexRaspConfiguration("key", enabled=True), client=client, resolver=YandexLocationResolver())
        try:
            provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
        except Exception:
            assert provider.last_error
        else:
            raise AssertionError("expected provider error")


def test_unknown_city_raises_clear_error():
    provider, _ = provider_with_payload({"segments": [segment()]})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Неизвестный", destination="Москва")
    except Exception as exc:
        assert "Неизвестный город" in str(exc)
    else:
        raise AssertionError("expected unknown city error")


def test_yandex_enabled_when_api_key_is_present(monkeypatch):
    monkeypatch.setenv("YANDEX_RASP_API_KEY", "secret")
    monkeypatch.delenv("YANDEX_RASP_ENABLED", raising=False)

    config = YandexRaspConfiguration.from_env()

    assert config.enabled is True


def test_yandex_missing_api_key_is_not_silently_swallowed():
    provider = YandexRaspProvider(YandexRaspConfiguration(None, enabled=True), resolver=YandexLocationResolver())

    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    except Exception as exc:
        assert "YANDEX_RASP_API_KEY" in str(exc)
    else:
        raise AssertionError("expected Yandex Rasp API key error")


def test_yandex_resolver_resolves_required_cities_aliases_case_and_yo():
    resolver = YandexLocationResolver()
    assert resolver.resolve("Сарапул").code == "c42"
    assert resolver.resolve("бийск").code == "c197"
    assert resolver.resolve("МОСКВА").code == "c213"
    assert resolver.resolve("СПб").code == "c2"
    assert resolver.resolve("санкт-петербург").code == "c2"
    assert resolver.resolve("Екатеринбург").code == "c54"
    assert resolver.resolve("Новосибирск").code == "c65"
    assert YandexLocationResolver.normalize("Ёлка") == YandexLocationResolver.normalize("Елка")


def test_yandex_resolver_returns_multiple_station_codes_for_city():
    match = YandexLocationResolver().resolve("Бийск")
    assert set(match.station_codes) >= {"s9610404", "s9657040"}
    assert match.type == "city"


def test_yandex_resolver_unknown_city():
    try:
        YandexLocationResolver().resolve("Неизвестныйгород")
    except Exception as exc:
        assert getattr(exc, "code", "") == "unknown_location"
    else:
        raise AssertionError("expected unknown location")


def test_yandex_provider_passes_resolved_station_codes_to_search():
    provider, client = provider_with_payload({"segments": []})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN, TransportType.BUS], origin="Сарапул", destination="Бийск")
    except Exception:
        pass
    assert client.kwargs["origin_code"] in {"s9612363", "s9635668"}
    assert client.kwargs["destination_code"] in {"s9610404", "s9657040"}


def test_yandex_provider_no_direct_segments_is_diagnostic_not_unknown_city():
    provider, _ = provider_with_payload({"segments": []})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Сарапул", destination="Бийск")
    except Exception:
        assert provider.last_error_payload["code"] == "empty_provider_response"
        assert provider.last_error_payload["details"]["resolved_origin_codes"]
    else:
        raise AssertionError("expected empty provider response")


def test_yandex_mapper_handles_missing_transport_subtype_and_empty_prices():
    payload = {"segments": [segment(None, "001А") | {"tickets_info": {"places": []}}]}
    provider, _ = provider_with_payload(payload)
    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    assert segments[0].transport_type == TransportType.TRAIN
    assert segments[0].price is None


def test_yandex_mapper_skips_missing_station_code_without_index_error():
    bad = segment()
    bad["from"] = {"title": "Москва", "settlement": {"title": "Москва"}}
    provider, _ = provider_with_payload({"segments": [bad]})
    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    assert segments[0].origin_station.code == "Москва"


def test_yandex_empty_segments_raise_structured_error_not_index_error():
    provider, _ = provider_with_payload({"segments": []})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    except Exception:
        assert provider.last_error_payload["code"] == "empty_provider_response"
        assert provider.last_error_payload["message"] == "Яндекс Расписания не вернули сегменты"
        assert "list index out of range" not in provider.last_error_payload["message"]
    else:
        raise AssertionError("expected empty provider response")


def test_yandex_invalid_json_structure_is_structured_error():
    provider, _ = provider_with_payload({"unexpected": []})
    try:
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    except Exception:
        assert provider.last_error_payload["code"] == "invalid_provider_response"
        assert provider.last_diagnostics["pair_errors"][0]["error"]["code"] == "invalid_provider_response"
    else:
        raise AssertionError("expected invalid provider response")


def test_yandex_pair_failure_does_not_abort_all_pairs_and_deduplicates():
    class Client:
        last_status_code = 200
        def stations_list(self):
            return {}
        def search(self, **kwargs):
            self.kwargs = kwargs
            if kwargs["origin_code"] == "s2000003":
                return {"unexpected": []}
            return {"segments": [segment(), segment()]}
    client = Client()
    provider = YandexRaspProvider(YandexRaspConfiguration("key", enabled=True), client=client, resolver=YandexLocationResolver())
    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    assert len(segments) == 1
    assert provider.last_diagnostics["attempts"][0]["error"]["code"] == "invalid_provider_response"


def test_yandex_resolver_diagnostic_empty_matches():
    payload = YandexLocationResolver().diagnostic("Неизвестныйгород")
    assert payload["matches"] == []


def test_yandex_default_base_url_uses_new_domain(monkeypatch):
    monkeypatch.delenv("YANDEX_RASP_BASE_URL", raising=False)

    config = YandexRaspConfiguration.from_env()

    assert config.base_url == "https://api.rasp.yandex-net.ru/v3.0"


def test_yandex_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("YANDEX_RASP_BASE_URL", "https://example.test/v3.0")

    config = YandexRaspConfiguration.from_env()

    assert config.base_url == "https://example.test/v3.0"


def test_yandex_client_json_response_is_parsed_and_search_params_are_documented():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"pagination": {}, "segments": [], "search": {}}, headers={"content-type": "application/json"})

    client = YandexRaspClient(YandexRaspConfiguration("secret", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0"))

    payload = client.search(origin_code="c2", destination_code="c213", departure_date=DAY, allowed_transport=[TransportType.TRAIN], transfers=True)

    assert sorted(payload) == ["pagination", "search", "segments"]
    assert seen["params"]["system"] == "yandex"
    assert seen["params"]["limit"] == "100"
    assert seen["params"]["offset"] == "0"
    assert "page" not in seen["params"]


def test_yandex_client_html_response_returns_unexpected_content_type_without_full_html():
    html = "<html>" + ("secret-html" * 200) + "</html>"

    def handler(request):
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"}, request=request)

    client = YandexRaspClient(YandexRaspConfiguration("secret", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0"))

    try:
        client.search(origin_code="c2", destination_code="c213", departure_date=DAY, allowed_transport=[TransportType.TRAIN])
    except Exception as exc:
        error = exc.to_error()
    else:
        raise AssertionError("expected unexpected content type")

    assert error["code"] == "unexpected_content_type"
    assert error["message"] == "Яндекс Расписания вернули ответ не в формате JSON"
    assert error["details"]["content_type"].startswith("text/html")
    assert len(error["details"]["body_preview"]) == 1000
    assert html not in str(error)
    assert "secret" not in error["details"]["request_url"]


def test_yandex_client_redirect_is_followed_and_final_url_saved():
    def handler(request):
        if request.url.host == "api.rasp.yandex-net.ru":
            return httpx.Response(302, headers={"location": "https://redirected.example/v3.0/search/"}, request=request)
        return httpx.Response(200, json={"pagination": {}, "segments": [], "search": {}}, headers={"content-type": "application/json"}, request=request)

    client = YandexRaspClient(YandexRaspConfiguration("secret", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0", follow_redirects=True))

    client.search(origin_code="c2", destination_code="c213", departure_date=DAY, allowed_transport=[TransportType.TRAIN])

    assert client.last_response_diagnostics["final_response_url"] == "https://redirected.example/v3.0/search/"


def test_yandex_client_api_key_is_not_in_unexpected_content_type_diagnostics():
    def handler(request):
        return httpx.Response(200, text="<html>bad</html>", headers={"content-type": "text/html"}, request=request)

    client = YandexRaspClient(YandexRaspConfiguration("top-secret-key", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0"))

    try:
        client.search(origin_code="c2", destination_code="c213", departure_date=DAY, allowed_transport=[TransportType.TRAIN])
    except Exception as exc:
        error = exc.to_error()
    else:
        raise AssertionError("expected unexpected content type")

    assert "top-secret-key" not in __import__("json").dumps(error, ensure_ascii=False)
