from __future__ import annotations

from datetime import date
from typing import Any

from app.domain import TransportSegment, TransportType
from app.providers.tutu.playwright.client import TutuPlaywrightClient
from app.providers.tutu.playwright.mapper import TutuPlaywrightMapper


class TutuPlaywrightProvider:
    provider_name = "tutu_playwright"

    def __init__(self, client: TutuPlaywrightClient | None = None, mapper: TutuPlaywrightMapper | None = None) -> None:
        self.client = client or TutuPlaywrightClient()
        self.mapper = mapper or TutuPlaywrightMapper()

    def healthcheck(self) -> bool:
        return True

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType] | None = None, origin: str | None = None, destination: str | None = None, passengers: int = 1, **_: Any) -> list[TransportSegment]:
        if allowed_transport and TransportType.TRAIN not in allowed_transport:
            return []
        if not origin or not destination:
            return []
        try:
            self.client.open_home()
            self.client.search(origin=origin, destination=destination, date=departure_date, passengers=passengers)
            results = self.client.parse_results()
            return self.mapper.to_segments(results, origin, destination)
        finally:
            self.client.close()
