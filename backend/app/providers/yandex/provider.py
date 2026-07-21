from __future__ import annotations

from datetime import date

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.yandex.client import YandexRaspClient
from app.providers.yandex.config import YandexRaspConfiguration
from app.providers.yandex.mapper import YandexRaspMapper
from app.providers.yandex.resolver import YandexLocationResolver


class YandexRaspProvider(TransportProvider):
    provider_name = "yandex_rasp"

    def __init__(self, config: YandexRaspConfiguration | None = None, client: YandexRaspClient | None = None, resolver: YandexLocationResolver | None = None, mapper: YandexRaspMapper | None = None):
        self.config = config or YandexRaspConfiguration.from_env()
        self.client = client or YandexRaspClient(self.config)
        self.resolver = resolver or YandexLocationResolver(self.client.stations_list)
        self.mapper = mapper or YandexRaspMapper()
        self.last_error: str | None = None

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType], origin: str | None = None, destination: str | None = None) -> list[TransportSegment]:
        if not self.config.enabled:
            return []
        try:
            if origin and destination:
                pairs = [(origin, destination)]
            else:
                pairs = [("Москва", "Санкт-Петербург")]
            segments: list[TransportSegment] = []
            for origin_name, destination_name in pairs:
                from_settlement = self.resolver.resolve(origin_name)
                to_settlement = self.resolver.resolve(destination_name)
                payload = self.client.search(origin_code=from_settlement.code, destination_code=to_settlement.code, departure_date=departure_date, allowed_transport=allowed_transport, transfers=True)
                segments.extend(self.mapper.to_segments(payload))
            self.last_error = None
            return segments
        except Exception as exc:
            self.last_error = str(exc)
            return []
