from datetime import date, datetime, timedelta
import pytest

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityCache, SegmentAvailabilityResult
from app.availability.seats import BerthPosition, RailwayPlace, SeatAllocationService, SeatPreferences
from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.models.routes import RouteSearchRequest, SeatPreferencesRequest
from app.providers.yandex.mapper import YandexRaspMapper
from app.services.multimodal_journey_planner import MultimodalJourneyPlanner
from app.services.route_search import RouteSearchService
from app.services.segment_enrichment import SegmentEnrichmentService

DAY = date(2026, 7, 28)

def dt(hour, day_offset=0):
    return datetime(2026, 7, 28 + day_offset, hour)

def seg(id, origin, destination, dep, arr, seats=4, ttype=TransportType.TRAIN, klass=TransportClass.COUPE, number=None, places=None):
    oc, dc = City(origin), City(destination)
    return TransportSegment(id=id, provider="mock", carrier=Carrier("c", "Carrier"), transport_type=ttype, transport_class=klass, vehicle_number=number or id, origin_city=oc, origin_station=Station(f"{origin}-{ttype.value}", f"{origin} station", oc), destination_city=dc, destination_station=Station(f"{destination}-{ttype.value}", f"{destination} station", dc), departure_datetime=dep, arrival_datetime=arr, duration_minutes=int((arr-dep).total_seconds()//60), available_seats=seats, metadata={"places": places or []})

class Provider:
    def __init__(self, segments): self.segments = segments
    def get_segments(self, *_args, **_kwargs): return self.segments

def req(**kw):
    data = dict(origin="A", destination="C", departure_date=DAY, passengers=2, allowed_transport=["train", "bus"], max_transfers=1, minimum_transfer_minutes=30, maximum_transfer_minutes=240, strict_availability=True)
    data.update(kw)
    return RouteSearchRequest(**data)

def test_direct_train_confirmed():
    planner = MultimodalJourneyPlanner(Provider([seg("ac", "A", "C", dt(8), dt(12), seats=2)]))
    routes, partial, rejected, summary = planner.search(req(max_transfers=0))
    assert len(routes) == 1
    assert routes[0].availability.status == AvailabilityStatus.CONFIRMED
    assert summary.confirmed_routes == 1

def test_direct_train_unavailable_is_rejected_under_strict_availability():
    planner = MultimodalJourneyPlanner(Provider([seg("ac", "A", "C", dt(8), dt(12), seats=1)]))
    routes, partial, rejected, _ = planner.search(req(max_transfers=0))
    assert routes == []
    assert rejected[0].availability.status == AvailabilityStatus.UNAVAILABLE

def test_train_train_and_train_bus_candidates_are_built():
    segments = [seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(10), dt(12)), seg("bd", "B", "C", dt(11), dt(13), ttype=TransportType.BUS, klass=TransportClass.SEATED)]
    planner = MultimodalJourneyPlanner(Provider(segments))
    routes, _, _, _ = planner.search(req())
    combos = {tuple(s.transport_type for s in option.route.segments) for option in routes}
    assert (TransportType.TRAIN, TransportType.TRAIN) in combos
    assert (TransportType.TRAIN, TransportType.BUS) in combos

def test_transfer_too_short_and_too_long_are_rejected():
    short = MultimodalJourneyPlanner(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(9), dt(11))]))
    assert short.search(req())[0] == []
    long = MultimodalJourneyPlanner(Provider([seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(16), dt(18))]))
    assert long.search(req(maximum_transfer_minutes=120))[0] == []

def test_midnight_transfer_is_supported_when_allowed():
    planner = MultimodalJourneyPlanner(Provider([seg("ab", "A", "B", dt(22), dt(23)), seg("bc", "B", "C", dt(1, 1), dt(3, 1))]))
    assert planner.search(req(allow_overnight_transfer=True))[0]
    assert planner.search(req(allow_overnight_transfer=False))[0] == []

def test_lower_berths_same_compartment_required_on_every_train():
    def explicit(items): return [{**item, "explicitly_confirmed": True, "source": "rzd_explicit_place_details"} for item in items]
    places_one = explicit([{"place_number":"1","carriage_number":"1","berth_position":"lower","compartment_number":"1"},{"place_number":"3","carriage_number":"1","berth_position":"lower","compartment_number":"1"}])
    places_bad = explicit([{"place_number":"1","carriage_number":"1","berth_position":"lower","compartment_number":"1"},{"place_number":"5","carriage_number":"1","berth_position":"lower","compartment_number":"2"}])
    segments = [seg("ab", "A", "B", dt(8), dt(9)), seg("bc", "B", "C", dt(10), dt(12))]
    planner = MultimodalJourneyPlanner(Provider(segments))
    request = req(seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True, require_same_carriage=True, strict_preferences=True))
    results = tuple(planner._apply_railway_preferences(segment, request, SegmentAvailabilityResult(segment_id=segment.id, provider="rzd", status=AvailabilityStatus.PARTIALLY_CONFIRMED, metadata={"places": places})) for segment, places in zip(segments, (places_one, places_bad)))
    from app.availability.journey import aggregate_journey_availability
    assert results[0].status == AvailabilityStatus.CONFIRMED
    assert results[1].status == AvailabilityStatus.UNAVAILABLE
    assert aggregate_journey_availability(results).status == AvailabilityStatus.UNAVAILABLE


