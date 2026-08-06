from __future__ import annotations

import logging
import os
import ssl
import time
import traceback
from datetime import date, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rzd_api.exceptions import RzdError
from starlette.responses import JSONResponse, Response

from app.providers.rzd_availability import RZDClient
from app.providers.rzd_availability.client import rzd_error_code
from app.providers.rzd_availability.exceptions import (
    RZDAvailabilityError,
    RZDNoSeatsError, RZDNoTrainError,
    SameStationCodeError,
)
from app.providers.rzd_availability.exceptions import RZDTrainNotFound
from app.providers.rzd_availability.mapper import train_number_match_type, to_segment_result
from app.domain import Carrier, City, Station, TransportSegment, TransportType

router = APIRouter(prefix="/api/v1/debug/rzd", tags=["development"])
logger = logging.getLogger(__name__)


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


class RZDSegmentDebugRequest(BaseModel):
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    departure_datetime: datetime
    train_number: str = Field(min_length=1)
    passengers: int = Field(default=1, ge=1, le=9)


class RZDHTTPProbeRequest(BaseModel):
    origin_code: str = Field(min_length=1)
    destination_code: str = Field(min_length=1)
    date: date
    passengers: int = Field(default=1, ge=1, le=9)


def _probe_verify_ssl() -> bool:
    return os.getenv("RZD_HTTP_PROBE_VERIFY_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_tls_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        message = str(current).lower()
        if isinstance(current, ssl.SSLError) or "ssl" in message or "tls" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


async def _request_probe(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
    except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        return {
            "status": "timeout",
            "status_code": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    except httpx.ConnectError as exc:
        return {
            "status": "tls_error" if _is_tls_error(exc) else "connect_error",
            "status_code": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    except httpx.HTTPStatusError as exc:
        response = exc.response
        return {
            "status": "http_error",
            "status_code": response.status_code,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "content_type": response.headers.get("content-type"),
            "body_sample": response.text[:500],
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    return {
        "status": "ok",
        "status_code": response.status_code,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "content_type": response.headers.get("content-type"),
        "body_sample": response.text[:500],
    }


async def run_http_probes(
    payload: RZDHTTPProbeRequest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ticket.rzd.ru/",
    }
    timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)
    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        verify=_probe_verify_ssl(),
        transport=transport,
    ) as client:
        base_probe = await _request_probe(client, "https://ticket.rzd.ru/")
        pricing_probe = await _request_probe(
            client,
            "https://ticket.rzd.ru/api/v1/railway-service/prices/train-pricing",
            params={
                "service_provider": "B2B_RZD",
                "getByLocalTime": "true",
                "carGrouping": "DontGroup",
                "origin": payload.origin_code,
                "destination": payload.destination_code,
                "departureDate": f"{payload.date.isoformat()}T00:00:00",
                "specialPlacesDemand": "StandardPlacesAndForDisabledPersons",
                "carIssuingType": "Passenger",
                "getTrainsFromSchedule": "true",
                "adultPassengersQuantity": payload.passengers,
                "childrenPassengersQuantity": 0,
                "hasPlacesForLargeFamily": "false",
            },
        )
    return {"base_probe": base_probe, "pricing_probe": pricing_probe}


@router.post("/http-probe", response_model=None)
async def http_probe_rzd(payload: RZDHTTPProbeRequest) -> Response:
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        raise HTTPException(status_code=404, detail="Not found")
    return JSONResponse(status_code=200, content=await run_http_probes(payload))


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


@router.post("/segment", response_model=None)
async def debug_rzd_segment(payload: RZDSegmentDebugRequest) -> Response:
    """Run the same code resolution, date and matching rules as route enrichment."""
    try:
        return await _debug_rzd_segment(payload)
    except HTTPException:
        raise
    except Exception as exc:
        formatted_traceback = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        logger.exception(
            "rzd_segment_debug.unexpected_exception",
            exc_info=True,
        )
        return JSONResponse(status_code=500, content={
            "status": "error",
            "provider": "rzd",
            "stage": "internal",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": formatted_traceback,
        })


async def _debug_rzd_segment(payload: RZDSegmentDebugRequest) -> Response:
    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        raise HTTPException(status_code=404, detail="Not found")
    client = RZDClient()
    try:
        origin_resolution = await client.resolve_station_code(payload.origin)
        destination_resolution = await client.resolve_station_code(payload.destination)
        if origin_resolution.station.code == destination_resolution.station.code:
            raise SameStationCodeError(
                origin=payload.origin, destination=payload.destination,
                origin_code=origin_resolution.station.code,
                destination_code=destination_resolution.station.code,
                origin_source=origin_resolution.source,
                destination_source=destination_resolution.source,
            )
        search = await client.search(
            payload.origin, payload.destination, payload.departure_datetime.date(),
            payload.passengers, origin_code=origin_resolution.station.code,
            destination_code=destination_resolution.station.code,
            skip_station_lookup=True,
        )
    except SameStationCodeError as exc:
        return JSONResponse(status_code=422, content=exc.diagnostic())
    except RZDNoSeatsError as exc:
        return JSONResponse(status_code=200, content={
            "status": "unavailable", "provider": "rzd", "stage": "ticket_search",
            "error_code": 311, "message": str(exc),
            "resolved_codes": {
                "origin": origin_resolution.station.code,
                "origin_source": origin_resolution.source,
                "destination": destination_resolution.station.code,
                "destination_source": destination_resolution.source,
            },
            "date": payload.departure_datetime.date().isoformat(),
            "train_number": payload.train_number,
            "final_availability_status": "unavailable",
        })
    except RZDNoTrainError as exc:
        return JSONResponse(status_code=200, content={
            "status": "not_found", "provider": "rzd", "stage": "ticket_search",
            "error_code": 310, "message": str(exc),
            "resolved_codes": {
                "origin": origin_resolution.station.code,
                "origin_source": origin_resolution.source,
                "destination": destination_resolution.station.code,
                "destination_source": destination_resolution.source,
            },
            "date": payload.departure_datetime.date().isoformat(),
            "train_number": payload.train_number,
            "final_availability_status": "unknown",
        })
    except (RzdError, RZDAvailabilityError) as exc:
        if rzd_error_code(exc) == 310:
            message = str(exc).split(":", 1)[-1].strip()
            return JSONResponse(status_code=200, content={
                "status": "not_found", "provider": "rzd", "stage": "ticket_search",
                "error_code": 310, "message": message,
                "resolved_codes": {
                    "origin": origin_resolution.station.code,
                    "origin_source": origin_resolution.source,
                    "destination": destination_resolution.station.code,
                    "destination_source": destination_resolution.source,
                },
                "date": payload.departure_datetime.date().isoformat(),
                "train_number": payload.train_number,
                "final_availability_status": "unknown",
            })
        return JSONResponse(status_code=502, content={
            "status": "error", "provider": "rzd",
            "stage": getattr(exc, "stage", None) or "ticket_search",
            "error_type": type(exc).__name__, "message": str(exc),
        })
    match = next(
        (
            (train, train_number_match_type(payload.train_number, train.train_number))
            for train in search.trains
            if train_number_match_type(payload.train_number, train.train_number) != "no_match"
        ),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=404,
            detail={
                "provider": "rzd",
                "stage": "train_match",
                "error_type": RZDTrainNotFound.__name__,
                "expected_train": payload.train_number,
                "returned_train_numbers": [train.train_number for train in search.trains[:10]],
            },
        )
    train, match_type = match
    origin = City(payload.origin)
    destination = City(payload.destination)
    segment = TransportSegment(
        "debug-rzd-segment", "rzd", Carrier("rzd", "РЖД"), TransportType.TRAIN,
        None, payload.train_number, origin, Station("debug-origin", payload.origin, origin),
        destination, Station("debug-destination", payload.destination, destination),
        payload.departure_datetime, payload.departure_datetime, 0, None,
    )
    availability = to_segment_result(segment, train, payload.passengers)
    return JSONResponse(
        status_code=200,
        content=_serialize(
            {
                "resolved_codes": {
                    "origin": origin_resolution.station.code,
                    "origin_source": origin_resolution.source,
                    "destination": destination_resolution.station.code,
                    "destination_source": destination_resolution.source,
                },
                "date": payload.departure_datetime.date(),
                "returned_train_numbers": [item.train_number for item in search.trains],
                "matched_train": train.train_number,
                "match_type": match_type,
                "carriages": train.carriages,
                "available_places_count": availability.available_places_count,
                "min_price": train.min_price,
                "final_availability_status": availability.status.value,
            }
        ),
    )
