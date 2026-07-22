from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from app.providers.tutu.exceptions import TutuConfigurationError
from app.providers.unified import ProviderRegistration, registry

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


class TutuLiveTestRequest(BaseModel):
    origin: str
    destination: str
    date: date


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


@router.get("/tutu/test")
async def test_tutu_provider() -> dict:
    from app.providers.tutu.playwright import TutuPlaywrightClient, TutuPlaywrightMapper

    tomorrow = date.today() + timedelta(days=1)
    client = TutuPlaywrightClient()
    mapper = TutuPlaywrightMapper()
    try:
        await client.open_home()
        await client.search(origin="Москва", destination="Санкт-Петербург", date=tomorrow, passengers=1)
        results = await client.parse_results()
        routes = [mapper.to_route_option(result, "Москва", "Санкт-Петербург", rank=index + 1) for index, result in enumerate(results[:5])]
    finally:
        await client.close()
    return jsonable_encoder({"origin": "Москва", "destination": "Санкт-Петербург", "date": tomorrow, "routes": routes})


@router.post("/tutu/live-test")
async def live_test_tutu_provider(payload: TutuLiveTestRequest) -> dict:
    from app.providers.tutu.playwright import TutuPlaywrightClient

    client = TutuPlaywrightClient()
    return jsonable_encoder(await client.live_test(payload.origin, payload.destination, payload.date))