def test_aggregate_lower_quantity_does_not_confirm_concrete_lower_places():
    segment = seg("ac", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(
        max_transfers=0,
        seat_preferences=SeatPreferencesRequest(
            berth_preference="lower_only", require_same_compartment=False
        ),
    )
    provider_result = SegmentAvailabilityResult(
        segment_id=segment.id,
        provider="rzd",
        status=AvailabilityStatus.PARTIALLY_CONFIRMED,
        available_places_count=10,
        metadata={"lower_places_count": 2, "places": []},
    )

    result = planner._apply_railway_preferences(segment, request, provider_result)

    assert result.status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert result.seat_preferences_status == AvailabilityStatus.UNKNOWN
    assert result.metadata["lower_berths_confirmed"] is False
    assert result.selected_places == ()


def test_two_explicit_lower_places_in_one_rzd_compartment_are_confirmed_with_evidence():
    segment = seg("ac", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(max_transfers=0, seat_preferences=SeatPreferencesRequest(
        berth_preference="lower_only", require_same_compartment=True, require_same_carriage=True
    ))
    places = [
        {"place_number": "11", "carriage_number": "07", "compartment_number": "3", "berth_position": "lower", "explicitly_confirmed": True, "source": "rzd_explicit_place_details"},
        {"place_number": "13", "carriage_number": "07", "compartment_number": "3", "berth_position": "lower", "explicitly_confirmed": True, "source": "rzd_explicit_place_details"},
    ]
    provider_result = SegmentAvailabilityResult(
        segment_id=segment.id, provider="rzd", status=AvailabilityStatus.PARTIALLY_CONFIRMED,
        available_places_count=20, metadata={"places": places},
    )

    result = planner._apply_railway_preferences(segment, request, provider_result)

    assert result.status == AvailabilityStatus.CONFIRMED
    assert result.seats_confirmed is True
    assert result.seat_preferences_status == AvailabilityStatus.CONFIRMED
    assert result.selected_places == ("11", "13")
    assert result.selected_carriages == ("07",)
    assert result.selected_compartments == ("3",)
    assert [item["place_number"] for item in result.metadata["selected_place_evidence"]] == ["11", "13"]
    assert all(item["train_number"] == "ac" and item["explicitly_confirmed"] for item in result.metadata["selected_place_evidence"])
    assert result.lower_berths_check.status.value == "confirmed"
    assert result.same_compartment_check.status.value == "confirmed"


def test_missing_compartment_is_unknown_not_confirmed():
    segment = seg("ac", "A", "C", dt(8), dt(12), places=[
        {"place_number": "1", "carriage_number": "07", "berth_position": "lower"},
        {"place_number": "3", "carriage_number": "07", "berth_position": "lower"},
    ])
    planner = MultimodalJourneyPlanner(Provider([segment]))
    result = planner._apply_railway_preferences(segment, req(max_transfers=0, seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True)), SegmentAvailabilityResult(segment_id="ac", provider="rzd", status=AvailabilityStatus.PARTIALLY_CONFIRMED, metadata=segment.metadata))
    assert result.status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert result.same_compartment_check.status.value == "unknown"


def test_seated_sapsan_requirements_are_not_applicable():
    segment = seg("sap", "A", "C", dt(8), dt(12), klass=TransportClass.SEATED, number="Сапсан")
    planner = MultimodalJourneyPlanner(Provider([segment]))
    result = planner._apply_railway_preferences(segment, req(max_transfers=0, seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True)), SegmentAvailabilityResult(segment_id="sap", provider="rzd", status=AvailabilityStatus.CONFIRMED, available_places_count=10))
    assert result.status == AvailabilityStatus.UNAVAILABLE
    assert result.lower_berths_check.status.value == "not_applicable"
    assert result.same_compartment_check.status.value == "not_applicable"


