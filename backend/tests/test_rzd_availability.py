from datetime import date, datetime

import pytest

from app.availability.journey import AvailabilityStatus
from app.domain import Carrier, City, Station, TransportSegment, TransportType
from app.models.routes import RouteSearchRequest
from app.providers.rzd_availability import (
    RZDClient,
    RZDAvailabilityConfig,
    RZDAvailabilityProvider,
    normalize_train_number,
)


class FakeRZD:
    def __init__(self):
        self.station_calls = 0
        self.search_calls = 0

    def suggest_stations(self, query):
        self.station_calls += 1
        return [{"code": "2000000" if query == "Москва" else "2004000", "name": query}]

    def search_trains(self, **kwargs):
        self.search_calls += 1
        return [{"id": "train-8", "trainNumber": "008С"}]

    def train_availability(self, **kwargs):
        return {
            "carriages": [
                {
                    "number": "01",
                    "type": "coupe",
                    "freeSeats": 2,
                    "seats": [{"number": "1"}, {"number": "2"}],
                }
            ]
        }


def config(**kwargs):
    return RZDAvailabilityConfig(enabled=True, retries=0, **kwargs)


@pytest.mark.asyncio
async def test_client_looks_up_stations_carriages_and_caches_identical_searches():
    sdk = FakeRZD()
    client = RZDClient(config(), sdk_factory=lambda **_: sdk)
    first = await client.search("Москва", "Петербург", date(2026, 8, 10), 2)
    second = await client.search("Москва", "Петербург", date(2026, 8, 10), 2)
    assert first is second
    assert first.trains[0].available_seats == 2
    assert [seat.number for seat in first.trains[0].seats] == ["1", "2"]
    assert sdk.station_calls == 2
    assert sdk.search_calls == 1


@pytest.mark.parametrize(
    ("value", "expected"), [("008С", "8C"), ("008C", "8C"), ("8С", "8C"), ("8C", "8C")]
)
def test_train_number_normalization(value, expected):
    assert normalize_train_number(value) == expected


def segment():
    origin = City("Москва")
    destination = City("Петербург")
    return TransportSegment(
        "s1",
        "yandex",
        Carrier("rzd", "РЖД"),
        TransportType.TRAIN,
        None,
        "8C",
        origin,
        Station("1", "Москва", origin),
        destination,
        Station("2", "Петербург", destination),
        datetime(2026, 8, 10, 8),
        datetime(2026, 8, 10, 12),
        240,
        None,
    )


@pytest.mark.asyncio
async def test_provider_maps_sdk_result_to_existing_contract():
    client = RZDClient(config(), sdk_factory=lambda **_: FakeRZD())
    provider = RZDAvailabilityProvider(client, config())
    result = await provider.check_segment(
        segment(),
        RouteSearchRequest(
            origin="Москва",
            destination="Петербург",
            departure_date="2026-08-10",
            passengers=2,
        ),
    )
    assert result.status == AvailabilityStatus.CONFIRMED
    assert result.provider == "rzd"
    assert result.available_places_count == 2


class BrokenClient:
    async def search(self, *args, **kwargs):
        raise TimeoutError("RZD timed out")


@pytest.mark.asyncio
async def test_provider_failure_is_unconfirmed_and_never_escapes():
    result = await RZDAvailabilityProvider(BrokenClient(), config()).check_segment(
        segment(),
        RouteSearchRequest(
            origin="Москва",
            destination="Петербург",
            departure_date="2026-08-10",
            passengers=1,
        ),
    )
    assert result.status == AvailabilityStatus.UNCONFIRMED
    assert result.metadata["provider_error"]["error_type"] == "TimeoutError"
