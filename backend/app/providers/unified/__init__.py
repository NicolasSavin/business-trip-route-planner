from pathlib import Path

from app.domain import TransportType
from app.providers.gtfs import GTFSProvider
from app.providers.mock import MockTransportProvider
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