def test_non_strict_seated_sapsan_is_partial_but_requirements_stay_not_applicable():
    segment = seg("sap", "A", "C", dt(8), dt(12), klass=TransportClass.SEATED, number="Сапсан")
    planner = MultimodalJourneyPlanner(Provider([segment]))
    result = planner._apply_railway_preferences(segment, req(max_transfers=0, seat_preferences=SeatPreferencesRequest(
        berth_preference="lower_only", require_same_compartment=True, strict_preferences=False)),
        SegmentAvailabilityResult(segment_id="sap", provider="rzd", status=AvailabilityStatus.CONFIRMED, available_places_count=10))
    assert result.status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert result.seat_preferences_status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert result.lower_berths_check.status.value == "not_applicable"
    assert result.same_compartment_check.status.value == "not_applicable"


def test_general_allocator_keeps_lower_and_upper_preferences_advisory_when_inventory_is_insufficient():
    places = [
        RailwayPlace("rzd", "1", "1", TransportClass.COUPE, berth_position=BerthPosition.LOWER),
        RailwayPlace("rzd", "2", "1", TransportClass.COUPE, berth_position=BerthPosition.UPPER),
    ]
    lower = SeatAllocationService().match(places, SeatPreferences(passengers=2, prefer_lower=True))
    upper = SeatAllocationService().match(places, SeatPreferences(passengers=2, prefer_upper=True))
    assert lower.matches_preferences and {p.place_number for p in lower.selected_places} == {"1", "2"}
    assert upper.matches_preferences and {p.place_number for p in upper.selected_places} == {"1", "2"}


def placement_result(places, passengers=2, provider="rzd", lower=True, compartment=True, **preference_overrides):
    segment = seg("ac", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([segment]))
    normalized = [{**place, "explicitly_confirmed": True, "source": "rzd_explicit_place_details"} for place in places]
    preferences = {"berth_preference": "lower_only" if lower else "any", "require_same_compartment": compartment}
    preferences.update(preference_overrides)
    request = req(max_transfers=0, passengers=passengers, seat_preferences=SeatPreferencesRequest(**preferences))
    return planner._apply_railway_preferences(segment, request, SegmentAvailabilityResult(
        segment_id="ac", provider=provider, status=AvailabilityStatus.PARTIALLY_CONFIRMED, metadata={"places": normalized}))


@pytest.mark.parametrize("places", [
    [{"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"}, {"place_number":"3","carriage_number":"1","compartment_number":"2","berth_position":"lower"}],
    [{"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"}, {"place_number":"3","carriage_number":"2","compartment_number":"1","berth_position":"lower"}],
    [{"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"}, {"place_number":"2","carriage_number":"1","compartment_number":"1","berth_position":"upper"}],
])
def test_concrete_places_reject_different_compartments_carriages_or_upper(places):
    result = placement_result(places)
    assert result.status == AvailabilityStatus.UNAVAILABLE
    assert not result.seats_confirmed


def test_not_enough_lower_places_is_rejected():
    result = placement_result([{"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"}], compartment=False)
    assert result.lower_berths_check.status.value == "rejected"


def test_valid_group_ignores_unrelated_place_without_compartment():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"3","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"9","carriage_number":"1","compartment_number":None,"berth_position":"upper"},
    ])
    assert result.status == AvailabilityStatus.CONFIRMED


def test_lower_confirmed_while_compartment_is_unknown():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":None,"berth_position":"lower"},
        {"place_number":"3","carriage_number":"1","compartment_number":None,"berth_position":"lower"},
    ])
    assert result.lower_berths_check.status.value == "confirmed"
    assert result.same_compartment_check.status.value == "unknown"


def test_arbitrary_metadata_and_non_rzd_places_are_not_explicit_evidence():
    raw = [{"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"}, {"place_number":"3","carriage_number":"1","compartment_number":"1","berth_position":"lower"}]
    segment = seg("ac", "A", "C", dt(8), dt(12), places=raw)
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(max_transfers=0, seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True))
    arbitrary = planner._apply_railway_preferences(segment, request, SegmentAvailabilityResult(segment_id="ac", provider="rzd", status=AvailabilityStatus.PARTIALLY_CONFIRMED, metadata={"places": raw}))
    other = placement_result(raw, provider="tutu")
    assert arbitrary.lower_berths_check.status.value == "unknown"
    assert other.lower_berths_check.status.value == "unknown"
    assert other.metadata["selected_place_evidence"] == ()


def test_upper_only_selects_only_explicit_upper_places():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"2","carriage_number":"1","compartment_number":"1","berth_position":"upper"},
        {"place_number":"4","carriage_number":"1","compartment_number":"1","berth_position":"upper"},
    ], lower=False, compartment=False, berth_preference="upper_only")
    assert result.status == AvailabilityStatus.CONFIRMED
    assert result.selected_places == ("2", "4")


