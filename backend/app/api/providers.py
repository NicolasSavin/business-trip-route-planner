from fastapi import APIRouter, HTTPException, status

from app.providers.tutu.exceptions import TutuConfigurationError
from app.providers.unified import ProviderRegistration, registry

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


@router.get("", response_model=list[ProviderRegistration])
def list_providers() -> list[ProviderRegistration]:
    return registry.list()


@router.get("/health", response_model=list[ProviderRegistration])
def providers_health() -> list[ProviderRegistration]:
    return registry.health()


@router.post("/{provider_id}/enable", response_model=ProviderRegistration)
def enable_provider(provider_id: str) -> ProviderRegistration:
    try:
        provider = registry.enable(provider_id)
    except TutuConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if provider is None:
        raise _not_found()
    return provider


@router.post("/{provider_id}/disable", response_model=ProviderRegistration)
def disable_provider(provider_id: str) -> ProviderRegistration:
    provider = registry.disable(provider_id)
    if provider is None:
        raise _not_found()
    return provider
