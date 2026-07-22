import os
from pathlib import Path

from app.domain import TransportType
from app.providers.gtfs import GTFSProvider
from app.providers.mock import MockTransportProvider
from app.providers.rzd import RzdCapabilities, RzdConfiguration, RzdProvider
from app.providers.tutu import TutuAvailabilityProvider, TutuConfiguration
from app.providers.tutu.playwright import TutuPlaywrightProvider
from app.providers.yandex import YandexRaspConfiguration, YandexRaspProvider
from app.browser import BrowserAutomationProvider, BrowserConfiguration, BrowserManager, BrowserProviderCapability
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
        enabled=os.getenv("MOCK_PROVIDER_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=True, supports_realtime=False, supports_schedule=True),
        metadata={"provider_type": "mock", "configured": True, "ready": True},
    )
    yandex_config = YandexRaspConfiguration.from_env()
    registry.register(
        YandexRaspProvider(config=yandex_config),
        id="yandex_rasp",
        name="Яндекс Расписания",
        priority=ProviderPriority.HIGH,
        enabled=yandex_config.enabled,
        capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=False, supports_realtime=False, supports_schedule=True),
        metadata={"base_url": yandex_config.base_url, "timeout_seconds": yandex_config.timeout_seconds, "uses_official_api": True, "configured": bool(yandex_config.api_key), "provider_type": "production"},
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
        capabilities=ProviderCapabilities(supported_transport=RzdCapabilities.supported_transport, supports_availability=RzdCapabilities.supports_availability, supports_realtime=RzdCapabilities.supports_realtime, supports_schedule=True),
        metadata={"provider_type": "production", "configured": rzd_config.enabled, "ready_to_connect": True, "status_label": "готов к подключению", "base_url": rzd_config.base_url, "timeout": rzd_config.timeout, "retry_count": rzd_config.retry_count},
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
            supports_schedule=False,
            supports_carriages=True,
            supports_place_map=True,
            supports_compartment_rules=True,
            supports_gender_restrictions=True,
        ),
        metadata={
            "provider_type": "production",
            "configured": tutu_config.configured,
            "status": "disabled",
            "message": "Требуется официальный партнёрский доступ Туту",
            "status_label": "Требуется партнёрский доступ",
            "real_requests_enabled": False,
            "adapter_prepared": True,
        },
    )

    registry.register(
        TutuPlaywrightProvider(),
        id="tutu_playwright",
        name="Tutu Playwright",
        priority=ProviderPriority.LOW,
        enabled=False,
        capabilities=ProviderCapabilities(
            supported_transport=[TransportType.TRAIN],
            supports_availability=True,
            supports_realtime=False,
            supports_schedule=False,
            supports_carriages=True,
            supports_place_map=False,
        ),
        metadata={
            "provider_type": "production",
            "ready": True,
            "status_label": "Ready",
            "browser": "Playwright",
            "source": "tutu.ru browser UI only",
            "no_internal_api": True,
            "no_booking": True,
        },
    )

    browser_config = BrowserConfiguration.from_env()
    browser_manager = BrowserManager(config=browser_config)
    browser_status = BrowserAutomationProvider(manager=browser_manager).status()
    browser_capability = BrowserProviderCapability()
    registry.register(
        BrowserAutomationProvider(manager=browser_manager),
        id="browser_automation",
        name="Browser Automation",
        priority=ProviderPriority.LOW,
        enabled=False,
        capabilities=ProviderCapabilities(
            supported_transport=[],
            browser_automation=browser_capability.__dict__,
        ),
        metadata={
            "provider_type": "infrastructure",
            "configured": browser_status["configured"],
            **browser_status,
            "status_label": "Browser diagnostics",
            "infrastructure": "Инфраструктура готова",
            "playwright_installed": browser_status["configured"],
            "browser_running": browser_status["status"] == "running",
            "browser_version": browser_status["version"],
            "real_browser_requests_enabled": True,
        },
    )

    gtfs_dir = Path("examples/gtfs")
    if gtfs_dir.exists():
        registry.register(
            GTFSProvider(gtfs_dir),
            id="gtfs",
            name="GTFS Provider",
            priority=ProviderPriority.HIGH,
            capabilities=ProviderCapabilities(supported_transport=[TransportType.TRAIN, TransportType.BUS], supports_availability=False, supports_realtime=False, supports_schedule=True),
            metadata={"provider_type": "production", "configured": True, "ready": True},
        )
    return registry


registry = build_default_registry()
unified_provider = UnifiedTransportProvider(registry)

__all__ = ["UnifiedTransportProvider", "ProviderRegistry", "ProviderPriority", "ProviderHealth", "ProviderCapabilities", "ProviderRegistration", "build_default_registry", "registry", "unified_provider"]