def test_require_empty_compartment_rejects_explicitly_occupied_compartment():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"3","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"2","carriage_number":"1","compartment_number":"1","berth_position":"upper", "is_available":False},
    ], require_empty_compartment=True)
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_require_adjacent_rejects_non_adjacent_places():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"3","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
    ], lower=False, compartment=False, require_adjacent=True)
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_exclude_side_berths_rejects_side_only_inventory():
    result = placement_result([
        {"place_number":"37","carriage_number":"1","compartment_number":"1","berth_position":"lower", "is_side":True},
        {"place_number":"39","carriage_number":"1","compartment_number":"1","berth_position":"lower", "is_side":True},
    ], exclude_side_berths=True)
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_gender_restriction_rejects_incompatible_places():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower", "gender":"male"},
        {"place_number":"3","carriage_number":"1","compartment_number":"1","berth_position":"lower", "gender":"male"},
    ], gender="female")
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_standalone_same_carriage_is_enforced_and_can_be_disabled():
    places = [
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"3","carriage_number":"2","compartment_number":"1","berth_position":"lower"},
    ]
    rejected = placement_result(places, lower=False, compartment=False, require_same_carriage=True)
    confirmed = placement_result(places, lower=False, compartment=False, require_same_carriage=False)
    assert rejected.status == AvailabilityStatus.UNAVAILABLE
    assert confirmed.status == AvailabilityStatus.CONFIRMED


def test_non_strict_rejected_preferences_are_partially_confirmed():
    places = [{"place_number":"2","carriage_number":"1","compartment_number":"1","berth_position":"upper"}]
    strict = placement_result(places, passengers=2, compartment=False, strict_preferences=True)
    advisory = placement_result(places, passengers=2, compartment=False, strict_preferences=False)
    assert strict.status == AvailabilityStatus.UNAVAILABLE
    assert strict.selected_places == ()
    assert strict.metadata["selected_place_evidence"] == ()
    assert advisory.status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert advisory.seat_preferences_status == AvailabilityStatus.PARTIALLY_CONFIRMED


def test_preferred_class_and_allow_split_group_are_applied():
    places = [
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower", "carriage_type":"coupe"},
        {"place_number":"3","carriage_number":"2","compartment_number":"1","berth_position":"lower", "carriage_type":"coupe"},
    ]
    wrong_class = placement_result(places, lower=False, compartment=False, preferred_classes=["platzkart"], require_same_carriage=False)
    split = placement_result(places, lower=False, compartment=False, preferred_classes=["coupe"], require_same_carriage=True, allow_split_group=True)
    assert wrong_class.status == AvailabilityStatus.UNAVAILABLE
    assert wrong_class.seat_preferences_status == AvailabilityStatus.UNAVAILABLE
    assert split.status == AvailabilityStatus.CONFIRMED


def test_maximum_compartments_is_enforced():
    result = placement_result([
        {"place_number":"1","carriage_number":"1","compartment_number":"1","berth_position":"lower"},
        {"place_number":"5","carriage_number":"1","compartment_number":"2","berth_position":"lower"},
    ], lower=False, compartment=False, require_same_carriage=True, maximum_compartments=1)
    assert result.status == AvailabilityStatus.UNAVAILABLE


def test_yandex_schedule_enriched_by_rzd_confirms_coupe_lower_group():
    from app.providers.rzd_availability.mapper import map_train, to_segment_result
    schedule = yandex_moscow_petersburg_schedule()
    train = map_train({"number": "022А", "carriages": [{"number": "07", "type": "coupe", "places": [
        {"number": "11", "berthPosition": "lower", "compartmentNumber": "3"},
        {"number": "13", "berthPosition": "lower", "compartmentNumber": "3"},
    ]}]})
    base = to_segment_result(schedule, train, passengers=2, preferences_requested=True)
    planner = MultimodalJourneyPlanner(Provider([schedule]))
    result = planner._apply_railway_preferences(schedule, req(
        origin="Москва", destination="Санкт-Петербург", max_transfers=0, passengers=2,
        seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True)), base)
    assert result.lower_berths_check.status.value == "confirmed"
    assert result.same_compartment_check.status.value == "confirmed"
    assert {item["carriage_type"] for item in result.metadata["selected_place_evidence"]} == {"coupe"}


