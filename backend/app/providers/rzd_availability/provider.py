from __future__ import annotations

import asyncio

import logging
import time

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment, TransportType
from app.models.routes import RouteSearchRequest
from app.providers.rzd_availability.client import RZDClient
from app.providers.rzd_availability.config import RZDAvailabilityConfig
from app.providers.rzd_availability.exceptions import RZDTrainNotFound
from app.providers.rzd_availability.mapper import (
    normalize_train_number,
    to_segment_result,
)

logger = logging.getLogger(__name__)


class RZDAvailabilityProvider:
    """Availability enrichment interface used by the journey planner."""

    def __init__(
        self,
        client: RZDClient | None = None,
        config: RZDAvailabilityConfig | None = None,
    ):
        self.config = config or RZDAvailabilityConfig.from_env()
        self.client = client or RZDClient(self.config)

    def available(self) -> bool:
        return self.config.enabled

    async def check_segment(
        self, segment: TransportSegment, request: RouteSearchRequest
    ) -> SegmentAvailabilityResult | None:
        if not self.available() or segment.transport_type != TransportType.TRAIN:
            return None
        started = time.monotonic()
        status, error = "ok", None
        try:
            origin_code = self._endpoint_value(
                segment,
                request,
                "origin",
                "rzd_origin_code",
            )
            destination_code = self._endpoint_value(
                segment,
                request,
                "destination",
                "rzd_destination_code",
            )
            search = await asyncio.wait_for(
                self.client.search(
                    segment.origin_city.name,
                    segment.destination_city.name,
                    segment.departure_datetime.date(),
                    request.passengers,
                    origin_code=origin_code,
                    destination_code=destination_code,
                    origin_location_id=request.origin_location_id,
                    destination_location_id=request.destination_location_id,
                ),
                timeout=self.config.timeout_seconds,
            )
            expected = normalize_train_number(segment.vehicle_number)
            train = next(
                (
                    item
                    for item in search.trains
                    if normalize_train_number(item.train_number) == expected
                ),
                None,
            )
            if train is None:
                raise RZDTrainNotFound(segment.vehicle_number)
            return to_segment_result(segment, train, request.passengers)
        except Exception as exc:
            status, error = "unconfirmed", type(exc).__name__
            return SegmentAvailabilityResult(
                segment_id=segment.id,
                provider="rzd",
                status=AvailabilityStatus.UNCONFIRMED,
                schedule_confirmed=True,
                seats_confirmed=False,
                passengers_supported=False,
                available_places_count=None,
                seat_preferences_status=AvailabilityStatus.UNKNOWN,
                reasons=("Расписание найдено, наличие мест РЖД не подтверждено",),
                warnings=("Расписание найдено, наличие мест РЖД не подтверждено",),
                metadata={
                    "provider_error": {
                        "code": "availability_enrichment_failed",
                        "message": str(exc) or type(exc).__name__,
                        "error_type": type(exc).__name__,
                        "details": {
                            "segment_id": segment.id,
                            "origin": segment.origin_city.name,
                            "destination": segment.destination_city.name,
                            "train_number": segment.vehicle_number,
                        },
                    }
                },
            )
        finally:
            logger.info(
                "rzd_availability.segment",
                extra={
                    "origin": segment.origin_city.name,
                    "destination": segment.destination_city.name,
                    "train_number": segment.vehicle_number,
                    "provider_latency_ms": round(
                        (time.monotonic() - started) * 1000, 2
                    ),
                    "status": status,
                    "error": error,
                },
            )

    @staticmethod
    def _endpoint_value(
        segment: TransportSegment,
        request: RouteSearchRequest,
        endpoint: str,
        metadata_key: str,
    ) -> str | None:
        metadata_value = segment.metadata.get(metadata_key)
        if metadata_value:
            return str(metadata_value)
        station = getattr(segment, f"{endpoint}_station")
        if station.id and (
            station.id.isdigit()
            or (station.id.lower().startswith("s") and station.id[1:].isdigit())
        ):
            return station.id
        city = getattr(segment, f"{endpoint}_city").name.casefold()
        request_city = getattr(request, endpoint).casefold()
        return (
            getattr(request, f"{endpoint}_provider_code")
            if city == request_city
            else None
        )
