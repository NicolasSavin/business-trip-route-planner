from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import logging
import time
from datetime import date
from typing import Any, Callable

from rzd_api import Config, RzdClient

from app.providers.rzd_availability.config import RZDAvailabilityConfig
from app.providers.rzd_availability.exceptions import (
    RZDAvailabilityError,
    RZDStationNotFound,
)
from app.providers.rzd_availability.mapper import map_train
from app.providers.rzd_availability.models import RZDSearchResult, RZDStation

logger = logging.getLogger(__name__)


class RZDClient:
    """Timeout/retry/cache boundary around the third-party ``rzd-api`` SDK."""

    def __init__(
        self,
        config: RZDAvailabilityConfig | None = None,
        sdk_factory: Callable[[Config], RzdClient] | None = None,
    ):
        self.config = config or RZDAvailabilityConfig.from_env()
        self._sdk_factory = sdk_factory or self._default_sdk_factory
        self._sdk: Any = None
        self._stations: dict[str, tuple[float, RZDStation]] = {}
        self._searches: dict[tuple[Any, ...], tuple[float, RZDSearchResult]] = {}

    @staticmethod
    def _default_sdk_factory(config: Config) -> RzdClient:
        return RzdClient(config)

    def _get_sdk(self) -> RzdClient:
        if self._sdk is None:
            sdk_config = Config(
                connect_timeout=self.config.timeout_seconds,
                read_timeout=self.config.timeout_seconds,
                retry_total=self.config.retries,
                retry_backoff=self.config.backoff_seconds,
                station_cache_ttl=self.config.station_cache_ttl_seconds,
            )
            self._sdk = self._sdk_factory(sdk_config)
        return self._sdk

    async def _call(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.wait_for(
            asyncio.to_thread(method, *args, **kwargs), self.config.timeout_seconds
        )

    async def _retry(
        self, method: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        last: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return await self._call(method, *args, **kwargs)
            except Exception as exc:
                last = exc
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.backoff_seconds * (2**attempt))
        raise RZDAvailabilityError(str(last) or type(last).__name__) from last

    async def lookup_station(self, query: str) -> RZDStation:
        key = query.strip().casefold()
        cached = self._stations.get(key)
        if (
            cached
            and time.monotonic() - cached[0] < self.config.station_cache_ttl_seconds
        ):
            return cached[1]
        candidates = await self._retry(self._get_sdk().find_stations, query)
        if not candidates:
            raise RZDStationNotFound(query)
        item = candidates[0]
        station = RZDStation(str(item.code), str(item.name))
        self._stations[key] = (time.monotonic(), station)
        return station

    async def search(
        self, origin: str, destination: str, departure_date: date, passengers: int = 1
    ) -> RZDSearchResult:
        key = (
            origin.casefold(),
            destination.casefold(),
            departure_date.isoformat(),
            passengers,
        )
        cached = self._searches.get(key)
        if (
            cached
            and time.monotonic() - cached[0]
            < self.config.availability_cache_ttl_seconds
        ):
            return cached[1]
        start = time.monotonic()
        status, error = "ok", None
        try:
            origin_station, destination_station = await asyncio.gather(
                self.lookup_station(origin), self.lookup_station(destination)
            )
            raw = await self._retry(
                self._get_sdk().search_tickets,
                origin,
                destination,
                departure_date,
                adults=passengers,
                children=0,
            )
            items = raw if isinstance(raw, list) else raw.outbound
            trains = []
            for item in items:
                # TrainRoute is a dataclass in 3.0.0. Keep its genuine fields and
                # let the normalization boundary consume a plain snapshot.
                snapshot = asdict(item) if is_dataclass(item) else dict(item.raw or {})
                snapshot.update(
                    number=item.number,
                    departure_time=item.departure_time,
                    arrival_time=item.arrival_time,
                    min_price=item.min_price,
                    carriages=[
                        asdict(group) if is_dataclass(group) else group
                        for group in item.car_groups
                    ],
                )
                trains.append(map_train(snapshot))
            result = RZDSearchResult(
                origin_station, destination_station, tuple(trains), raw
            )
            self._searches[key] = (time.monotonic(), result)
            return result
        except Exception as exc:
            status, error = "error", type(exc).__name__
            raise
        finally:
            logger.info(
                "rzd_availability.request",
                extra={
                    "origin": origin,
                    "destination": destination,
                    "train_number": None,
                    "provider_latency_ms": round((time.monotonic() - start) * 1000, 2),
                    "status": status,
                    "error": error,
                },
            )
