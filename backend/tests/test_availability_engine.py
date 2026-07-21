from datetime import date, datetime, timedelta

from app.availability import AvailabilityEngine, AvailabilityPolicy, AvailabilityValidator, MockAvailabilityProvider
from app.availability.models import AvailabilityResult
from app.domain import Carrier, City, Route, RouteOption, Station, TransportClass, TransportSegment, TransportType
from app.intelligence.transfers import TransferEngine

DAY = date(2026, 7, 21)


def dt(hour):
    return datetime(2026, 7, 21, hour)


def seg(id, origin="A", destination="B", dep=None, arr=None, seats=5, klass=TransportClass.COUPE):
    dep = dep or dt(8)
    arr = arr or dep + timedelta(hours=1)
    oc, dc = City(origin), City(destination)
    return TransportSegment(
        id=id,
        provider="test",
        carrier=Carrier("c", "Carrier"),
        transport_type=TransportType.TRAIN,
        transport_class=klass,
        vehicle_number=id,
        origin_city=oc,
        origin_station=Station(f"{origin}-s", origin, oc),
        destination_city=dc,
        destination_station=Station(f"{destination}-s", destination, dc),
        departure_datetime=dep,
        arrival_datetime=arr,
        duration_minutes=int((arr - dep).total_seconds() // 60),
        available_seats=seats,
    )


def option(*segments):
    transfers = tuple(TransferEngine().build_transfer(first, second) for first, second in zip(segments, segments[1:]))
    return RouteOption(Route(tuple(segments), transfers), 1.0)


def test_availability_engine_marks_route_available_when_every_segment_has_enough_seats():
    result = AvailabilityEngine().check(option(seg("ab", seats=4), seg("bc", "B", "C", dt(10), dt(11), seats=3)), AvailabilityPolicy.for_group(3))
    assert result.is_available
    assert result.total_available_seats == 3
    assert [item.segment_id for item in result.segment_results] == ["ab", "bc"]


def test_mock_provider_supports_not_enough_no_seats_and_seats_appeared_scenarios():
    route = option(seg("ab", seats=1), seg("bc", "B", "C", dt(10), dt(11), seats=0))
    provider = MockAvailabilityProvider(overrides={"bc": 4})
    result = AvailabilityEngine(provider).check(route, AvailabilityPolicy.for_group(2))
    assert not result.is_available
    assert result.segment_results[0].available_seats == 1
    assert result.segment_results[1].available_seats == 4


def test_availability_policy_can_require_coupe_or_allow_split_group():
    seated = seg("ab", seats=1, klass=TransportClass.SEATED)
    assert not AvailabilityPolicy.coupe_only(1).accepts_class(seated.transport_class)
    split_policy = AvailabilityPolicy.split_group(3)
    assert split_policy.has_enough_seats(1)


def test_availability_validator_checks_segments_transfers_and_total_seats():
    route_option = option(seg("ab", seats=1), seg("bc", "B", "C", dt(10), dt(11), seats=1))
    result = AvailabilityEngine().check(route_option, AvailabilityPolicy.for_group(2))
    warnings = AvailabilityValidator().validate(route_option.route, result, AvailabilityPolicy.for_group(2))
    assert "route does not have enough seats for the full group" in warnings
