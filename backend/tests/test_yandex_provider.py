import logging
from datetime import date

import httpx
import pytest

from app.domain import TransportType
from app.engine import RouteEngine
from app.providers.yandex import YandexLocationResolver, YandexRaspClient, YandexRaspConfiguration, YandexRaspProvider
from app.providers.yandex.exceptions import YandexRaspUnexpectedContentTypeError

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


def test_yandex_provider_logs_entry_before_enabled_check(caplog):
    provider = YandexRaspProvider(YandexRaspConfiguration(None, enabled=False))

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        assert provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург") == []

    assert caplog.messages == [
        "route_search.yandex_provider_enter\norigin='Москва'\ndestination='Санкт-Петербург'\ndate=2026-08-10"
    ]
    assert {record.name for record in caplog.records} == {"uvicorn.error"}


def test_successful_search_maps_train_route():
    provider, client = provider_with_payload({"segments": [segment()]})
    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург")
    assert len(segments) == 1
    assert segments[0].transport_type == TransportType.TRAIN
    assert segments[0].carrier.name == "Перевозчик"
    assert segments[0].metadata["source"] == "Яндекс Расписания"
    assert client.kwargs["transfers"] is True
    assert provider.last_diagnostics["raw_direct_schedule_count"] == 1
    direct = provider.last_diagnostics["raw_direct_candidates"][0]
    assert direct["train_number"] == "001А"
    assert direct["departure"] == "2026-08-10T08:00:00+03:00"


def test_yandex_search_logs_direct_segment_diagnostics(caplog):
    direct = segment()
    direct["thread"]["title"] = "Москва — Санкт-Петербург"
    provider, _ = provider_with_payload({"segments": [direct]})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        provider.get_segments(
            DAY,
            [TransportType.TRAIN],
            origin="Москва",
            destination="Санкт-Петербург",
        )

    messages = [record.getMessage() for record in caplog.records]
    assert all(record.name == "uvicorn.error" for record in caplog.records)
    segment_message = next(
        message for message in messages
        if message.startswith("route_search.yandex_direct_segment")
    )
    assert "number='001А'" in segment_message
    assert "title='Москва — Санкт-Петербург'" in segment_message
    assert "origin='Москва'" in segment_message
    assert "destination='Санкт-Петербург'" in segment_message
    assert "origin_station='Москва'" in segment_message
    assert "destination_station='Санкт-Петербург'" in segment_message
    assert "departure_time=2026-08-10T08:00:00+03:00" in segment_message
    assert "route_search.yandex_segments_total count=4" in messages
    assert any(message.startswith("route_search.yandex_provider_output total_count=1 direct_count=1") for message in messages)
    assert any(message.startswith("route_search.yandex_response") for message in messages)
    assert any(message.startswith("route_search.yandex_direct_schedules") for message in messages)


def test_yandex_search_logs_reason_when_no_direct_candidates(caplog):
    provider, _ = provider_with_payload({"segments": []})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        try:
            provider.get_segments(
                DAY,
                [TransportType.TRAIN],
                origin="Москва",
                destination="Санкт-Петербург",
            )
        except Exception:
            pass

    messages = [record.getMessage() for record in caplog.records]
    assert all(record.name == "uvicorn.error" for record in caplog.records)
    assert "route_search.yandex_segments_total count=0" in messages
    assert any(message.startswith("route_search.yandex_provider_output total_count=0 direct_count=0") for message in messages)
    assert (
        "route_search.yandex_provider_output_direct_zero "
        "reason=yandex_returned_no_segments"
    ) in messages


def test_yandex_search_logs_station_requests_candidates_and_acceptance(caplog):
    provider, _ = provider_with_payload({"segments": [segment()]})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        provider.get_segments(
            DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург"
        )

    messages = caplog.messages
    station_summary = next(
        message for message in messages
        if message.startswith("route_search.yandex_station_candidates origin_station_search_count=")
    )
    assert "origin_station_search_count=2" in station_summary
    assert "destination_station_search_count=1" in station_summary
    assert any("role=origin code=s2000003" in message for message in messages)
    assert any("role=destination code=s9602494" in message for message in messages)
    assert any(
        message.startswith("route_search.yandex_request ")
        and "transfers=False" in message
        and "phase=response" in message
        and "segment_count=1" in message
        for message in messages
    )
    assert any(
        message.startswith("route_search.yandex_direct_candidate ")
        and "'train_number': '001А'" in message
        and "'transport_type': 'train'" in message
        for message in messages
    )
    assert any(message.startswith("route_search.yandex_direct_accepted ") for message in messages)
    assert any(
        message.startswith("route_search.yandex_provider_return total_count=1 direct_count=1")
        for message in messages
    )


