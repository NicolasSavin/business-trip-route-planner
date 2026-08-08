import logging
import sqlite3

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.locations import LocationSuggestResponse, LocationSuggestion, location_repository
from app.providers.yandex.location_service import yandex_location_resolver

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])
logger = logging.getLogger(__name__)


def _to_suggestion(match) -> LocationSuggestion:
    location_type = "railway_station" if match.station_type == "railway_station" else "bus_station" if match.station_type == "bus_station" else match.type
    region_part = f", {match.region}" if match.region and match.region != match.settlement else ""
    station_part = f" — {match.title}" if match.type == "station" and match.settlement and match.title != match.settlement else ""
    transports = "/".join(match.transport_types)
    display_name = f"{match.settlement or match.title}{station_part}{region_part}" + (f" ({transports})" if transports else "")
    return LocationSuggestion(id=f"{location_type}:{match.code}", name=match.title, display_name=display_name, type=location_type, provider_code=match.code, region=match.region, country=match.country)


@router.get("/suggest", response_model=LocationSuggestResponse)
def suggest_locations(q: str = Query(default="", min_length=0), limit: int = Query(default=10, ge=1, le=20)) -> LocationSuggestResponse:
    matches = []
    if len(q.strip()) >= 2:
        try:
            matches = yandex_location_resolver.resolve_all(q)[:limit]
        except sqlite3.DatabaseError as exc:
            logger.warning("Yandex location suggestions database failed for %r: %s", q, exc)
            matches = []
        if matches:
            index_ready = yandex_location_resolver.stats().get("locations", 0) > 0
            yandex_match_count = sum(match.source == "sqlite" for match in matches)
            logger.info(
                "route_search.location_suggest",
                extra={
                    "query": q,
                    "yandex_index_ready": index_ready,
                    "yandex_match_count": yandex_match_count,
                    "fallback_used": yandex_match_count != len(matches),
                },
            )
            return LocationSuggestResponse(items=[_to_suggestion(item) for item in matches])
    fallback = location_repository.suggest(q, min(limit, 10))
    fallback_used = bool(fallback)
    logger.info(
        "route_search.location_suggest",
        extra={
            "query": q,
            "yandex_index_ready": yandex_location_resolver.stats().get("locations", 0) > 0,
            "yandex_match_count": len(matches),
            "fallback_used": fallback_used,
        },
    )
    return LocationSuggestResponse(items=fallback)


@router.get("/resolve")
def resolve_location(q: str = Query(..., min_length=1)) -> dict:
    return yandex_location_resolver.diagnostic(q)


@router.post("/sync-yandex")
def sync_yandex_locations(x_admin_token: str | None = Header(default=None)) -> dict:
    import os
    token = os.getenv("LOCATIONS_ADMIN_TOKEN")
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return yandex_location_resolver.refresh()