def test_aggregate_lower_quantity_cannot_confirm_same_compartment():
    segment = seg("ac", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(
        max_transfers=0,
        seat_preferences=SeatPreferencesRequest(
            berth_preference="lower_only", require_same_compartment=True
        ),
    )
    provider_result = SegmentAvailabilityResult(
        segment_id=segment.id,
        provider="rzd",
        status=AvailabilityStatus.PARTIALLY_CONFIRMED,
        available_places_count=10,
        metadata={"lower_places_count": 2, "places": []},
    )

    result = planner._apply_railway_preferences(segment, request, provider_result)

    assert result.status == AvailabilityStatus.PARTIALLY_CONFIRMED
    assert result.seat_preferences_status == AvailabilityStatus.UNKNOWN
    assert result.metadata["lower_berths_confirmed"] is False
    assert result.metadata["same_compartment_confirmed"] is False
    assert result.selected_places == ()

def test_tutu_enrichment_matches_only_the_same_train():
    schedule = seg("s", "A", "C", dt(8), dt(12), number="016М")
    right = seg("tutu-right", "A", "C", dt(8), dt(12), number="016М")
    wrong = seg("tutu-wrong", "A", "C", dt(8), dt(12), number="999Х")
    service = SegmentEnrichmentService()
    assert service.match(schedule, [wrong, right]).availability_segment_id == "tutu-right"

def test_cache_prevents_repeated_availability_lookup():
    planner = MultimodalJourneyPlanner(Provider([seg("ac", "A", "C", dt(8), dt(12), seats=2)]))
    request = req(max_transfers=0)
    planner.search(request)
    before = dict(planner.cache._items)
    planner.search(request)
    assert planner.cache._items.keys() == before.keys()

def test_yandex_schedule_only_unknown_seats_is_unconfirmed_not_rejected_when_not_strict():
    segment = seg("yx", "A", "C", dt(8), dt(12), seats=None, klass=None)
    segment = segment.__class__(**{**segment.__dict__, "provider": "yandex_rasp", "metadata": {"availability_unknown": True, "source": "Яндекс Расписания"}})
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(max_transfers=0, strict_availability=False, seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True))

    routes, partial, rejected, summary = planner.search(request)

    assert routes == partial
    assert len(routes) == 1
    assert rejected == []
    assert routes[0].availability.status == AvailabilityStatus.UNCONFIRMED
    assert routes[0].availability.segment_results[0].available_places_count is None
    assert "Источник расписаний не подтверждает наличие и расположение мест" in routes[0].availability.warnings
    assert summary.partially_confirmed_routes == 1
    assert summary.rejected_routes == 0


def test_yandex_schedule_only_strict_is_not_confirmed_and_explains_unavailable_data():
    segment = seg("yx", "A", "C", dt(8), dt(12), seats=None, klass=None)
    segment = segment.__class__(**{**segment.__dict__, "provider": "yandex_rasp", "metadata": {"availability_unknown": True, "source": "Яндекс Расписания"}})
    planner = MultimodalJourneyPlanner(Provider([segment]))
    request = req(max_transfers=0, strict_availability=True, seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True))

    routes, partial, rejected, summary = planner.search(request)

    assert routes == []
    assert len(partial) == 1
    assert rejected == []
    assert partial[0].availability.status == AvailabilityStatus.UNCONFIRMED
    assert "нет мест" not in partial[0].explanation.lower()
    assert partial[0].explanation == "Расписание найдено, наличие мест не подтверждено."
    assert "Источник мест не предоставил номера и явное подтверждение двух нижних мест." in partial[0].warnings
    assert "Источник мест не предоставил номер вагона и купе для размещения всех сотрудников вместе." in partial[0].warnings
    assert "Источник расписаний не подтверждает наличие и расположение мест" in partial[0].availability.warnings
    assert summary.confirmed_routes == 0
    assert summary.partially_confirmed_routes == 1
    assert summary.rejected_routes == 0


def yandex_moscow_petersburg_schedule():
    payload = {"segments": [{
        "from": {"code": "s2000009", "title": "Москва Октябрьская", "settlement": {"title": "Москва"}},
        "to": {"code": "s2004001", "title": "Санкт-Петербург-Главн.", "settlement": {"title": "Санкт-Петербург"}},
        "departure": "2026-07-28T00:25:00+03:00",
        "arrival": "2026-07-28T08:53:00+03:00",
        "thread": {"uid": "022A", "number": "022А", "title": "Москва — Санкт-Петербург", "transport_type": "train"},
    }]}
    return YandexRaspMapper().to_segments(payload)[0]


def test_api_preserves_direct_yandex_unknown_availability_when_not_confirmed_only():
    service = RouteSearchService(Provider([yandex_moscow_petersburg_schedule()]))
    response = service.search_response(req(
        origin="Москва", destination="Санкт-Петербург", max_transfers=1,
        strict_availability=False, allowed_transport=["train"],
    ))

    assert len(response.routes) == 1
    assert response.routes[0].transfers_count == 0
    assert response.routes[0].segments[0].number == "022А"
    assert response.routes[0].availability.is_available is None


