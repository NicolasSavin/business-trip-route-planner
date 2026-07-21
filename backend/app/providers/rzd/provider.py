from __future__ import annotations

from datetime import date

from app.domain import TransportSegment, TransportType
from app.providers.base import TransportProvider
from app.providers.rzd.client import MockRzdClient, RzdClient
from app.providers.rzd.config import RzdConfiguration
from app.providers.rzd.mapper import RzdMapper


class RzdProvider(TransportProvider):
    provider_name = "rzd"

    def __init__(self, client: RzdClient | None = None, mapper: RzdMapper | None = None, configuration: RzdConfiguration | None = None) -> None:
        self.client = client or MockRzdClient()
        self.mapper = mapper or RzdMapper()
        self.configuration = configuration or RzdConfiguration()

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType]) -> list[TransportSegment]:
        if TransportType.TRAIN not in set(allowed_transport):
            return []
        return self.mapper.to_segments(self.client.search_trains(departure_date))

    def healthcheck(self) -> bool:
        return self.client.healthcheck()
