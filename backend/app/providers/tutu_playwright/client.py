from __future__ import annotations
import os
import logging
import re
import time
from dataclasses import replace
from typing import Any

import httpx
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment, TransportType
from app.models.routes import RouteSearchRequest

logger = logging.getLogger(__name__)
MAX_DIAGNOSTIC_ITEMS = 50
MAX_DIAGNOSTIC_STRING = 500
SENSITIVE_KEYS = {"token", "service_api_token", "authorization", "x-service-token", "api_key", "password", "secret"}

def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else _safe_value(v)) for k, v in list(value.items())[:MAX_DIAGNOSTIC_ITEMS]}
    if isinstance(value, list | tuple):
        return [_safe_value(v) for v in list(value)[:MAX_DIAGNOSTIC_ITEMS]]
    if isinstance(value, str):
        scrubbed = re.sub(r"(?i)(token|authorization|api[_-]?key|secret|password)=([^&\s]+)", r"\1=[redacted]", value)
        return scrubbed[:MAX_DIAGNOSTIC_STRING]
    return value

def _safe_details(data: dict[str, Any], segment: TransportSegment, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
    details = {
        "segment_id": segment.id,
        "origin": segment.origin_city.name,
        "destination": segment.destination_city.name,
        "train_number": segment.vehicle_number,
        "status": status,
    }
    if diagnostics:
        details.update(diagnostics)
    for key in ("selected_inputs", "popup_candidates", "screenshots", "html_artifacts"):
        if key not in details and key in data:
            details[key] = data[key]
    if extra:
        details.update(extra)
    return _safe_value(details)

class TutuPlaywrightAvailabilityClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, enabled: bool | None = None, timeout: float | None = None):
        self.base_url=(base_url or os.getenv("TUTU_PLAYWRIGHT_SERVICE_URL", "")).rstrip("/")
        self.token=token if token is not None else os.getenv("TUTU_PLAYWRIGHT_SERVICE_TOKEN", "")
        self.enabled=(os.getenv("TUTU_PLAYWRIGHT_ENABLED", "false").lower()=="true") if enabled is None else enabled
        self.timeout=timeout if timeout is not None else float(os.getenv("TUTU_PLAYWRIGHT_REQUEST_TIMEOUT_SECONDS", "40"))
        self.connect_timeout=float(os.getenv("TUTU_PLAYWRIGHT_CONNECT_TIMEOUT_SECONDS", "5"))
        self.write_timeout=float(os.getenv("TUTU_PLAYWRIGHT_WRITE_TIMEOUT_SECONDS", "10"))
        self.pool_timeout=float(os.getenv("TUTU_PLAYWRIGHT_POOL_TIMEOUT_SECONDS", "5"))
    def available(self) -> bool:
        return bool(self.enabled and self.base_url)
    async def check_segment(self, segment: TransportSegment, request: RouteSearchRequest) -> SegmentAvailabilityResult | None:
        if not self.available() or segment.transport_type != TransportType.TRAIN:
            return None
        pref=request.seat_preferences
        payload={
            "origin": segment.origin_city.name,
            "destination": segment.destination_city.name,
            "departure_date": segment.departure_datetime.date().isoformat(),
            "train_number": segment.vehicle_number,
            "departure_time": segment.departure_datetime.isoformat(),
            "passengers": request.passengers,
            "preferred_classes": [str(c.value if hasattr(c,'value') else c) for c in (pref.preferred_classes if pref and pref.preferred_classes else request.preferred_classes)],
            "berth_preference": pref.berth_preference if pref else "any",
            "require_same_carriage": pref.require_same_carriage if pref else request.require_group_together,
            "require_same_compartment": pref.require_same_compartment if pref else False,
            "maximum_compartments": pref.maximum_compartments if pref else None,
        }
        headers={"X-Service-Token": self.token} if self.token else {}
        safe_payload = {k: v for k, v in payload.items() if k != "service_api_token"}
        timeout=httpx.Timeout(connect=self.connect_timeout, read=self.timeout, write=self.write_timeout, pool=self.pool_timeout)
        timeout_values={"connect": self.connect_timeout, "read": self.timeout, "write": self.write_timeout, "pool": self.pool_timeout}
        service_url=f"{self.base_url}/api/v1/availability/check"
        started_at=time.monotonic()
        logger.info("tutu_request_started", extra={"segment_id": segment.id, "payload": safe_payload, "service_url": service_url})
        logger.info("tutu_request_timeout_configuration", extra={"segment_id": segment.id, "timeouts": timeout_values, "service_url": service_url})
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp=await client.post(service_url, json=payload, headers=headers)
                elapsed=time.monotonic()-started_at
                logger.info("tutu_response_received", extra={"segment_id": segment.id, "status_code": resp.status_code, "elapsed_seconds": elapsed, "timeouts": timeout_values})
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=getattr(resp, "request", None), response=resp)
                data=resp.json()
                if data.get("status") == AvailabilityStatus.PROVIDER_ERROR.value or isinstance(data.get("diagnostics"), dict):
                    logger.info("tutu_diagnostic_response_received", extra={"segment_id": segment.id, "elapsed_seconds": elapsed, "diagnostic_response_received": True, "diagnostic_fields": sorted((data.get("diagnostics") or {}).keys()) if isinstance(data.get("diagnostics"), dict) else []})
        except httpx.ReadTimeout as exc:
            elapsed=time.monotonic()-started_at
            logger.warning("tutu_http_read_timeout", extra={"segment_id": segment.id, "elapsed_seconds": elapsed, "configured_read_timeout_seconds": self.timeout, "service_url": service_url, "timeouts": timeout_values})
            message = str(exc) or type(exc).__name__
            details = _safe_details({}, segment, "exception", {"diagnostic_response_received": False, "timeout_stage": "backend_http_read", "configured_read_timeout_seconds": self.timeout, "elapsed_seconds": elapsed, "service_url": service_url})
            return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, reasons=("Расписание найдено, проверка мест через Туту не выполнена",), warnings=("Расписание найдено, проверка мест через Туту не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": _safe_value(message), "error_type": type(exc).__name__, "details": details}})
        except Exception as exc:
            elapsed=time.monotonic()-started_at
            logger.warning("tutu_playwright.enrichment exception captured", extra={"segment_id": segment.id, "error_type": type(exc).__name__, "elapsed_seconds": elapsed, "timeouts": timeout_values})
            message = str(exc) or type(exc).__name__
            return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, reasons=("Расписание найдено, проверка мест через Туту не выполнена",), warnings=("Расписание найдено, проверка мест через Туту не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": _safe_value(message), "error_type": type(exc).__name__, "details": _safe_details({}, segment, "exception", {"elapsed_seconds": elapsed, "service_url": service_url})}})
        status=AvailabilityStatus(data.get("status", "unknown")) if data.get("status") in AvailabilityStatus._value2member_map_ else AvailabilityStatus.UNKNOWN
        if status == AvailabilityStatus.PROVIDER_ERROR:
            message = data.get("message") or data.get("error") or "Tutu Playwright provider_error"
            logger.warning("tutu_playwright.enrichment provider_error", extra={"segment_id": segment.id, "error_type": data.get("error_type")})
            return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, seats_confirmed=False, passengers_supported=False, available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN, reasons=("Расписание найдено, проверка мест через Туту не выполнена",), warnings=("Расписание найдено, проверка мест через Туту не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": _safe_value(message), "error_type": _safe_value(data.get("error_type") or "ProviderError"), "details": _safe_details(data, segment, "provider_error")}})
        if status == AvailabilityStatus.UNKNOWN and not data.get("matched_train"):
            reasons=("Tutu не нашёл поезд в публичном UI",)
        else:
            reasons=(data.get("message") or "",)
        return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=status, schedule_confirmed=True, seats_confirmed=status==AvailabilityStatus.CONFIRMED, passengers_supported=status==AvailabilityStatus.CONFIRMED, available_places_count=data.get("available_seats"), seat_preferences_status=status, selected_places=tuple(data.get("selected_places") or ()), selected_carriages=tuple(data.get("selected_carriages") or ()), selected_compartments=tuple(data.get("selected_compartments") or ()), reasons=tuple(r for r in reasons if r), warnings=tuple(data.get("warnings") or ()), metadata=data)