def test_api_confirmed_only_hides_direct_yandex_unknown_availability():
    service = RouteSearchService(Provider([yandex_moscow_petersburg_schedule()]))
    response = service.search_response(req(
        origin="Москва", destination="Санкт-Петербург", max_transfers=1,
        strict_availability=True, allowed_transport=["train"],
    ))

    assert response.routes == []
    assert len(response.partially_confirmed_routes) == 1
    assert response.partially_confirmed_routes[0].transfers_count == 0

class TutuProviderErrorClient:
    def __init__(self, messages):
        self.messages = messages
    async def check_segment(self, segment, request):
        from app.availability.journey import SegmentAvailabilityResult, aggregate_journey_availability
        message = self.messages.get(segment.id, "Location suggestion not found: Рязань")
        return SegmentAvailabilityResult(
            segment_id=segment.id,
            provider="tutu_playwright",
            status=AvailabilityStatus.UNCONFIRMED,
            schedule_confirmed=True,
            reasons=("Расписание найдено, проверка мест через Туту не выполнена",),
            warnings=("Расписание найдено, проверка мест через Туту не выполнена",),
            metadata={"provider_error": {"code":"availability_enrichment_failed", "message": message, "error_type":"TutuDiagnosticError", "details":{"segment_id": segment.id}}},
        )


def test_tutu_provider_error_preserves_yandex_route_and_summary_error():
    segment = seg("yx", "A", "C", dt(8), dt(12), seats=None, klass=None, number="6994")
    segment = segment.__class__(**{**segment.__dict__, "provider": "yandex_rasp", "metadata": {"availability_unknown": True, "source": "Яндекс Расписания"}})
    planner = MultimodalJourneyPlanner(Provider([segment]))
    planner.tutu_playwright = TutuProviderErrorClient({"yx": "Location suggestion not found: Рязань"})

    routes, partial, rejected, summary = planner.search(req(max_transfers=0, strict_availability=False))

    assert routes == partial
    assert len(routes) == 1
    assert rejected == []
    assert routes[0].availability.status == AvailabilityStatus.PARTIALLY_CONFIRMED or routes[0].availability.status == AvailabilityStatus.UNCONFIRMED
    assert "tutu_playwright" in summary.provider_errors
    assert summary.provider_errors["tutu_playwright"]["errors"][0]["message"] == "Location suggestion not found: Рязань"
    assert "yandex_rasp" not in summary.provider_errors
    assert "Недостаточно мест" not in routes[0].explanation


def test_multiple_tutu_segment_errors_are_not_overwritten_and_warnings_deduped():
    first = seg("ab", "A", "B", dt(8), dt(9), seats=None)
    second = seg("bc", "B", "C", dt(10), dt(12), seats=None)
    segments = [
        first.__class__(**{**first.__dict__, "metadata": {"availability_unknown": True}}),
        second.__class__(**{**second.__dict__, "metadata": {"availability_unknown": True}}),
    ]
    planner = MultimodalJourneyPlanner(Provider(segments))
    planner.tutu_playwright = TutuProviderErrorClient({"ab": "first", "bc": "second"})

    routes, partial, rejected, summary = planner.search(req(strict_availability=False))

    errors = summary.provider_errors["tutu_playwright"]["errors"]
    assert [e["message"] for e in errors] == ["first", "second"]
    assert len(routes[0].warnings) == len(set(routes[0].warnings))

from app.availability.journey import SegmentAvailabilityResult, aggregate_journey_availability
from app.domain import Route, RouteOption
import asyncio
import time


def option_with(*segments):
    return RouteOption(route=Route(tuple(segments)), score=0)


