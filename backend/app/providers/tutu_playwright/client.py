from __future__ import annotations
import os
from dataclasses import replace
import httpx
from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment, TransportType
from app.models.routes import RouteSearchRequest

class TutuPlaywrightAvailabilityClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, enabled: bool | None = None, timeout: float = 50.0):
        self.base_url=(base_url or os.getenv("TUTU_PLAYWRIGHT_SERVICE_URL", "")).rstrip("/")
        self.token=token if token is not None else os.getenv("TUTU_PLAYWRIGHT_SERVICE_TOKEN", "")
        self.enabled=(os.getenv("TUTU_PLAYWRIGHT_ENABLED", "false").lower()=="true") if enabled is None else enabled
        self.timeout=timeout
    def available(self) -> bool:
        return bool(self.enabled and self.base_url)
    def check_segment(self, segment: TransportSegment, request: RouteSearchRequest) -> SegmentAvailabilityResult | None:
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
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp=client.post(f"{self.base_url}/api/v1/availability/check", json=payload, headers=headers)
                resp.raise_for_status(); data=resp.json()
        except Exception as exc:
            return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=AvailabilityStatus.UNCONFIRMED, schedule_confirmed=True, reasons=("Tutu Playwright недоступен; маршрут не отклонён",), warnings=(str(exc),))
        status=AvailabilityStatus(data.get("status", "unknown")) if data.get("status") in AvailabilityStatus._value2member_map_ else AvailabilityStatus.UNKNOWN
        if status == AvailabilityStatus.UNKNOWN and not data.get("matched_train"):
            reasons=("Tutu не нашёл поезд в публичном UI",)
        else:
            reasons=(data.get("message") or "",)
        return SegmentAvailabilityResult(segment_id=segment.id, provider="tutu_playwright", status=status, schedule_confirmed=True, seats_confirmed=status==AvailabilityStatus.CONFIRMED, passengers_supported=status==AvailabilityStatus.CONFIRMED, available_places_count=data.get("available_seats"), seat_preferences_status=status, selected_places=tuple(data.get("selected_places") or ()), selected_carriages=tuple(data.get("selected_carriages") or ()), selected_compartments=tuple(data.get("selected_compartments") or ()), reasons=tuple(r for r in reasons if r), warnings=tuple(data.get("warnings") or ()), metadata=data)
