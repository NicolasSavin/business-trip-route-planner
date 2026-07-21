from datetime import date, datetime, timedelta

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.providers.unified import ProviderCapabilities, ProviderHealth, ProviderPriority, ProviderRegistry, UnifiedTransportProvider

DAY = date(2026, 8, 10)


def seg(id, provider="p1", carrier="c", number="42", seats=5):
    origin, destination = City("Москва"), City("Казань")
    dep = datetime(2026, 8, 10, 8)
    arr = dep + timedelta(hours=2)
    return TransportSegment(id=id, provider=provider, carrier=Carrier(carrier, "Carrier"), transport_type=TransportType.TRAIN, transport_class=TransportClass.SEATED, vehicle_number=number, origin_city=origin, origin_station=Station("msk", "Москва", origin), destination_city=destination, destination_station=Station("kaz", "Казань", destination), departure_datetime=dep, arrival_datetime=arr, duration_minutes=120, available_seats=seats)


class Provider:
    def __init__(self, segments=None, fail=False):
        self.segments = segments or []
        self.fail = fail
    def get_segments(self, *_args, **_kwargs):
        if self.fail:
            raise RuntimeError("down")
        return self.segments


def caps():
    return ProviderCapabilities(supported_transport=[TransportType.TRAIN], supports_availability=True, supports_realtime=False)


def test_registry_priority_enable_disable():
    registry = ProviderRegistry()
    registry.register(Provider(), id="low", name="Low", priority=ProviderPriority.LOW, capabilities=caps())
    registry.register(Provider(), id="high", name="High", priority=ProviderPriority.HIGH, capabilities=caps())
    assert [item.id for item in registry.list()] == ["high", "low"]
    assert registry.disable("high").enabled is False
    assert [item.id for item, _ in registry.enabled([TransportType.TRAIN])] == ["low"]
    assert registry.enable("high").enabled is True


def test_unified_merge_deduplicates_by_carrier_time_stations_and_number():
    registry = ProviderRegistry()
    registry.register(Provider([seg("a", "first", seats=3)]), id="first", name="First", priority=ProviderPriority.HIGH, capabilities=caps())
    registry.register(Provider([seg("b", "second", seats=9)]), id="second", name="Second", priority=ProviderPriority.LOW, capabilities=caps())
    segments = UnifiedTransportProvider(registry).get_segments(DAY, [TransportType.TRAIN])
    assert len(segments) == 1
    assert segments[0].provider == "first"
    assert segments[0].metadata["source_provider"] == "first"


def test_unified_health_marks_failed_provider_degraded_or_offline():
    registry = ProviderRegistry()
    registry.register(Provider(fail=True), id="broken", name="Broken", priority=ProviderPriority.HIGH, capabilities=caps())
    registry.register(Provider([seg("ok", "ok")]), id="ok", name="Ok", priority=ProviderPriority.LOW, capabilities=caps())
    segments = UnifiedTransportProvider(registry).get_segments(DAY, [TransportType.TRAIN])
    assert [s.id for s in segments] == ["ok"]
    assert registry.get("broken").health == ProviderHealth.OFFLINE
    assert registry.get("ok").health == ProviderHealth.HEALTHY


def test_registry_filters_unsupported_transport():
    registry = ProviderRegistry()
    registry.register(Provider([seg("train")]), id="train", name="Train", priority=ProviderPriority.NORMAL, capabilities=caps())
    assert registry.enabled([TransportType.BUS]) == []


def test_providers_api_enable_disable(monkeypatch):
    from app.api import providers as api_module

    registry = ProviderRegistry()
    registry.register(Provider(), id="api", name="API", priority=ProviderPriority.NORMAL, capabilities=caps())
    monkeypatch.setattr(api_module, "registry", registry)

    assert api_module.list_providers()[0].id == "api"
    assert api_module.providers_health()[0].health == ProviderHealth.HEALTHY
    assert api_module.disable_provider("api").enabled is False
    assert api_module.enable_provider("api").enabled is True
