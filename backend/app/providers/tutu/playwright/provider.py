from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from app.domain import TransportSegment, TransportType
from app.providers.tutu.playwright.client import TutuPlaywrightClient
from app.providers.tutu.playwright.mapper import TutuPlaywrightMapper


class TutuPlaywrightProvider:
    provider_name = "tutu_playwright"

    def __init__(self, client: TutuPlaywrightClient | None = None, mapper: TutuPlaywrightMapper | None = None) -> None:
        self._client = client
        self.mapper = mapper or TutuPlaywrightMapper()

    @property
    def client(self) -> TutuPlaywrightClient:
        if self._client is None:
            self._client = TutuPlaywrightClient()
        return self._client

    def healthcheck(self) -> bool:
        return True

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType] | None = None, origin: str | None = None, destination: str | None = None, passengers: int = 1, **kwargs: Any) -> list[TransportSegment]:
        return asyncio.run(self.get_segments_async(departure_date, allowed_transport, origin, destination, passengers, **kwargs))

    async def get_segments_async(self, departure_date: date, allowed_transport: list[TransportType] | None = None, origin: str | None = None, destination: str | None = None, passengers: int = 1, **_: Any) -> list[TransportSegment]:
        if allowed_transport and TransportType.TRAIN not in allowed_transport:
            return []
        if not origin or not destination:
            return []
        try:
            await self.client.open_home()
            await self.client.search(origin=origin, destination=destination, date=departure_date, passengers=passengers)
            results = await self.client.parse_results()
            return self.mapper.to_segments(results, origin, destination)
        finally:
            await self.client.close()
