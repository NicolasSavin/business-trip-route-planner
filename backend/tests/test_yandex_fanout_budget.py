from datetime import date

import pytest

from app.domain import TransportType
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.provider import YandexRaspProvider
from app.providers.yandex.resolver import YandexLocationMatch, YandexStation


DAY = date(2026, 9, 21)


def schedule():
    return {
        "thread": {"uid": "001-train", "number": "001", "transport_type": "train", "carrier": {"code": "rzd", "title": "РЖД"}},
        "from": {"code": "s1", "title": "Москва", "settlement": {"title": "Москва"}},
        "to": {"code": "s2", "title": "Санкт-Петербург", "settlement": {"title": "Санкт-Петербург"}},
        "departure": "2026-09-21T08:00:00+03:00",
        "arrival": "2026-09-21T12:00:00+03:00",
    }


class Resolver:
    def __init__(self):
        self.locations = {
            "Москва": YandexLocationMatch("c213", "Москва", "city", stations=(
                YandexStation("s-train-a", "Москва Вокзал", "railway_station", ("train",)),
                YandexStation("s-airport", "Шереметьево", "airport", ("plane",)),
                YandexStation("s-bus", "Автовокзал", "bus_station", ("bus",)),
                YandexStation("s-water", "Речной вокзал", "water_station", ("water",)),
                YandexStation("s-train-b", "Москва станция", "station", ("suburban",)),
            )),
            "Санкт-Петербург": YandexLocationMatch("c2", "Санкт-Петербург", "city", stations=(
                YandexStation("s-train-c", "Московский вокзал", "railway_station", ("train",)),
            )),
        }

    def resolve(self, title):
        return self.locations[title]

    def resolve_code(self, code, title):
        if code.startswith("s"):
            return YandexLocationMatch(code, title, "station", ("train",))
        return self.locations[title]


class Client:
    def __init__(self, response_for=None):
        self.calls = []
        self.response_for = response_for or (lambda _kwargs: {"segments": []})

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.response_for(kwargs)


def make_provider(client, **limits):
    config = YandexRaspConfiguration("key", enabled=True, **limits)
    return YandexRaspProvider(config, client=client, resolver=Resolver())


def test_city_direct_train_fans_out_across_city_and_known_stations():
    client = Client(lambda _: {"segments": [schedule()]})
    provider = make_provider(client)

    provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", max_transfers=0)

    pairs = [(call["origin_code"], call["destination_code"]) for call in client.calls]
    assert pairs[0] == ("c213", "c2")
    assert {"c213", "s-train-a", "s-train-b"} <= {origin for origin, _ in pairs}
    assert {"c2", "s-train-c"} <= {destination for _, destination in pairs}
    assert provider.last_diagnostics["yandex_direct_requests_made"] == len(pairs)


def test_explicit_stations_are_used_directly_first():
    client = Client(lambda _: {"segments": [schedule()]})
    provider = make_provider(client)

    provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", origin_provider_code="s9612140", destination_provider_code="s9602494", max_transfers=0)

    assert (client.calls[0]["origin_code"], client.calls[0]["destination_code"]) == ("s9612140", "s9602494")
    assert len(client.calls) == 1


def test_mixed_train_bus_search_preserves_explicit_city_code():
    provider = make_provider(Client())
    city = YandexLocationMatch("c213", "Москва", "city", stations=(
        YandexStation("s-train", "Вокзал", "railway_station", ("train",)),
        YandexStation("s-bus", "Автовокзал", "bus_station", ("bus",)),
    ), source="provider_code")
    codes = provider._codes_for_transport(city, [TransportType.TRAIN, TransportType.BUS])
    assert codes[0] == "c213"
    assert {"s-train", "s-bus"} <= set(codes)


def test_transfer_search_checks_every_destination_station_before_cartesian_fallback():
    client = Client()
    provider = make_provider(client, max_direct_requests_per_search=1, max_transfer_requests_per_search=6)
    provider.resolver.locations["Санкт-Петербург"] = YandexLocationMatch("c2", "Санкт-Петербург", "city", stations=(
        YandexStation("s-destination-a", "Вокзал A", "railway_station", ("train",)),
        YandexStation("s-destination-b", "Вокзал B", "railway_station", ("train",)),
    ))
    with pytest.raises(Exception):
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", max_transfers=1)
    transfer_destinations = {call["destination_code"] for call in client.calls if call["transfers"]}
    assert {"c2", "s-destination-a", "s-destination-b"} <= transfer_destinations
    assert len([call for call in client.calls if call["transfers"]]) <= 6


def test_empty_city_response_uses_only_bounded_train_station_fallback():
    client = Client(lambda kwargs: {"segments": [schedule()]} if kwargs["origin_code"] == "s-train-a" else {"segments": []})
    provider = make_provider(client, max_stations_per_city=2, max_direct_requests_per_search=3)

    provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", max_transfers=0)

    codes = {call["origin_code"] for call in client.calls} | {call["destination_code"] for call in client.calls}
    assert not {"s-airport", "s-bus", "s-water"} & codes
    assert len(client.calls) <= 3
    assert client.calls[0]["origin_code"] == "c213"


def test_direct_and_transfer_request_budgets_are_hard_limits():
    client = Client()
    provider = make_provider(client, max_direct_requests_per_search=2, max_transfer_requests_per_search=1)

    with pytest.raises(Exception):
        provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", max_transfers=1)

    assert provider.last_diagnostics["yandex_direct_requests_made"] == 2
    assert provider.last_diagnostics["yandex_transfer_requests_made"] == 1
    assert provider.last_diagnostics["yandex_fanout_limited"] is True


def test_total_deadline_stops_additional_requests(monkeypatch):
    clock = [0.0]

    def response(_):
        clock[0] = 2.0
        return {"segments": [schedule()]}

    monkeypatch.setattr("app.providers.yandex.provider.monotonic", lambda: clock[0])
    client = Client(response)
    provider = make_provider(client, route_search_total_timeout_seconds=1.0)

    segments = provider.get_segments(DAY, [TransportType.TRAIN], origin="Москва", destination="Санкт-Петербург", max_transfers=1)

    assert segments
    assert len(client.calls) == 1
    assert provider.last_diagnostics["yandex_search_deadline_exceeded"] is True
    assert provider.last_diagnostics["warnings"]