def test_yandex_search_logs_direct_rejection_reasons(caplog):
    invalid = segment("train", "bad")
    invalid.pop("arrival")
    duplicate = segment("train", "duplicate")
    provider, _ = provider_with_payload({"segments": [invalid, duplicate, duplicate]})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        provider.get_segments(
            DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург"
        )

    rejected = [
        message for message in caplog.messages
        if message.startswith("route_search.yandex_direct_rejected ")
    ]
    assert any("reason=invalid_schedule_missing_arrival" in message for message in rejected)
    assert any("reason=duplicate_segment_id" in message for message in rejected)


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
        client = YandexRaspClient(YandexRaspConfiguration("key", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0"))
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

    assert config.base_url == "https://api.rasp.yandex-net.ru/v3.0/"


@pytest.mark.parametrize("legacy_url", [
    "api.rasp.yandex.net",
    "https://api.rasp.yandex.net",
    "https://api.rasp.yandex.net/v3.0/",
    "http://api.rasp.yandex.net/v3.0/stations_list/",
])
def test_yandex_legacy_base_url_normalizes_to_canonical(legacy_url):
    config = YandexRaspConfiguration("secret", enabled=True, base_url=legacy_url)

    assert config.base_url == "https://api.rasp.yandex-net.ru/v3.0/"


def test_yandex_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("YANDEX_RASP_BASE_URL", "https://example.test/v3.0")

    config = YandexRaspConfiguration.from_env()

    assert config.base_url == "https://example.test/v3.0/"


def test_yandex_client_search_preserves_api_version_path_in_request_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url.copy_with(query=None))
        return httpx.Response(200, json={"pagination": {}, "segments": [], "search": {}}, headers={"content-type": "application/json"}, request=request)

    config = YandexRaspConfiguration("secret", enabled=True, base_url="https://api.rasp.yandex-net.ru/v3.0")
    client = YandexRaspClient(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), base_url=config.base_url),
    )

    client.search(origin_code="c2", destination_code="c213", departure_date=DAY, allowed_transport=[TransportType.TRAIN])

    assert seen["url"] == "https://api.rasp.yandex-net.ru/v3.0/search/"
    assert seen["url"] != "https://api.rasp.yandex-net.ru/search/"


def test_yandex_client_stations_list_preserves_api_version_path_in_request_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url.copy_with(query=None))
        return httpx.Response(200, json={"countries": []}, headers={"content-type": "application/json"}, request=request)

    config = YandexRaspConfiguration("secret", enabled=True, base_url="https://api.rasp.yandex-net.ru/v3.0")
    client = YandexRaspClient(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler), base_url=config.base_url),
    )

    client.stations_list()

    assert seen["url"] == "https://api.rasp.yandex-net.ru/v3.0/stations_list/"
    assert seen["url"] != "https://api.rasp.yandex-net.ru/stations_list/"


def test_yandex_stations_list_legacy_html_retries_canonical_once():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.rasp.yandex.net":
            return httpx.Response(200, text="<html>legacy</html>", headers={"content-type": "text/html; charset=utf-8"}, request=request)
        return httpx.Response(200, json={"countries": []}, headers={"content-type": "application/json"}, request=request)

    # An externally supplied client may retain a legacy base URL even though all
    # YandexRaspConfiguration values are normalized.
    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex.net/v3.0/")
    client = YandexRaspClient(YandexRaspConfiguration("top-secret-key", enabled=True), http_client)

    assert client.stations_list() == {"countries": []}
    assert [(request.url.host, request.url.path) for request in requests] == [
        ("api.rasp.yandex.net", "/v3.0/stations_list/"),
        ("api.rasp.yandex-net.ru", "/v3.0/stations_list/"),
    ]
    assert all(request.url.params["format"] == "json" and request.url.params["lang"] == "ru_RU" for request in requests)


def test_yandex_stations_list_canonical_json_succeeds_without_retry():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"countries": []}, headers={"content-type": "application/json"}, request=request)

    client = YandexRaspClient(YandexRaspConfiguration("secret", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0/"))

    assert client.stations_list() == {"countries": []}
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"apikey": "secret", "format": "json", "lang": "ru_RU"}


def test_yandex_stations_list_canonical_html_raises_safe_error_and_does_not_retry(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="<html>bad</html>", headers={"content-type": "text/html; charset=utf-8"}, request=request)

    client = YandexRaspClient(YandexRaspConfiguration("top-secret-key", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex-net.ru/v3.0/"))

    with pytest.raises(YandexRaspUnexpectedContentTypeError) as raised:
        client.stations_list()

    assert len(requests) == 1
    details = raised.value.to_error()["details"]
    assert details["request_host"] == "api.rasp.yandex-net.ru"
    assert details["request_path"] == "/v3.0/stations_list/"
    assert details["status_code"] == 200
    assert details["content_type"].startswith("text/html")
    assert "top-secret-key" not in str(details)
    assert "top-secret-key" not in caplog.text


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


def test_yandex_provider_uses_provider_codes_without_string_resolve():
    provider, client = provider_with_payload({"segments": [segment()]})
    segments = provider.get_segments(
        DAY,
        [TransportType.TRAIN],
        origin="Санкт-Петербург (train/bus)",
        destination="Москва (train/bus)",
        origin_provider_code="c2",
        destination_provider_code="c213",
    )

    assert segments
    assert client.kwargs["origin_code"] == "s9602494"
    assert client.kwargs["destination_code"] in {"s2000003", "s2006004"}


def test_yandex_resolver_strips_ui_suffix_as_fallback():
    resolver = YandexLocationResolver()

    assert resolver.resolve("Санкт-Петербург (train/bus)").code == "c2"
    assert resolver.resolve("Москва (поезд/автобус)").code == "c213"
