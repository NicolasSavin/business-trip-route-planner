from dataclasses import dataclass, field
from datetime import date, datetime
import time

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
from app.providers.rzd_availability.exceptions import RZDAvailabilityError


@dataclass
class SDKStation:
    code: str
    name: str


@dataclass
class CarGroup:
    type: str = "coupe"
    place_quantity: int = 2


@dataclass
class TrainRoute:
    number: str = "008С"
    departure_time: datetime = datetime(2026, 8, 10, 8)
    arrival_time: datetime = datetime(2026, 8, 10, 12)
    min_price: float = 2500
    car_groups: list[CarGroup] = field(default_factory=lambda: [CarGroup()])
    raw: dict = field(default_factory=dict)


class FakeRZD:
    def __init__(self):
        self.station_calls = 0
        self.search_calls = 0

        self.search_kwargs = None
        self.search_route = None

    def find_stations(self, query):
        self.station_calls += 1
        return [SDKStation("2000000" if query == "Москва" else "2004000", query)]

    def search_tickets(self, origin, destination, departure_date, **kwargs):
        self.search_calls += 1
        self.search_route = (origin, destination)
        self.search_kwargs = kwargs
        return [TrainRoute()]


def config(**kwargs):
    return RZDAvailabilityConfig(enabled=True, retries=0, **kwargs)


@pytest.mark.asyncio
async def test_client_uses_static_codes_and_caches_identical_searches():
    sdk = FakeRZD()
    client = RZDClient(config(), sdk_factory=lambda _: sdk)
    first = await client.search("Москва", "Петербург", date(2026, 8, 10), 2)
    second = await client.search("Москва", "Петербург", date(2026, 8, 10), 2)
    assert first is second
    assert first.trains[0].available_seats == 2
    assert sdk.search_kwargs == {"adults": 2, "children": 0}
    assert sdk.station_calls == 0
    assert sdk.search_calls == 1
    assert sdk.search_route == ("2000000", "2004000")


@pytest.mark.asyncio
async def test_explicit_codes_fully_bypass_station_lookup():
    sdk = FakeRZD()
    client = RZDClient(config(), sdk_factory=lambda _: sdk)

    await client.search(
        "Неизвестный пункт A",
        "Неизвестный пункт B",
        date(2026, 8, 10),
        origin_code="2000000",
        destination_code="2004000",
        skip_station_lookup=True,
    )

    assert sdk.station_calls == 0
    assert sdk.search_calls == 1


@pytest.mark.asyncio
async def test_station_lookup_timeout_does_not_affect_code_search():
    sdk = SlowRZD("origin_station_lookup")
    client = RZDClient(
        config(station_lookup_timeout_seconds=0.001), sdk_factory=lambda _: sdk
    )

    result = await client.search(
        "A",
        "B",
        date(2026, 8, 10),
        origin_code="2000000",
        destination_code="2004000",
    )

    assert result.trains
    assert sdk.station_calls == 0


@pytest.mark.asyncio
async def test_yandex_city_code_is_not_assumed_to_be_express_code_and_cache_wins():
    sdk = FakeRZD()
    client = RZDClient(config(), sdk_factory=lambda _: sdk)

    resolution = await client.resolve_station_code("Москва", provider_code="c213")

    assert resolution.station.code == "2000000"
    assert resolution.source == "cache"
    assert not resolution.sdk_lookup_used


class SlowRZD(FakeRZD):
    def __init__(self, slow_stage):
        super().__init__()
        self.slow_stage = slow_stage

    def find_stations(self, query):
        stage = (
            "origin_station_lookup"
            if query in {"Москва", "Origin"}
            else "destination_station_lookup"
        )
        if self.slow_stage == stage:
            time.sleep(0.05)
        return super().find_stations(query)

    def search_tickets(self, *args, **kwargs):
        if self.slow_stage == "ticket_search":
            time.sleep(0.05)
        return super().search_tickets(*args, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    ["origin_station_lookup", "destination_station_lookup", "ticket_search"],
)
async def test_client_timeout_identifies_sdk_stage(stage):
    sdk = SlowRZD(stage)
    client = RZDClient(
        config(station_lookup_timeout_seconds=0.01, ticket_search_timeout_seconds=0.01),
        sdk_factory=lambda _: sdk,
    )

    with pytest.raises(
        RZDAvailabilityError, match=f"rzd_stage_timeout:{stage}"
    ) as error:
        await client.search("Origin", "Destination", date(2026, 8, 10))

    assert error.value.stage == stage
    assert error.value.elapsed_ms is not None


@pytest.mark.asyncio
async def test_stop_after_stage_returns_intermediate_result_without_later_calls():
    sdk = FakeRZD()
    client = RZDClient(config(), sdk_factory=lambda _: sdk)

    result = await client.search(
        "Origin",
        "Destination",
        date(2026, 8, 10),
        stop_after_stage="origin_station_lookup",
    )

    assert result["stage"] == "origin_station_lookup"
    assert result["result"]["origin_station"].name == "Origin"
    assert "origin_station_lookup" in result["timings"]
    assert sdk.station_calls == 1
    assert sdk.search_calls == 0


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
    client = RZDClient(config(), sdk_factory=lambda _: FakeRZD())
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
