from fastapi import APIRouter, Query

from app.locations import LocationSuggestResponse, location_repository
from app.providers.yandex.resolver import YandexLocationResolver

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get("/suggest", response_model=LocationSuggestResponse)
def suggest_locations(q: str = Query(default="", min_length=0), limit: int = Query(default=10, ge=1, le=10)) -> LocationSuggestResponse:
    return LocationSuggestResponse(items=location_repository.suggest(q, limit))


@router.get("/resolve")
def resolve_location(q: str = Query(..., min_length=1)) -> dict:
    return YandexLocationResolver(repository=location_repository).diagnostic(q)
