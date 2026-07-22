from __future__ import annotations

from datetime import date

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.exceptions import YandexRaspError, YandexRaspInvalidResponseError, YandexRaspUnknownCityError
from app.providers.yandex.mapper import YandexRaspMapper
from app.providers.yandex.resolver import YandexLocationMatch, YandexLocationResolver


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
            for origin_name, destination_name in pairs:
                origin_resolution = self.resolver.resolve(origin_name or "")
                destination_resolution = self.resolver.resolve(destination_name or "")
                diagnostics = self._diagnostics(origin_resolution, destination_resolution)
                seen_ids = {segment.id for segment in segments}
                for origin_code in self._codes_for_transport(origin_resolution, allowed_transport):
                    for destination_code in self._codes_for_transport(destination_resolution, allowed_transport):
                        payload = self.client.search(origin_code=origin_code, destination_code=destination_code, departure_date=departure_date, allowed_transport=allowed_transport, transfers=True)
                        if not isinstance(payload, dict) or "segments" not in payload:
                            raise YandexRaspInvalidResponseError("Некорректный ответ Яндекс Расписаний", diagnostics=diagnostics)
                        diagnostics["resolved_codes"].append({"from": origin_code, "to": destination_code})
                        for segment in self.mapper.to_segments(payload):
                            if segment.id in seen_ids:
                                continue
                            seen_ids.add(segment.id)
                            segments.append(segment)
                if not segments:
                    diagnostics["reason"] = "no_direct_segments"
                self.last_diagnostics = diagnostics
            self.last_error = None
            self.last_error_payload = None
            return segments
        except YandexRaspUnknownCityError as exc:
            exc.query = exc.query or origin or destination
            self._record_error(exc)
            raise
        except YandexRaspError as exc:
            self._record_error(exc)
            raise
        except Exception as exc:
            wrapped = YandexRaspError(str(exc) or exc.__class__.__name__, diagnostics=self.last_diagnostics)
            self._record_error(wrapped)
            raise

    def _diagnostics(self, origin: YandexLocationMatch, destination: YandexLocationMatch) -> dict:
        stations = list(origin.station_codes) + list(destination.station_codes)
        aliases = list(origin.aliases_used) + list(destination.aliases_used)
        return {
            "origin_resolution": origin.to_dict(),
            "destination_resolution": destination.to_dict(),
            "resolved_codes": [],
            "stations_considered": stations,
            "aliases_used": aliases,
            "cache_hit": origin.cache_hit or destination.cache_hit,
        }

    def _codes_for_transport(self, match: YandexLocationMatch, allowed_transport: list[TransportType]) -> tuple[str, ...]:
        allowed = {item.value for item in allowed_transport}
        if "train" in allowed:
            allowed.add("suburban")
        station_codes = tuple(station.code for station in match.stations if not station.transport_types or set(station.transport_types) & allowed)
        if match.type == "station":
            return (match.code,)
        return station_codes or match.station_codes

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
