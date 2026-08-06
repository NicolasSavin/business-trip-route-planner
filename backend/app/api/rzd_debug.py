from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

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
    started = time.monotonic()
    try:
        result = await RZDClient().search(
            payload.origin, payload.destination, payload.date, payload.passengers
        )
    except (RzdError, RZDAvailabilityError) as exc:
        return JSONResponse(
            status_code=502,
            content={
                "code": "rzd_debug_failed",
                "error_type": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
                "details": {
                    "origin": payload.origin,
                    "destination": payload.destination,
                    "date": payload.date.isoformat(),
                },
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "raw": _serialize(result.raw),
            "normalized": _serialize(result),
            "timings": {
                "total_ms": round((time.monotonic() - started) * 1000, 2)
            },
        },
    )
