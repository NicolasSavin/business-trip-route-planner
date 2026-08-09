from __future__ import annotations

import logging
from datetime import date, datetime
from time import monotonic
from typing import Any

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.exceptions import YandexRaspAuthError, YandexRaspEmptyResponseError, YandexRaspError, YandexRaspInvalidResponseError, YandexRaspUnexpectedContentTypeError, YandexRaspUnknownCityError
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

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None, origin_provider_code: str | None = None, destination_provider_code: str | None = None, max_transfers: int = 1, **_kwargs) -> list[TransportSegment]:
        logger.info("route_search.yandex_provider_enter\norigin=%r\ndestination=%r\ndate=%s", origin, destination, departure_date)
        if not self.config.enabled:
            return []
        if not self.config.api_key:
            error = YandexRaspAuthError("YANDEX_RASP_API_KEY is not configured")
            self._record_error(error)
            raise error
        try:
            pairs = [(origin, destination)] if origin and destination else [("Москва", "Санкт-Петербург")]
            segments: list[TransportSegment] = []
            pair_errors: list[dict[str, Any]] = []
            yandex_segment_count = 0
            raw_direct_segment_count = 0
            direct_candidate_ids: set[str] = set()
            direct_candidate_count = 0
            started_at = monotonic()
            deadline = started_at + self.config.route_search_total_timeout_seconds
            requests_made = direct_requests = transfer_requests = 0
            fanout_limited = deadline_exceeded = False
            for origin_name, destination_name in pairs:
                origin_resolution = self._resolve_location(origin_name or "", origin_provider_code)
                destination_resolution = self._resolve_location(destination_name or "", destination_provider_code)
                diagnostics = self._diagnostics(origin_resolution, destination_resolution, departure_date)
                seen_ids = {segment.id for segment in segments}
                origin_codes = self._codes_for_transport(origin_resolution, allowed_transport)
                destination_codes = self._codes_for_transport(destination_resolution, allowed_transport)
                logger.info(
                    "route_search.yandex_station_candidates origin_station_search_count=%s destination_station_search_count=%s "
                    "origin_considered_count=%s destination_considered_count=%s origin_codes=%s destination_codes=%s",
                    len(origin_resolution.stations), len(destination_resolution.stations),
                    len(origin_codes), len(destination_codes), list(origin_codes), list(destination_codes),
                )
                for code in origin_codes:
                    logger.info("route_search.yandex_station_candidates role=origin code=%s", code)
                for code in destination_codes:
                    logger.info("route_search.yandex_station_candidates role=destination code=%s", code)
                diagnostics["raw_direct_candidates"] = []
                if not origin_codes or not destination_codes:
                    diagnostics["reason"] = "missing_station_code"
                    pair_errors.append(diagnostics)
                    continue
                primary_pair = (origin_codes[0], destination_codes[0])
                fallback_pairs = [
                    (o, d) for o in origin_codes for d in destination_codes
                    if (o, d) != primary_pair
                ]
                direct_pairs = [primary_pair, *fallback_pairs]
                if len(direct_pairs) > self.config.max_direct_requests_per_search:
                    fanout_limited = True
                    direct_pairs = direct_pairs[:self.config.max_direct_requests_per_search]
                request_pairs = [(o, d, False) for o, d in direct_pairs]
                # Transfer schedules are useful only when the caller permits them.
                # Keep their independent budget hard-bounded as well.
                if max_transfers > 0:
                    # A single destination city code with bounded origin-station
                    # fallbacks covers transfer discovery without a cartesian
                    # station explosion.
                    transfer_pairs = ([primary_pair, *((o, primary_pair[1]) for o in origin_codes[1:])]
                        if set(allowed_transport) == {TransportType.TRAIN} else [primary_pair, *fallback_pairs])
                    if len(transfer_pairs) > self.config.max_transfer_requests_per_search:
                        fanout_limited = True
                    request_pairs += [
                        (o, d, True)
                        for o, d in transfer_pairs[:self.config.max_transfer_requests_per_search]
                    ]
                city_direct_satisfied = False
                for origin_code, destination_code, transfers in request_pairs:
                    if city_direct_satisfied and not transfers and (origin_code, destination_code) != primary_pair:
                        continue
                    if monotonic() >= deadline:
                        deadline_exceeded = True
                        diagnostics.setdefault("warnings", []).append(
                            "Yandex schedule search deadline reached; returning schedules already collected."
                        )
                        break
                    if transfers:
                        if transfer_requests >= self.config.max_transfer_requests_per_search:
                            fanout_limited = True
                            continue
                        transfer_requests += 1
                    else:
                        if direct_requests >= self.config.max_direct_requests_per_search:
                            fanout_limited = True
                            continue
                        direct_requests += 1
                    requests_made += 1
                    attempt = requests_made
                    attempt_diag = self._attempt_diagnostics(origin_code, destination_code, attempt)
                    attempt_diag["candidate_kind"] = "transfer" if transfers else "direct"
                    diagnostics["attempts"].append(attempt_diag)
                    try:
                        logger.info(
                            "route_search.yandex_request origin_code=%s destination_code=%s date=%s transfers=%s allowed_transport=%s attempt=%s",
                            origin_code, destination_code, departure_date.isoformat(), transfers,
                            [item.value for item in allowed_transport], attempt,
                        )
                        payload = self.client.search(origin_code=origin_code, destination_code=destination_code, departure_date=departure_date, allowed_transport=allowed_transport, transfers=transfers)
                        if monotonic() >= deadline:
                            deadline_exceeded = True
                            diagnostics.setdefault("warnings", []).append(
                                "Yandex schedule search deadline reached; returning schedules already collected."
                            )
                        attempt_diag["request_params"] = getattr(self.client, "last_request_params", None)
                        self._validate_payload(payload, diagnostics)
                        raw_segments = payload["segments"]
                        yandex_segment_count += len(raw_segments)
                        if not transfers:
                            raw_direct_segment_count += len(raw_segments)
                            for candidate_index, raw_segment in enumerate(raw_segments):
                                candidate = self._describe_raw_direct(raw_segment, candidate_index)
                                logger.info(
                                    "route_search.yandex_direct_candidate origin_code=%s destination_code=%s candidate=%s",
                                    origin_code, destination_code, candidate,
                                )
                                rejection_reason = self._raw_direct_rejection_reason(raw_segment)
                                if rejection_reason:
                                    logger.info(
                                        "route_search.yandex_direct_rejected origin_code=%s destination_code=%s candidate_index=%s reason=%s candidate=%s",
                                        origin_code, destination_code, candidate_index, rejection_reason, candidate,
                                    )
                        attempt_diag.update({
                            "http_status": getattr(self.client, "last_status_code", None),
                            "response_keys": sorted(payload.keys()),
                            "segment_count": len(raw_segments),
                            "pagination": {key: payload.get(key) for key in ("pagination", "page", "total", "limit", "offset") if key in payload},
                            "response_diagnostics": getattr(self.client, "last_response_diagnostics", None),
                        })
                        logger.info(
                            "route_search.yandex_request origin_code=%s destination_code=%s transfers=%s attempt=%s segment_count=%s phase=response",
                            origin_code, destination_code, transfers, attempt, len(raw_segments),
                        )
                        mapped_segments = self.mapper.to_segments(payload)
                        attempt_diag["mapped_segment_count"] = len(mapped_segments)
                        if not transfers:
                            direct_candidate_count += len(mapped_segments)
                            direct_candidate_ids.update(segment.id for segment in mapped_segments)
                            diagnostics["raw_direct_candidates"].extend(self._describe_direct(segment) for segment in mapped_segments)
                            usable_direct = any(
                                segment.transport_type in allowed_transport
                                for segment in mapped_segments
                            ) and any(
                                isinstance(item, dict) and not item.get("has_transfers")
                                for item in raw_segments
                            )
                            if (origin_code, destination_code) == primary_pair and usable_direct:
                                city_direct_satisfied = True
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
                            "route_search.yandex_response origin_code=%s destination_code=%s transfers=%s request=%s yandex_segments=%s mapped_segments=%s",
                            origin_code,
                            destination_code,
                            transfers,
                            getattr(self.client, "last_request_params", None),
                            len(raw_segments),
                            len(mapped_segments),
                        )
                        for segment in mapped_segments:
                            if segment.id in seen_ids:
                                if not transfers:
                                    logger.info(
                                        "route_search.yandex_direct_rejected origin_code=%s destination_code=%s segment=%s reason=duplicate_segment_id",
                                        origin_code, destination_code, self._describe_direct(segment),
                                    )
                                continue
                            seen_ids.add(segment.id)
                            segments.append(segment)
                            if not transfers:
                                logger.info(
                                    "route_search.yandex_direct_accepted origin_code=%s destination_code=%s segment=%s",
                                    origin_code, destination_code, self._describe_direct(segment),
                                )
                        if deadline_exceeded:
                            break
                    except YandexRaspError as exc:
                        attempt_diag["error"] = exc.to_error()
                        logger.info(
                            "route_search.yandex_request origin_code=%s destination_code=%s transfers=%s attempt=%s segment_count=unknown phase=error error_code=%s",
                            origin_code, destination_code, transfers, attempt, exc.code,
                        )
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
                diagnostics["attempts"].sort(key=lambda item: 0 if item.get("error") else 1)
                pair_errors.extend(item for item in diagnostics["attempts"] if item.get("error"))
            self.last_diagnostics.update({
                "yandex_requests_made": requests_made,
                "yandex_direct_requests_made": direct_requests,
                "yandex_transfer_requests_made": transfer_requests,
                "yandex_candidate_origin_codes": list(origin_codes) if pairs else [],
                "yandex_candidate_destination_codes": list(destination_codes) if pairs else [],
                "yandex_fanout_limited": fanout_limited,
                "yandex_search_deadline_exceeded": deadline_exceeded,
            })
            logger.info(
                "route_search.yandex_budget requests_made=%s direct_requests=%s transfer_requests=%s fanout_limited=%s deadline_exceeded=%s",
                requests_made, direct_requests, transfer_requests, fanout_limited, deadline_exceeded,
            )
            direct_candidates_passed = sum(segment.id in direct_candidate_ids for segment in segments)
            logger.info("route_search.yandex_segments_total count=%s", yandex_segment_count)
            returned_direct = [self._describe_direct(segment) for segment in segments if segment.id in direct_candidate_ids]
            logger.info(
                "route_search.yandex_provider_output total_count=%s direct_count=%s direct_segments=%s",
                len(segments), direct_candidates_passed, returned_direct,
            )
            logger.info(
                "route_search.yandex_provider_return total_count=%s direct_count=%s direct_segments=%s",
                len(segments), direct_candidates_passed, returned_direct,
            )
            if direct_candidates_passed == 0:
                logger.info(
                    "route_search.yandex_provider_output_direct_zero reason=%s",
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
                self._compact_runtime_diagnostics(pair_errors)
                return segments
            details = self._empty_details(origin, destination, departure_date, pair_errors)
            self._compact_runtime_diagnostics(pair_errors)
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
        if pair_errors:
            # The client diagnostics are already redacted and size-capped. Keep
            # their public shape instead of wrapping all fan-out attempts (which
            # both hid expected fields and could exceed the API response limit).
            first_error = pair_errors[-1].get("error") or {}
            first_details = first_error.get("details")
            if isinstance(first_details, dict):
                return first_details
        return {
            **self.last_diagnostics,
            "origin": origin,
            "destination": destination,
            "date": departure_date.isoformat(),
            "pair_errors": pair_errors,
        }

    def _compact_runtime_diagnostics(self, pair_errors: list[dict[str, Any]]) -> None:
        """Keep API summary diagnostics bounded; detailed evidence lives in last_error_payload."""
        def compact(attempt: dict[str, Any]) -> dict[str, Any]:
            result = {key: value for key, value in attempt.items() if key not in {"response_diagnostics", "request_params"}}
            error = attempt.get("error")
            if isinstance(error, dict):
                result["error"] = {key: error[key] for key in ("code", "message") if key in error}
            return result
        attempts = self.last_diagnostics.get("attempts") or []
        self.last_diagnostics["attempts"] = [compact(item) for item in attempts]
        self.last_diagnostics["pair_errors"] = [compact(item) for item in pair_errors]

    def _codes_for_transport(self, match: YandexLocationMatch, allowed_transport: list[TransportType]) -> tuple[str, ...]:
        allowed = {item.value for item in allowed_transport}
        if "train" in allowed:
            allowed.add("suburban")
        if match.type == "station":
            return (match.code,) if match.code else ()
        train_only = allowed <= {"train", "suburban"}
        stations = [
            station for station in match.stations
            if station.code and (
                set(station.transport_types) & allowed
                or (not train_only and not station.transport_types)
            )
        ]
        if train_only:
            stations = [station for station in stations if set(station.transport_types) <= {"train", "suburban"}]
        stations.sort(key=self._station_rank)
        # For rail searches a city code is not an Express/station code. Prefer
        # concrete station codes and fall back to the city only when the
        # catalogue genuinely has no station mapping.
        station_codes = [station.code for station in stations[:self.config.max_stations_per_city]]
        # Mixed train+bus searches must retain the settlement code: it is valid
        # for Yandex's multimodal search and may cover bus endpoints not present
        # in the railway station subset. Explicit city codes are expanded to
        # station-only values only for a train-only request.
        codes = station_codes if match.source == "provider_code" and train_only and station_codes else [match.code, *station_codes]
        return tuple(dict.fromkeys(code for code in codes if code))

    @staticmethod
    def _station_rank(station) -> tuple[int, int, str]:
        station_type = (station.type or "").casefold()
        title = (station.title or "").casefold()
        exact_railway = station_type in {"railway_station", "train_station"}
        named_station = "вокзал" in title or "станция" in title
        return (0 if exact_railway else 1, 0 if named_station else 1, title)

    def _record_error(self, exc: YandexRaspError) -> None:
        self.last_error = exc.message
        self.last_error_payload = exc.to_error()
        if not self.last_diagnostics:
            self.last_diagnostics = exc.diagnostics or {}

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

    def _describe_raw_direct(self, item: Any, candidate_index: int) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {"candidate_index": candidate_index, "value_type": type(item).__name__}
        thread = item.get("thread") if isinstance(item.get("thread"), dict) else {}
        carrier = thread.get("carrier") if isinstance(thread.get("carrier"), dict) else {}
        origin = item.get("from") if isinstance(item.get("from"), dict) else {}
        destination = item.get("to") if isinstance(item.get("to"), dict) else {}
        return {
            "candidate_index": candidate_index,
            "has_transfers": item.get("has_transfers"),
            "train_number": thread.get("number") or item.get("number"),
            "train_title": thread.get("title") or thread.get("short_title"),
            "transport_type": thread.get("transport_type"),
            "transport_subtype": thread.get("transport_subtype"),
            "company": carrier.get("title") or carrier.get("name"),
            "express_type": thread.get("express_type"),
            "origin_code": origin.get("code"),
            "origin_title": origin.get("title"),
            "destination_code": destination.get("code"),
            "destination_title": destination.get("title"),
            "departure": item.get("departure"),
            "arrival": item.get("arrival"),
            "tickets_info": item.get("tickets_info"),
        }

    def _raw_direct_rejection_reason(self, item: Any) -> str | None:
        """Describe mapper exclusions without changing the mapper's decisions."""
        if not isinstance(item, dict):
            return "unsupported_segment_not_object"
        if item.get("has_transfers"):
            details = item.get("details") or []
            if not isinstance(details, list):
                return "unsupported_transfer_details_not_list"
            if not any(isinstance(detail, dict) for detail in details):
                return "unsupported_transfer_details_empty"
            return None
        origin = item.get("from") or {}
        destination = item.get("to") or {}
        if not isinstance(origin, dict):
            return "unsupported_origin_not_object"
        if not isinstance(destination, dict):
            return "unsupported_destination_not_object"
        if not origin:
            return "missing_origin_station"
        if not destination:
            return "missing_destination_station"
        if not item.get("departure"):
            return "invalid_schedule_missing_departure"
        if not item.get("arrival"):
            return "invalid_schedule_missing_arrival"
        try:
            datetime.fromisoformat(item["departure"])
            datetime.fromisoformat(item["arrival"])
        except (TypeError, ValueError):
            return "invalid_schedule_datetime"
        return None

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
