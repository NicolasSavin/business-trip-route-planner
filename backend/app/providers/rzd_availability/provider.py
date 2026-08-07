from __future__ import annotations

import asyncio

import logging
import time

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment, TransportType
from app.models.routes import RouteSearchRequest
from app.providers.rzd_availability.client import RZDClient, rzd_error_code
from app.providers.rzd_availability.config import RZDAvailabilityConfig
from app.providers.rzd_availability.exceptions import RZDNoSeatsError, RZDNoTrainError, RZDTrainNotFound
from app.providers.rzd_availability.mapper import (
    normalize_train_number,
    train_number_match_type,
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
        stage = "started"
        context = self._diagnostic_context(segment)
        logger.info("rzd_segment_enrichment.started", extra=context)
        try:
            origin_hint = self._endpoint_value(segment, request, "origin", "rzd_origin_code")
            destination_hint = self._endpoint_value(segment, request, "destination", "rzd_destination_code")
            if not hasattr(self.client, "resolve_station_code"):
                # Small test/custom clients may intentionally expose only search.
                origin_resolution = destination_resolution = None
            else:
                origin_resolution = await self.client.resolve_station_code(
                    segment.origin_city.name, provider_code=origin_hint
                )
                destination_resolution = await self.client.resolve_station_code(
                    segment.destination_city.name, provider_code=destination_hint
                )
            stage = "codes_resolved"
            context.update(
                origin_code=origin_resolution.station.code if origin_resolution else origin_hint,
                destination_code=destination_resolution.station.code if destination_resolution else destination_hint,
                origin_code_source=origin_resolution.source if origin_resolution else None,
                destination_code_source=destination_resolution.source if destination_resolution else None,
            )
            logger.info("rzd_segment_enrichment.codes_resolved", extra=context)
            search = await asyncio.wait_for(
                self.client.search(
                    segment.origin_city.name,
                    segment.destination_city.name,
                    segment.departure_datetime.date(),
                    request.passengers,
                    origin_code=origin_resolution.station.code if origin_resolution else origin_hint,
                    destination_code=destination_resolution.station.code if destination_resolution else destination_hint,
                    # Request location ids are Yandex identifiers and describe the
                    # whole journey, not this particular intermediate segment.
                    origin_location_id=None,
                    destination_location_id=None,
                    skip_station_lookup=True,
                ),
                timeout=self.config.timeout_seconds,
            )
            stage = "search_completed"
            returned = [item.train_number for item in search.trains]
            normalized_returned = [normalize_train_number(number) for number in returned]
            context.update(
                returned_trains_count=len(returned),
                returned_train_numbers_sample=normalized_returned[:10],
            )
            logger.info("rzd_segment_enrichment.search_completed", extra=context)
            train = None
            match_type = "no_match"
            for item in search.trains:
                candidate_type = train_number_match_type(segment.vehicle_number, item.train_number)
                if candidate_type != "no_match":
                    train, match_type = item, candidate_type
                    break
            if train is None:
                raise RZDTrainNotFound(segment.vehicle_number)
            stage = "train_matched"
            context.update(matched_train_number=train.train_number, match_type=match_type)
            logger.info("rzd_segment_enrichment.train_matched", extra=context)
            return to_segment_result(
                segment, train, request.passengers, preferences_requested=request.seat_preferences is not None
            )
        except RZDNoSeatsError as exc:
            # Error 311 is raised by the direction-level ticket search, before a
            # train can be matched.  It therefore cannot disprove the Yandex
            # timetable for this exact train.  A returned, matched train with
            # insufficient inventory is still mapped to UNAVAILABLE above.
            return self._unknown_result(segment, exc, "ticket_search", 311)
        except RZDNoTrainError as exc:
            return self._unknown_result(segment, exc, "ticket_search", 310)
        except Exception as exc:
            if rzd_error_code(exc) == 311:
                return self._unknown_result(segment, exc, "ticket_search", 311)
            if rzd_error_code(exc) == 310:
                return self._unknown_result(segment, exc, "ticket_search", 310)
            failure_stage = "train_match" if isinstance(exc, RZDTrainNotFound) else stage
            details = {
                "segment_id": segment.id,
                "origin_code": context.get("origin_code"),
                "destination_code": context.get("destination_code"),
                "expected_train": segment.vehicle_number,
                "returned_trains_sample": context.get("returned_train_numbers_sample", []),
            }
            logger.info(
                "rzd_segment_enrichment.failed",
                extra={**context, "failure_stage": failure_stage, "error_type": type(exc).__name__, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)},
            )
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
                        "provider": "rzd",
                        "stage": failure_stage,
                        "message": str(exc) or type(exc).__name__,
                        "error_type": type(exc).__name__,
                        "details": details,
                    }
                },
            )
        finally:
            logger.info("rzd_segment_enrichment.finished", extra={**context, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)})

    @staticmethod
    def _diagnostic_context(segment: TransportSegment) -> dict[str, object]:
        departure = segment.departure_datetime
        return {
            "segment_id": segment.id,
            "origin_city": segment.origin_city.name,
            "destination_city": segment.destination_city.name,
            "origin_station_id": segment.origin_station.id,
            "origin_station_name": segment.origin_station.name,
            "destination_station_id": segment.destination_station.id,
            "destination_station_name": segment.destination_station.name,
            "departure_datetime": segment.departure_datetime.isoformat(),
            "departure_date": segment.departure_datetime.date().isoformat(),
            "local_departure_datetime": departure.isoformat(),
            "timezone": departure.tzname() if departure.tzinfo else "naive/local schedule time",
            "date_sent_to_rzd": departure.date().isoformat(),
            "arrival_date": segment.arrival_datetime.date().isoformat(),
            "raw_train_number": segment.vehicle_number,
            "normalized_train_number": normalize_train_number(segment.vehicle_number),
        }

    @staticmethod
    def _unknown_result(segment: TransportSegment, exc: Exception, stage: str, code: int) -> SegmentAvailabilityResult:
        reason = (
            "РЖД вернул ошибку направления; наличие мест в конкретном поезде не подтверждено"
            if code == 311 else "РЖД не вернул поезд для данного участка и даты"
        )
        return SegmentAvailabilityResult(
            segment_id=segment.id, provider="rzd", status=AvailabilityStatus.UNKNOWN,
            schedule_confirmed=True, seats_confirmed=False, passengers_supported=False,
            available_places_count=None, seat_preferences_status=AvailabilityStatus.UNKNOWN,
            reasons=(reason,), warnings=(reason,), metadata={
                "rzd_error_code": code, "stage": stage,
                "provider_error": {"code": code, "provider": "rzd", "stage": stage,
                    "message": str(exc), "error_type": type(exc).__name__,
                    "details": {"segment_id": segment.id, "train_number": segment.vehicle_number}},
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
        city = getattr(segment, f"{endpoint}_city").name.casefold()
        request_city = getattr(request, endpoint).casefold()
        return (
            getattr(request, f"{endpoint}_provider_code")
            if city == request_city
            else None
        )
