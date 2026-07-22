from datetime import date, datetime, timedelta

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityCache
from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.models.routes import RouteSearchRequest, SeatPreferencesRequest
from app.services.multimodal_journey_planner import MultimodalJourneyPlanner
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
    places_one = [{"place_number":"1","carriage_number":"1","berth_position":"lower","compartment_number":"1"},{"place_number":"3","carriage_number":"1","berth_position":"lower","compartment_number":"1"}]
    places_bad = [{"place_number":"1","carriage_number":"1","berth_position":"lower","compartment_number":"1"},{"place_number":"5","carriage_number":"1","berth_position":"lower","compartment_number":"2"}]
    planner = MultimodalJourneyPlanner(Provider([seg("ab", "A", "B", dt(8), dt(9), places=places_one), seg("bc", "B", "C", dt(10), dt(12), places=places_bad)]))
    routes, _, rejected, _ = planner.search(req(seat_preferences=SeatPreferencesRequest(berth_preference="lower_only", require_same_compartment=True, require_same_carriage=True, strict_preferences=True)))
    assert routes == []
    assert rejected[0].availability.status == AvailabilityStatus.UNAVAILABLE

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
