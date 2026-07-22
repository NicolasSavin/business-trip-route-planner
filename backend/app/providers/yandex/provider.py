from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.exceptions import YandexRaspEmptyResponseError, YandexRaspError, YandexRaspInvalidResponseError, YandexRaspUnknownCityError
from app.providers.yandex.mapper import YandexRaspMapper
from app.providers.yandex.resolver import YandexLocationMatch, YandexLocationResolver

logger = logging.getLogger(__name__)


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

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None) -> list[TransportSegment]:
        if not self.config.enabled:
            return []
        try:
            pairs = [(origin, destination)] if origin and destination else [("Москва", "Санкт-Петербург")]
            segments: list[TransportSegment] = []
            pair_errors: list[dict[str, Any]] = []
            for origin_name, destination_name in pairs:
                origin_resolution = self.resolver.resolve(origin_name or "")
                destination_resolution = self.resolver.resolve(destination_name or "")
                diagnostics = self._diagnostics(origin_resolution, destination_resolution, departure_date)
                seen_ids = {segment.id for segment in segments}
                origin_codes = self._codes_for_transport(origin_resolution, allowed_transport)
                destination_codes = self._codes_for_transport(destination_resolution, allowed_transport)
                if not origin_codes or not destination_codes:
                    diagnostics["reason"] = "missing_station_code"
                    pair_errors.append(diagnostics)
                    continue
                for attempt, (origin_code, destination_code) in enumerate(((o, d) for o in origin_codes for d in destination_codes), start=1):
                    attempt_diag = self._attempt_diagnostics(origin_code, destination_code, attempt)
                    diagnostics["attempts"].append(attempt_diag)
                    try:
                        payload = self.client.search(origin_code=origin_code, destination_code=destination_code, departure_date=departure_date, allowed_transport=allowed_transport, transfers=True)
                        self._validate_payload(payload, diagnostics)
                        raw_segments = payload["segments"]
                        attempt_diag.update({
                            "http_status": getattr(self.client, "last_status_code", None),
                            "response_keys": sorted(payload.keys()),
                            "segment_count": len(raw_segments),
                            "pagination": {key: payload.get(key) for key in ("pagination", "page", "total", "limit", "offset") if key in payload},
                        })
                        for segment in self.mapper.to_segments(payload):
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
                self.last_diagnostics = diagnostics
                pair_errors.extend(item for item in diagnostics["attempts"] if item.get("error"))
            if segments:
                self.last_error = None
                self.last_error_payload = None
                return segments
            details = self._empty_details(origin, destination, departure_date, pair_errors)
            if pair_errors:
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

    def _validate_payload(self, payload: Any, diagnostics: dict) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            raise YandexRaspInvalidResponseError("Неожиданная структура ответа Яндекс Расписаний", diagnostics=diagnostics)

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
        return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "resolved_origin_codes": self.last_diagnostics.get("resolved_origin_codes", []), "resolved_destination_codes": self.last_diagnostics.get("resolved_destination_codes", []), "pair_errors": pair_errors}

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

    def healthcheck(self) -> bool:
        return self.config.enabled and bool(self.config.api_key)

    def ensure_can_enable(self) -> None:
        if not self.config.api_key:
            from app.providers.yandex.exceptions import YandexRaspAuthError
            raise YandexRaspAuthError("YANDEX_RASP_API_KEY is not configured")
