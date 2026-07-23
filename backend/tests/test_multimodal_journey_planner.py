from datetime import date, datetime, timedelta
import pytest

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
    assert "Источник расписаний не подтверждает наличие и расположение мест" in partial[0].availability.warnings
    assert summary.confirmed_routes == 0
    assert summary.partially_confirmed_routes == 1
    assert summary.rejected_routes == 0

class TutuProviderErrorClient:
    def __init__(self, messages):
        self.messages = messages
    async def check_segment(self, segment, request):
        from app.availability.journey import SegmentAvailabilityResult
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

from app.availability.journey import SegmentAvailabilityResult
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
