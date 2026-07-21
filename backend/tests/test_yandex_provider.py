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


def test_empty_response_returns_no_segments():
    provider, _ = provider_with_payload({"segments": []})
    assert provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург") == []


def test_provider_returns_empty_on_auth_timeout_429_and_500_errors():
    for exc in (httpx.Response(403), httpx.TimeoutException("timeout"), httpx.Response(429), httpx.Response(500)):
        def handler(request, exc=exc):
            if isinstance(exc, httpx.Response):
                return exc
            raise exc
        client = YandexRaspClient(YandexRaspConfiguration("key", enabled=True), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.rasp.yandex.net/v3.0"))
        provider = YandexRaspProvider(YandexRaspConfiguration("key", enabled=True), client=client, resolver=YandexLocationResolver())
        assert provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург") == []
        assert provider.last_error


def test_unknown_city_returns_empty_result():
    provider, _ = provider_with_payload({"segments": [segment()]})
    assert provider.get_segments(DAY, [TransportType.TRAIN], origin="Неизвестный", destination="Москва") == []
