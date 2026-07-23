from __future__ import annotations
import os
import logging
import re
from dataclasses import replace
from typing import Any

import httpx
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment, TransportType
from app.models.routes import RouteSearchRequest

logger = logging.getLogger(__name__)
MAX_DIAGNOSTIC_ITEMS = 10
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

def _safe_details(data: dict[str, Any], segment: TransportSegment, status: str) -> dict[str, Any]:
    diagnostics = data.get("diagnostics") if isinstance(data.get("diagnostics"), dict) else {}
    details = {
        "segment_id": segment.id,
        "origin": segment.origin_city.name,
        "destination": segment.destination_city.name,
        "train_number": segment.vehicle_number,
        "status": status,
        "selected_inputs": diagnostics.get("selected_inputs", data.get("selected_inputs", [])),
        "popup_candidates": diagnostics.get("popup_candidates", data.get("popup_candidates", [])),
        "screenshots": diagnostics.get("screenshots", data.get("screenshots", [])),
        "html_artifacts": diagnostics.get("html_artifacts", data.get("html_artifacts", [])),
    }
    return _safe_value(details)

class TutuPlaywrightAvailabilityClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, enabled: bool | None = None, timeout: float | None = None):
        self.base_url=(base_url or os.getenv("TUTU_PLAYWRIGHT_SERVICE_URL", "")).rstrip("/")
        self.token=token if token is not None else os.getenv("TUTU_PLAYWRIGHT_SERVICE_TOKEN", "")
        self.enabled=(os.getenv("TUTU_PLAYWRIGHT_ENABLED", "false").lower()=="true") if enabled is None else enabled
        self.timeout=timeout if timeout is not None else float(os.getenv("TUTU_PLAYWRIGHT_REQUEST_TIMEOUT_SECONDS", "15"))
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
        logger.info("tutu_playwright.enrichment request started", extra={"segment_id": segment.id, "payload": safe_payload})
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp=await client.post(f"{self.base_url}/api/v1/availability/check", json=payload, headers=headers)
                logger.info("tutu_playwright.enrichment response received", extra={"segment_id": segment.id, "status_code": resp.status_code})
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=getattr(resp, "request", None), response=resp)
                data=resp.json()
        except Exception as exc:
            logger.warning("tutu_playwright.enrichment exception captured", extra={"segment_id": segment.id, "error_type": type(exc).__name__})
            message = str(exc) or type(exc).__name__
            return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, reasons=("Расписание найдено, проверка мест через Туту не выполнена",), warnings=("Расписание найдено, проверка мест через Туту не выполнена",), metadata={"provider_error": {"code": "availability_enrichment_failed", "message": _safe_value(message), "error_type": type(exc).__name__, "details": _safe_details({}, segment, "exception")}})
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
