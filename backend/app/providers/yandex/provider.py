from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.exceptions import YandexRaspEmptyResponseError, YandexRaspError, YandexRaspInvalidResponseError, YandexRaspUnexpectedContentTypeError, YandexRaspUnknownCityError
from app.providers.yandex.mapper import YandexRaspMapper
from app.providers.yandex.resolver import YandexLocationMatch, YandexLocationResolver

logger = logging.getLogger("uvicorn.error")


class YandexRaspProvider(TransportProvider):
    provider_name = "yandex_rasp"

    def __init__(self, config: YandexRaspConfiguration | None = None, client: YandexRaspClient | None = None, resolver: YandexLocationResolver | None = None, mapper: YandexRaspMapper | None = None):
        self.config = config or YandexRaspConfiguration.from_env()
        self.client = client or YandexRaspClient(self.config)
        self.resolver = resolver or YandexLocationResolver(self.client.stations_list)
        self.mapper = mapper or YandexRaspMapper()
        self.last_error: str | None = None
        self.last_error_payload: dict | None = None
        self.last_diagnostics: dict = {}

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None, origin_provider_code: str | None = None, destination_provider_code: str | None = None, **_kwargs) -> list[TransportSegment]:
        logger.info("route_search.yandex_provider_enter\norigin=%r\ndestination=%r\ndate=%s", origin, destination, departure_date)
        if not self.config.enabled:
            return []
        try:
            pairs = [(origin, destination)] if origin and destination else [("Москва", "Санкт-Петербург")]
            segments: list[TransportSegment] = []
            pair_errors: list[dict[str, Any]] = []
            yandex_segment_count = 0
            raw_direct_segment_count = 0
            direct_candidate_ids: set[str] = set()
            direct_candidate_count = 0
            for origin_name, destination_name in pairs:
                origin_resolution = self._resolve_location(origin_name or "", origin_provider_code)
                destination_resolution = self._resolve_location(destination_name or "", destination_provider_code)
                diagnostics = self._diagnostics(origin_resolution, destination_resolution, departure_date)
                seen_ids = {segment.id for segment in segments}
                origin_codes = self._codes_for_transport(origin_resolution, allowed_transport)
                destination_codes = self._codes_for_transport(destination_resolution, allowed_transport)
                diagnostics["raw_direct_candidates"] = []
                if not origin_codes or not destination_codes:
                    diagnostics["reason"] = "missing_station_code"
                    pair_errors.append(diagnostics)
                    continue
                request_pairs = [(o, d, transfers) for o in origin_codes for d in destination_codes for transfers in (False, True)]
                for attempt, (origin_code, destination_code, transfers) in enumerate(request_pairs, start=1):
                    attempt_diag = self._attempt_diagnostics(origin_code, destination_code, attempt)
                    attempt_diag["candidate_kind"] = "transfer" if transfers else "direct"
                    diagnostics["attempts"].append(attempt_diag)
                    try:
                        payload = self.client.search(origin_code=origin_code, destination_code=destination_code, departure_date=departure_date, allowed_transport=allowed_transport, transfers=transfers)
                        attempt_diag["request_params"] = getattr(self.client, "last_request_params", None)
                        self._validate_payload(payload, diagnostics)
                        raw_segments = payload["segments"]
                        yandex_segment_count += len(raw_segments)
                        if not transfers:
                            raw_direct_segment_count += len(raw_segments)
                        attempt_diag.update({
                            "http_status": getattr(self.client, "last_status_code", None),
                            "response_keys": sorted(payload.keys()),
                            "segment_count": len(raw_segments),
                            "pagination": {key: payload.get(key) for key in ("pagination", "page", "total", "limit", "offset") if key in payload},
                            "response_diagnostics": getattr(self.client, "last_response_diagnostics", None),
                        })
                        mapped_segments = self.mapper.to_segments(payload)
                        attempt_diag["mapped_segment_count"] = len(mapped_segments)
                        if not transfers:
                            direct_candidate_count += len(mapped_segments)
                            direct_candidate_ids.update(segment.id for segment in mapped_segments)
                            diagnostics["raw_direct_candidates"].extend(self._describe_direct(segment) for segment in mapped_segments)
                            for segment in mapped_segments:
                                if self._is_moscow_to_saint_petersburg(segment):
                                    logger.info(
                                        "route_search.yandex_direct_segment number=%r title=%r origin=%r destination=%r "
                                        "origin_station=%r destination_station=%r departure_time=%s",
                                        segment.vehicle_number,
                                        segment.metadata.get("train_title"),
                                        segment.origin_city.name,
                                        segment.destination_city.name,
                                        segment.origin_station.name,
                                        segment.destination_station.name,
                                        segment.departure_datetime.isoformat(),
                                    )
                        logger.info(
                            "route_search.yandex_response origin_code=%s destination_code=%s request=%s yandex_segments=%s mapped_segments=%s",
                            origin_code,
                            destination_code,
                            getattr(self.client, "last_request_params", None),
                            len(raw_segments),
                            len(mapped_segments),
                        )
                        for segment in mapped_segments:
                            if segment.id in seen_ids:
                                continue
                            seen_ids.add(segment.id)
                            segments.append(segment)
                    except YandexRaspError as exc:
                        attempt_diag["error"] = exc.to_error()
                        logger.exception("Yandex Rasp pair failed: from=%s to=%s attempt=%s", origin_code, destination_code, attempt)
                        continue
                if not segments:
                    diagnostics["reason"] = "no_direct_segments"
                diagnostics["raw_direct_candidates"] = list({item["id"]: item for item in diagnostics["raw_direct_candidates"]}.values())
                diagnostics["raw_direct_schedule_count"] = len(diagnostics["raw_direct_candidates"])
                logger.info(
                    "route_search.yandex_direct_schedules count=%s trains=%s",
                    diagnostics["raw_direct_schedule_count"],
                    [item["train_number"] for item in diagnostics["raw_direct_candidates"]],
                )
                self.last_diagnostics = diagnostics
                pair_errors.extend(item for item in diagnostics["attempts"] if item.get("error"))
            direct_candidates_passed = sum(segment.id in direct_candidate_ids for segment in segments)
            logger.info("route_search.yandex_segments_total count=%s", yandex_segment_count)
            logger.info(
                "route_search.yandex_direct_candidates_to_route_engine count=%s",
                direct_candidates_passed,
            )
            if direct_candidates_passed == 0:
                logger.info(
                    "route_search.yandex_direct_candidates_to_route_engine_zero reason=%s",
                    self._zero_direct_candidates_reason(
                        yandex_segment_count=yandex_segment_count,
                        raw_direct_segment_count=raw_direct_segment_count,
                        direct_candidate_count=direct_candidate_count,
                        returned_segment_count=len(segments),
                    ),
                )
            if segments:
                self.last_error = None
                self.last_error_payload = None
                return segments
            details = self._empty_details(origin, destination, departure_date, pair_errors)
            if pair_errors:
                first_error = pair_errors[0].get("error") or {}
                if first_error.get("code") == "unexpected_content_type":
                    raise YandexRaspUnexpectedContentTypeError(
                        first_error.get("message", "Яндекс Расписания вернули ответ не в формате JSON"),
                        diagnostics=details,
                    )
                raise YandexRaspInvalidResponseError("Неожиданная структура ответа Яндекс Расписаний", diagnostics=details)
            raise YandexRaspEmptyResponseError("Яндекс Расписания не вернули сегменты", diagnostics=details)
        except YandexRaspUnknownCityError as exc:
            exc.query = exc.query or origin or destination
            self._record_error(exc)
            raise
        except YandexRaspError as exc:
            self._record_error(exc)
            raise
        except Exception:
            logger.exception("Unexpected Yandex Rasp provider failure")
            wrapped = YandexRaspInvalidResponseError("Неожиданная структура ответа Яндекс Расписаний", diagnostics=self.last_diagnostics)
            self._record_error(wrapped)
            raise wrapped

    def _resolve_location(self, title: str, provider_code: str | None) -> YandexLocationMatch:
        if provider_code:
            return self.resolver.resolve_code(provider_code, title)
        return self.resolver.resolve(title)

    def _validate_payload(self, payload: Any, diagnostics: dict) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            details = getattr(self.client, "last_response_diagnostics", None) or diagnostics
            raise YandexRaspInvalidResponseError("Неожиданная структура ответа Яндекс Расписаний", diagnostics=details)

    def _diagnostics(self, origin: YandexLocationMatch, destination: YandexLocationMatch, departure_date: date) -> dict:
        return {
            "endpoint": "/search/",
            "origin_resolution": origin.to_dict(),
            "destination_resolution": destination.to_dict(),
            "origin": origin.title,
            "destination": destination.title,
            "date": departure_date.isoformat(),
            "resolved_origin_codes": list(origin.station_codes),
            "resolved_destination_codes": list(destination.station_codes),
            "attempts": [],
            "stations_considered": list(origin.station_codes) + list(destination.station_codes),
            "aliases_used": list(origin.aliases_used) + list(destination.aliases_used),
            "cache_hit": origin.cache_hit or destination.cache_hit,
        }

    def _attempt_diagnostics(self, origin_code: str, destination_code: str, attempt: int) -> dict[str, Any]:
        return {"endpoint": "/search/", "origin_code": origin_code, "destination_code": destination_code, "request_attempt": attempt}

    def _empty_details(self, origin: str | None, destination: str | None, departure_date: date, pair_errors: list[dict[str, Any]]) -> dict[str, Any]:
        details = {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "resolved_origin_codes": self.last_diagnostics.get("resolved_origin_codes", []), "resolved_destination_codes": self.last_diagnostics.get("resolved_destination_codes", []), "pair_errors": pair_errors}
        for item in pair_errors:
            error_details = (item.get("error") or {}).get("details")
            if error_details:
                return error_details
        return details

    def _codes_for_transport(self, match: YandexLocationMatch, allowed_transport: list[TransportType]) -> tuple[str, ...]:
        allowed = {item.value for item in allowed_transport}
        if "train" in allowed:
            allowed.add("suburban")
        if match.type == "station":
            return (match.code,) if match.code else ()
        return tuple(station.code for station in match.stations if station.code and (not station.transport_types or set(station.transport_types) & allowed)) or tuple(code for code in match.station_codes if code)

    def _record_error(self, exc: YandexRaspError) -> None:
        self.last_error = exc.message
        self.last_error_payload = exc.to_error()
        self.last_diagnostics = exc.diagnostics or self.last_diagnostics

    def _describe_direct(self, segment: TransportSegment) -> dict[str, Any]:
        return {
            "id": segment.id,
            "train_number": segment.vehicle_number,
            "title": segment.metadata.get("train_title"),
            "departure": segment.departure_datetime.isoformat(),
            "arrival": segment.arrival_datetime.isoformat(),
            "duration_minutes": segment.duration_minutes,
            "provider": segment.provider,
            "transport_type": segment.transport_type.value,
            "transport_subtype": segment.metadata.get("transport_subtype") or segment.metadata.get("raw_transport_type"),
        }

    def _is_moscow_to_saint_petersburg(self, segment: TransportSegment) -> bool:
        def normalize(value: str) -> str:
            return " ".join(value.casefold().replace("ё", "е").replace("-", " ").split())

        return (
            normalize(segment.origin_city.name) == "москва"
            and normalize(segment.destination_city.name) == "санкт петербург"
        )

    def _zero_direct_candidates_reason(
        self,
        *,
        yandex_segment_count: int,
        raw_direct_segment_count: int,
        direct_candidate_count: int,
        returned_segment_count: int,
    ) -> str:
        if yandex_segment_count == 0:
            return "yandex_returned_no_segments"
        if raw_direct_segment_count == 0:
            return "yandex_returned_no_direct_segments"
        if direct_candidate_count == 0:
            return "yandex_direct_segments_could_not_be_mapped"
        if returned_segment_count == 0:
            return "direct_segments_were_not_added_to_provider_results"
        return "direct_segments_were_deduplicated_against_provider_results"

    def healthcheck(self) -> bool:
        return self.config.enabled and bool(self.config.api_key)

    def ensure_can_enable(self) -> None:
        if not self.config.api_key:
            from app.providers.yandex.exceptions import YandexRaspAuthError
            raise YandexRaspAuthError("YANDEX_RASP_API_KEY is not configured")