class AsyncTutuClient:
    def __init__(self, delay=0.01, statuses=None):
        self.delay = delay
        self.statuses = statuses or {}
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.cancelled = 0
    def available(self):
        return True
    async def check_segment(self, segment, request):
        self.calls.append(segment.id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            status = self.statuses.get(segment.id, AvailabilityStatus.UNCONFIRMED)
            return SegmentAvailabilityResult(
                segment_id=segment.id,
                provider="tutu_playwright",
                status=status,
                schedule_confirmed=True,
                seats_confirmed=status == AvailabilityStatus.CONFIRMED,
                passengers_supported=status == AvailabilityStatus.CONFIRMED,
                available_places_count=2 if status == AvailabilityStatus.CONFIRMED else None,
                warnings=() if status == AvailabilityStatus.CONFIRMED else ("Расписание найдено, проверка мест через Туту не выполнена",),
                metadata={} if status == AvailabilityStatus.CONFIRMED else {"provider_error": {"code": "availability_enrichment_failed", "message": "timeout", "error_type": "TimeoutError"}},
            )
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


class StubRZDClient:
    def __init__(self, status):
        self.status = status
        self.calls = []
    def available(self):
        return True
    async def check_segment(self, segment, request):
        self.calls.append(segment.id)
        return SegmentAvailabilityResult(
            segment_id=segment.id, provider="rzd", status=self.status,
            schedule_confirmed=True, seats_confirmed=self.status == AvailabilityStatus.CONFIRMED,
            reasons=("РЖД не вернул поезд для данного участка и даты",) if self.status == AvailabilityStatus.UNKNOWN else (),
            metadata={"rzd_error_code": 310} if self.status == AvailabilityStatus.UNKNOWN else {},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_status", [AvailabilityStatus.CONFIRMED, AvailabilityStatus.UNAVAILABLE])
async def test_conclusive_rzd_result_does_not_start_tutu_fallback(primary_status):
    segment = seg("rail", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.rzd_availability = StubRZDClient(primary_status)
    planner.tutu_playwright = AsyncTutuClient(statuses={"rail": AvailabilityStatus.CONFIRMED})
    await planner._attach_journey_availability([option_with(segment)], req(strict_availability=False))
    assert planner.tutu_playwright.calls == []


@pytest.mark.asyncio
async def test_tutu_confirmed_replaces_rzd_error_310_unknown_and_maps_seats():
    segment = seg("rail", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.rzd_availability = StubRZDClient(AvailabilityStatus.UNKNOWN)
    planner.tutu_playwright = AsyncTutuClient(statuses={"rail": AvailabilityStatus.CONFIRMED})
    checked = await planner._attach_journey_availability([option_with(segment)], req(strict_availability=False))
    result = checked[0].availability.segment_results[0]
    assert planner.tutu_playwright.calls == ["rail"]
    assert result.provider == "tutu_playwright"
    assert result.status == AvailabilityStatus.CONFIRMED
    assert result.available_places_count == 2


@pytest.mark.asyncio
async def test_both_unknown_preserve_primary_and_fallback_reasons():
    segment = seg("rail", "A", "C", dt(8), dt(12), seats=None)
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.rzd_availability = StubRZDClient(AvailabilityStatus.UNKNOWN)
    planner.tutu_playwright = AsyncTutuClient()
    checked = await planner._attach_journey_availability([option_with(segment)], req(strict_availability=False))
    result = checked[0].availability.segment_results[0]
    assert result.status == AvailabilityStatus.UNKNOWN
    assert result.metadata["rzd_error_code"] == 310
    assert result.metadata["fallback_provider_error"]["error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_tutu_enrichment_budget_returns_unconfirmed_for_slow_segments(monkeypatch):
    import app.services.multimodal_journey_planner as module
    monkeypatch.setattr(module, "TUTU_MAX_JOURNEYS_TO_ENRICH", 3)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_CONCURRENCY", 2)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", 0.05)
    segments = [seg(f"s{i}", "A", "C", dt(8), dt(12), seats=None).__class__(**{**seg(f"s{i}", "A", "C", dt(8), dt(12), seats=None).__dict__, "metadata": {"availability_unknown": True}}) for i in range(6)]
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.tutu_playwright = AsyncTutuClient(delay=0.2)

    started = time.monotonic()
    checked = await planner._attach_journey_availability([option_with(*segments[:2]), option_with(*segments[2:4]), option_with(*segments[4:6])], req(strict_availability=False))

    assert time.monotonic() - started < 0.2
    assert all(o.availability.status == AvailabilityStatus.UNCONFIRMED for o in checked)
    assert planner.tutu_playwright.cancelled > 0


@pytest.mark.asyncio
async def test_tutu_enrichment_deduplicates_same_segment(monkeypatch):
    import app.services.multimodal_journey_planner as module
    monkeypatch.setattr(module, "TUTU_MAX_JOURNEYS_TO_ENRICH", 3)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", 1)
    shared = seg("shared", "A", "C", dt(8), dt(12), seats=None)
    shared = shared.__class__(**{**shared.__dict__, "metadata": {"availability_unknown": True}})
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.tutu_playwright = AsyncTutuClient(delay=0)

    await planner._attach_journey_availability([option_with(shared), option_with(shared), option_with(shared)], req(strict_availability=False))

    assert planner.tutu_playwright.calls == ["shared"]


@pytest.mark.asyncio
async def test_one_tutu_success_and_other_timeouts_are_reported(monkeypatch):
    import app.services.multimodal_journey_planner as module
    monkeypatch.setattr(module, "TUTU_MAX_JOURNEYS_TO_ENRICH", 3)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", 0.05)
    first = seg("ok", "A", "C", dt(8), dt(12), seats=None).__class__(**{**seg("ok", "A", "C", dt(8), dt(12), seats=None).__dict__, "metadata": {"availability_unknown": True}})
    slow = seg("slow", "A", "C", dt(9), dt(13), seats=None).__class__(**{**seg("slow", "A", "C", dt(9), dt(13), seats=None).__dict__, "metadata": {"availability_unknown": True}})

    class MixedClient(AsyncTutuClient):
        async def check_segment(self, segment, request):
            self.calls.append(segment.id)
            if segment.id == "ok":
                return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.CONFIRMED, seats_confirmed=True, passengers_supported=True, available_places_count=2)
            await asyncio.sleep(0.2)
            return None

    planner = MultimodalJourneyPlanner(Provider([]))
    planner.tutu_playwright = MixedClient()
    checked = await planner._attach_journey_availability([option_with(first, slow)], req(strict_availability=False))

    results = {r.segment_id: r for r in checked[0].availability.segment_results}
    assert results["ok"].status == AvailabilityStatus.CONFIRMED
    assert results["slow"].metadata["provider_error"]["error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_tutu_enrichment_concurrency_is_limited(monkeypatch):
    import app.services.multimodal_journey_planner as module
    monkeypatch.setattr(module, "TUTU_MAX_JOURNEYS_TO_ENRICH", 3)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_CONCURRENCY", 2)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", 1)
    segments = [seg(f"c{i}", "A", "C", dt(8), dt(12), seats=None).__class__(**{**seg(f"c{i}", "A", "C", dt(8), dt(12), seats=None).__dict__, "metadata": {"availability_unknown": True}}) for i in range(5)]
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.tutu_playwright = AsyncTutuClient(delay=0.02)

    await planner._attach_journey_availability([option_with(*segments)], req(strict_availability=False))

    assert planner.tutu_playwright.max_active <= 2


@pytest.mark.asyncio
async def test_cancelled_tutu_tasks_are_cancelled(monkeypatch):
    import app.services.multimodal_journey_planner as module
    monkeypatch.setattr(module, "TUTU_MAX_JOURNEYS_TO_ENRICH", 1)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_CONCURRENCY", 2)
    monkeypatch.setattr(module, "TUTU_ENRICHMENT_TOTAL_TIMEOUT_SECONDS", 0.01)
    segments = [seg(f"x{i}", "A", "C", dt(8), dt(12), seats=None).__class__(**{**seg(f"x{i}", "A", "C", dt(8), dt(12), seats=None).__dict__, "metadata": {"availability_unknown": True}}) for i in range(2)]
    planner = MultimodalJourneyPlanner(Provider([]))
    planner.tutu_playwright = AsyncTutuClient(delay=0.2)

    await planner._attach_journey_availability([option_with(*segments)], req(strict_availability=False))

    assert planner.tutu_playwright.cancelled == 2

def test_unknown_availability_does_not_emit_not_enough_seats_warning():
    segment = seg("unknown", "A", "C", dt(8), dt(12), seats=None)
    segment = segment.__class__(**{**segment.__dict__, "metadata": {"availability_unknown": True}})
    planner = MultimodalJourneyPlanner(Provider([segment]))

    routes, partial, rejected, _ = planner.search(req(max_transfers=0, strict_availability=False))

    assert routes == partial
    text = " ".join((*routes[0].warnings, routes[0].explanation, *routes[0].availability.warnings, *routes[0].availability.reasons))
    assert "Недостаточно мест" not in text


def test_unavailable_zero_seats_keeps_not_enough_seats_semantics_in_decision_engine():
    from app.decision.engine import DecisionEngine
    from app.services.route_search import RouteSearchService

    planner = MultimodalJourneyPlanner(Provider([seg("zero", "A", "C", dt(8), dt(12), seats=0)]))
    service = RouteSearchService(Provider([]))
    service.planner = planner
    response = service.search_response(req(max_transfers=0), include_unavailable=True)

    summary = DecisionEngine().analyze(response.rejected_routes, passengers=2)[0]
    assert any(item.message == "Недостаточно мест." for item in summary.warnings)


def test_duplicate_provider_errors_are_deduplicated_by_segment_and_error_key():
    segment = seg("dup", "A", "C", dt(8), dt(12), seats=None)
    segment = segment.__class__(**{**segment.__dict__, "metadata": {"availability_unknown": True}})
    planner = MultimodalJourneyPlanner(Provider([segment]))
    error = {"code": "availability_enrichment_failed", "message": "ReadTimeout", "error_type": "ReadTimeout", "details": {"segment_id": "dup"}}
    result = SegmentAvailabilityResult(segment_id="dup", provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, metadata={"provider_error": error})
    option = option_with(segment)
    availability = aggregate_journey_availability((result, result))
    errors = planner._collect_enrichment_errors([option.__class__(**{**option.__dict__, "availability": availability})])

    assert len(errors["tutu_playwright"]["errors"]) == 1
    assert errors["tutu_playwright"]["message"] == "Сервис проверки мест не ответил вовремя. Расписание доступно, наличие мест не подтверждено."
