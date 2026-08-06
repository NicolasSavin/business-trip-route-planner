from __future__ import annotations

import asyncio
import inspect
from importlib import import_module
import logging
import time
from datetime import date
from typing import Any, Callable

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
        sdk_factory: Callable[..., Any] | None = None,
    ):
        self.config = config or RZDAvailabilityConfig.from_env()
        self._sdk_factory = sdk_factory or self._default_sdk_factory
        self._sdk: Any = None
        self._stations: dict[str, tuple[float, RZDStation]] = {}
        self._searches: dict[tuple[Any, ...], tuple[float, RZDSearchResult]] = {}

    @staticmethod
    def _default_sdk_factory(**kwargs: Any) -> Any:
        module = import_module("rzd_api")
        sdk_class = next(
            (
                getattr(module, name, None)
                for name in ("RZD", "RzdApi", "RZDClient", "Client")
                if getattr(module, name, None)
            ),
            None,
        )
        if sdk_class is None:
            raise RZDAvailabilityError("Unsupported rzd-api package version")
        return sdk_class(**kwargs)

    def _get_sdk(self) -> Any:
        if self._sdk is None:
            kwargs = {
                "timeout": self.config.timeout_seconds,
                "verify_ssl": self.config.verify_ssl,
            }
            try:
                self._sdk = self._sdk_factory(**kwargs)
            except TypeError:
                self._sdk = self._sdk_factory()
        return self._sdk

    async def _invoke(self, names: tuple[str, ...], **kwargs: Any) -> Any:
        sdk = self._get_sdk()
        method = next(
            (
                getattr(sdk, name)
                for name in names
                if callable(getattr(sdk, name, None))
            ),
            None,
        )
        if method is None:
            raise RZDAvailabilityError(
                f"rzd-api does not expose any of: {', '.join(names)}"
            )
        if inspect.iscoroutinefunction(method):
            return await asyncio.wait_for(method(**kwargs), self.config.timeout_seconds)
        return await asyncio.wait_for(
            asyncio.to_thread(method, **kwargs), self.config.timeout_seconds
        )

    async def _retry(self, names: tuple[str, ...], **kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return await self._invoke(names, **kwargs)
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
        raw = await self._retry(
            ("suggest_stations", "search_stations", "stations"), query=query
        )
        candidates = (
            raw
            if isinstance(raw, list)
            else raw.get("stations", raw.get("items", []))
            if isinstance(raw, dict)
            else []
        )
        if not candidates:
            raise RZDStationNotFound(query)
        item = candidates[0]
        station = RZDStation(
            str(item.get("code") or item.get("expressCode") or item.get("id")),
            str(item.get("name") or item.get("station")),
        )
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
                ("search_trains", "trains", "search"),
                origin=origin_station.code,
                destination=destination_station.code,
                date=departure_date,
                passengers=passengers,
            )
            items = (
                raw
                if isinstance(raw, list)
                else raw.get("trains", raw.get("items", []))
                if isinstance(raw, dict)
                else []
            )
            trains = []
            for item in items:
                details = item
                reference = item.get("id") or item.get("trainId")
                if reference:
                    try:
                        details = await self._retry(
                            ("train_availability", "get_carriages", "carriages"),
                            train_id=reference,
                            origin=origin_station.code,
                            destination=destination_station.code,
                            date=departure_date,
                        )
                        if isinstance(details, list):
                            details = {**item, "carriages": details}
                        elif isinstance(details, dict):
                            details = {**item, **details}
                    except RZDAvailabilityError:
                        details = item
                trains.append(map_train(details))
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
