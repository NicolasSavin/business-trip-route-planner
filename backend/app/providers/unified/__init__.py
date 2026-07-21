from pathlib import Path

from app.domain import TransportType
from app.providers.gtfs import GTFSProvider
from app.providers.mock import MockTransportProvider
from app.providers.rzd import RzdCapabilities, RzdConfiguration, RzdProvider
from app.providers.tutu import TutuAvailabilityProvider, TutuConfiguration
from app.providers.yandex import YandexRaspConfiguration, YandexRaspProvider
from app.providers.unified.models import ProviderCapabilities, ProviderHealth, ProviderPriority, ProviderRegistration
from app.providers.unified.provider import UnifiedTransportProvider
from app.providers.unified.registry import ProviderRegistry


def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        MockTransportProvider(),
        id="mock",
        name="Mock Provider",
        priority=ProviderPriority.NORMAL,
        capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=True, supports_realtime=False),
    )
    yandex_config = YandexRaspConfiguration.from_env()
    registry.register(
        YandexRaspProvider(config=yandex_config),
        id="yandex_rasp",
        name="Яндекс Расписания",
        priority=ProviderPriority.HIGH,
        enabled=yandex_config.enabled,
        capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=False, supports_realtime=False),
        metadata={"base_url": yandex_config.base_url, "timeout_seconds": yandex_config.timeout_seconds, "uses_official_api": True},
    )
    if yandex_config.enabled:
        registry.disable("mock")

    rzd_config = RzdConfiguration.from_env()
    registry.register(
        RzdProvider(configuration=rzd_config),
        id="rzd",
        name="РЖД",
        priority=rzd_config.priority,
        enabled=rzd_config.enabled,
        capabilities=ProviderCapabilities(supported_transport=RzdCapabilities.supported_transport, supports_availability=RzdCapabilities.supports_availability, supports_realtime=RzdCapabilities.supports_realtime),
        metadata={"ready_to_connect": True, "status_label": "готов к подключению", "base_url": rzd_config.base_url, "timeout": rzd_config.timeout, "retry_count": rzd_config.retry_count},
    )
    tutu_config = TutuConfiguration.from_env()
    registry.register(
        TutuAvailabilityProvider(configuration=tutu_config),
        id="tutu",
        name="Туту",
        priority=ProviderPriority.LOW,
        enabled=False,
        capabilities=ProviderCapabilities(
            supported_transport=[TransportType.TRAIN],
            supports_availability=True,
            supports_realtime=False,
            supports_schedule=True,
            supports_carriages=True,
            supports_place_map=True,
            supports_compartment_rules=True,
            supports_gender_restrictions=True,
        ),
        metadata={
            "configured": tutu_config.configured,
            "status": "disabled",
            "message": "Требуется официальный партнёрский доступ Туту",
            "status_label": "Требуется партнёрский доступ",
            "real_requests_enabled": False,
            "adapter_prepared": True,
        },
    )

    gtfs_dir = Path("examples/gtfs")
    if gtfs_dir.exists():
        registry.register(
            GTFSProvider(gtfs_dir),
            id="gtfs",
            name="GTFS Provider",
            priority=ProviderPriority.HIGH,
            capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=False, supports_realtime=False),
        )
    return registry


registry = build_default_registry()
unified_provider = UnifiedTransportProvider(registry)

__all__ = ["UnifiedTransportProvider", "ProviderRegistry", "ProviderPriority", "ProviderHealth", "ProviderCapabilities", "ProviderRegistration", "build_default_registry", "registry", "unified_provider"]
