from __future__ import annotations

import os
import time
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rzd_api.exceptions import RzdError
from starlette.responses import JSONResponse, Response

from app.providers.rzd_availability import RZDClient
from app.providers.rzd_availability.exceptions import RZDAvailabilityError

router = APIRouter(prefix="/api/v1/debug/rzd", tags=["development"])


class RZDDebugSearchRequest(BaseModel):
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    date: date
    passengers: int = Field(default=1, ge=1, le=9)
    origin_code: str | None = None
    destination_code: str | None = None
    skip_station_lookup: bool = False
    stop_after_stage: (
        Literal[
            "origin_station_lookup",
            "destination_station_lookup",
            "station_codes_resolved",
            "ticket_search",
        ]
        | None
    ) = None


class RZDStationCodeRequest(BaseModel):
    query: str = Field(min_length=1)
    provider_code: str | None = None


@router.post("/station-code", response_model=None)
async def resolve_rzd_station_code(payload: RZDStationCodeRequest) -> Response:
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        result = await RZDClient().resolve_station_code(
            payload.query, provider_code=payload.provider_code
        )
    except (RzdError, RZDAvailabilityError, ValueError) as exc:
        return JSONResponse(
            status_code=404,
            content={
                "resolved": False,
                "rzd_code": None,
                "source": None,
                "sdk_lookup_used": False,
                "message": str(exc),
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "resolved": True,
            "rzd_code": result.station.code,
            "source": result.source,
            "sdk_lookup_used": result.sdk_lookup_used,
        },
    )


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {
            key: _serialize(item)
            for key, item in value.__dict__.items()
            if key != "raw"
        }
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


@router.post("/search", response_model=None)
async def search_rzd(payload: RZDDebugSearchRequest) -> Response:
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.skip_station_lookup and (
        not payload.origin_code or not payload.destination_code
    ):
        raise HTTPException(
            status_code=422,
            detail="origin_code and destination_code are required when skip_station_lookup=true",
        )
    started = time.monotonic()
    try:
        args = (payload.origin, payload.destination, payload.date, payload.passengers)
        result = await RZDClient().search(
            *args,
            origin_code=payload.origin_code,
            destination_code=payload.destination_code,
            skip_station_lookup=payload.skip_station_lookup,
            stop_after_stage=payload.stop_after_stage,
        )
    except (RzdError, RZDAvailabilityError) as exc:
        details = {
            "origin": payload.origin,
            "destination": payload.destination,
            "date": payload.date.isoformat(),
        }
        if getattr(exc, "stage", None) is not None:
            details["stage"] = exc.stage
        if getattr(exc, "elapsed_ms", None) is not None:
            details["elapsed_ms"] = exc.elapsed_ms
        return JSONResponse(
            status_code=502,
            content={
                "code": "rzd_debug_failed",
                "error_type": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
                "details": details,
            },
        )
    if payload.stop_after_stage:
        return JSONResponse(status_code=200, content=_serialize(result))
    return JSONResponse(
        status_code=200,
        content={
            "raw": _serialize(result.raw),
            "normalized": _serialize(result),
            "timings": {"total_ms": round((time.monotonic() - started) * 1000, 2)},
        },
    )
