from __future__ import annotations

import asyncio
import importlib
import importlib.util
from dataclasses import asdict, is_dataclass
import logging
import time
from datetime import date
from types import SimpleNamespace
from typing import Any, Callable, Literal

_rzd_api = importlib.import_module("rzd_api") if importlib.util.find_spec("rzd_api") else None
Config = getattr(_rzd_api, "Config", None)
if Config is None:
    class Config(SimpleNamespace):
        def __init__(self, **kwargs: Any):
            super().__init__(**kwargs)
RzdClient = getattr(_rzd_api, "RzdClient", Any)

from app.providers.rzd_availability.config import RZDAvailabilityConfig
from app.providers.rzd_availability.exceptions import (
    RZDAvailabilityError,
    RZDNoSeatsError,
    RZDNoTrainError,
    RZDStationNotFound,
    SameStationCodeError,
)
from app.providers.rzd_availability.mapper import map_train
from app.providers.rzd_availability.models import RZDSearchResult, RZDStation
from app.providers.rzd_availability.station_resolver import (
    StationCodeResolution,
    StationCodeResolver,
)

logger = logging.getLogger(__name__)


def rzd_error_code(exc: BaseException) -> int | None:
    """Read an SDK error code without depending on a particular SDK release."""
    current: BaseException | None = exc
    while current is not None:
        for attribute in ("code", "error_code"):
            value = getattr(current, attribute, None)
            try:
                if value is not None and int(value) in (310, 311):
                    return int(value)
            except (TypeError, ValueError):
                pass
        message = str(current).casefold()
        for code in (310, 311):
            if f"error {code}" in message:
                return code
        current = current.__cause__ or current.__context__
    return None


class RZDClient:
    """Timeout/retry/cache boundary around the third-party ``rzd-api`` SDK."""

    def __init__(
        self,
        config: RZDAvailabilityConfig | None = None,
        sdk_factory: Callable[[Config], RzdClient] | None = None,
        station_resolver: StationCodeResolver | None = None,
    ):
        self.config = config or RZDAvailabilityConfig.from_env()
        self._uses_default_sdk = sdk_factory is None
        self._sdk_factory = sdk_factory or self._default_sdk_factory
        self._sdk: Any = None
        self.station_resolver = station_resolver or StationCodeResolver()
        self._stations: dict[str, tuple[float, RZDStation]] = {}
        self._searches: dict[tuple[Any, ...], tuple[float, RZDSearchResult]] = {}

    @staticmethod
    def _default_sdk_factory(config: Config) -> RzdClient:
        return RzdClient(config)

    def _get_sdk(self) -> RzdClient:
        if _rzd_api is None and self._uses_default_sdk:
            raise RZDAvailabilityError("rzd-api SDK is not installed")
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

    async def _call(
        self, method: Callable[..., Any], timeout: float, *args: Any, **kwargs: Any
    ) -> Any:
        return await asyncio.wait_for(
            asyncio.to_thread(method, *args, **kwargs), timeout
        )

    async def _retry(
        self, method: Callable[..., Any], timeout: float, *args: Any, **kwargs: Any
    ) -> Any:
        last: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return await self._call(method, timeout, *args, **kwargs)
            except asyncio.TimeoutError:
                # A stage timeout is diagnostic evidence, not a transient error:
                # preserve it for the stage boundary instead of retrying it.
                raise
            except Exception as exc:
                if rzd_error_code(exc) == 311:
                    raise RZDNoSeatsError(str(exc)) from exc
                if rzd_error_code(exc) == 310:
                    raise RZDNoTrainError(str(exc)) from exc
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
        candidates = await self._retry(
            self._get_sdk().find_stations,
            self.config.station_lookup_timeout_seconds,
            query,
        )
        if not candidates:
            raise RZDStationNotFound(query)
        item = candidates[0]
        station = RZDStation(str(item.code), str(item.name))
        self._stations[key] = (time.monotonic(), station)
        return station

    async def resolve_station_code(
        self,
        query: str,
        provider_code: str | None = None,
        location_id: str | None = None,
        allow_sdk_lookup: bool = True,
    ) -> StationCodeResolution:
        return await self.station_resolver.resolve(
            query,
            provider_code=provider_code,
            location_id=location_id,
            sdk_lookup=self.lookup_station,
            allow_sdk_lookup=allow_sdk_lookup,
        )

    @staticmethod
    def _stage_log(
        event: str,
        stage: str,
        origin: str,
        destination: str,
        started: float,
        error: Exception | None = None,
    ) -> None:
        logger.info(
            f"rzd_availability.{event}",
            extra={
                "stage": stage,
                "origin": origin,
                "destination": destination,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "error_type": type(error).__name__ if error else None,
                "error_message": str(error) if error else None,
            },
        )

    async def _stage(
        self, stage: str, origin: str, destination: str, operation: Callable[[], Any]
    ) -> tuple[Any, float]:
        started = time.monotonic()
        self._stage_log("stage_started", stage, origin, destination, started)
        try:
            value = await operation()
        except asyncio.TimeoutError as exc:
            elapsed = round((time.monotonic() - started) * 1000, 2)
            error = RZDAvailabilityError(
                f"rzd_stage_timeout:{stage}", stage=stage, elapsed_ms=elapsed
            )
            self._stage_log("stage_failed", stage, origin, destination, started, error)
            raise error from exc
        except Exception as exc:
            self._stage_log("stage_failed", stage, origin, destination, started, exc)
            raise
        elapsed = round((time.monotonic() - started) * 1000, 2)
        self._stage_log("stage_completed", stage, origin, destination, started)
        return value, elapsed

    async def search(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        passengers: int = 1,
        origin_code: str | None = None,
        destination_code: str | None = None,
        origin_location_id: str | None = None,
        destination_location_id: str | None = None,
        skip_station_lookup: bool = False,
        stop_after_stage: (
            Literal[
                "origin_station_lookup",
                "destination_station_lookup",
                "ticket_search",
                "station_codes_resolved",
            ]
            | None
        ) = None,
    ) -> RZDSearchResult | dict[str, Any]:
        key = (
            origin.casefold(),
            destination.casefold(),
            departure_date.isoformat(),
            passengers,
            origin_code,
            destination_code,
            origin_location_id,
            destination_location_id,
        )
        cached = self._searches.get(key) if stop_after_stage is None else None
        if (
            cached
            and time.monotonic() - cached[0]
            < self.config.availability_cache_ttl_seconds
        ):
            return cached[1]
        start = time.monotonic()
        status, error = "ok", None
        try:
            timings: dict[str, float] = {}

            async def find_origin() -> StationCodeResolution:
                return await self.resolve_station_code(
                    origin, origin_code, origin_location_id, not skip_station_lookup
                )

            origin_resolution, timings["origin_station_lookup"] = await self._stage(
                "origin_station_lookup", origin, destination, find_origin
            )
            origin_station = origin_resolution.station
            intermediate: dict[str, Any] = {"origin_station": origin_station}
            if stop_after_stage == "origin_station_lookup":
                return {
                    "stage": stop_after_stage,
                    "result": intermediate,
                    "timings": timings,
                }

            async def find_destination() -> StationCodeResolution:
                return await self.resolve_station_code(
                    destination,
                    destination_code,
                    destination_location_id,
                    not skip_station_lookup,
                )

            destination_resolution, timings["destination_station_lookup"] = (
                await self._stage(
                    "destination_station_lookup", origin, destination, find_destination
                )
            )
            destination_station = destination_resolution.station
            intermediate["destination_station"] = destination_station
            if stop_after_stage == "destination_station_lookup":
                return {
                    "stage": stop_after_stage,
                    "result": intermediate,
                    "timings": timings,
                }

            if origin_station.code == destination_station.code:
                raise SameStationCodeError(
                    origin=origin,
                    destination=destination,
                    origin_code=origin_station.code,
                    destination_code=destination_station.code,
                    origin_source=origin_resolution.source,
                    destination_source=destination_resolution.source,
                )

            async def resolved_codes() -> dict[str, str]:
                return {
                    "origin": origin_station.code,
                    "destination": destination_station.code,
                    "origin_source": origin_resolution.source,
                    "destination_source": destination_resolution.source,
                }

            intermediate["station_codes"], timings["station_codes_resolved"] = (
                await self._stage(
                    "station_codes_resolved", origin, destination, resolved_codes
                )
            )
            if stop_after_stage == "station_codes_resolved":
                return {
                    "stage": stop_after_stage,
                    "result": intermediate,
                    "timings": timings,
                }

            async def init_sdk() -> Any:
                return self._get_sdk()

            _, timings["sdk_init"] = await self._stage(
                "sdk_init", origin, destination, init_sdk
            )

            async def search_tickets() -> Any:
                return await self._retry(
                    self._get_sdk().search_tickets,
                    self.config.ticket_search_timeout_seconds,
                    origin_station.code,
                    destination_station.code,
                    departure_date,
                    adults=passengers,
                    children=0,
                )

            raw, timings["ticket_search"] = await self._stage(
                "ticket_search", origin, destination, search_tickets
            )
            if stop_after_stage == "ticket_search":
                intermediate["raw"] = raw
                return {
                    "stage": stop_after_stage,
                    "result": intermediate,
                    "timings": timings,
                }

            mapping_started = time.monotonic()
            self._stage_log(
                "stage_started", "result_mapping", origin, destination, mapping_started
            )
            trains = []
            try:
                items = raw if isinstance(raw, list) else raw.outbound
                for item in items:
                    if is_dataclass(item):
                        sdk_fields = asdict(item)
                        raw_fields = sdk_fields.pop("raw", None)
                        snapshot = {
                            **(raw_fields if isinstance(raw_fields, dict) else {}),
                            **sdk_fields,
                        }
                    else:
                        snapshot = dict(item.raw or {})
                    # Keep detailed ``cars``/``carriages`` from the raw RZD
                    # response.  ``car_groups`` is aggregate inventory and must
                    # not overwrite concrete place evidence.
                    snapshot.update(
                        number=item.number,
                        departure_time=item.departure_time,
                        arrival_time=item.arrival_time,
                        min_price=item.min_price,
                        car_groups=[
                            asdict(group) if is_dataclass(group) else group
                            for group in item.car_groups
                        ],
                    )
                    trains.append(map_train(snapshot))
            except Exception as exc:
                self._stage_log(
                    "stage_failed",
                    "result_mapping",
                    origin,
                    destination,
                    mapping_started,
                    exc,
                )
                raise
            self._stage_log(
                "stage_completed",
                "result_mapping",
                origin,
                destination,
                mapping_started,
            )
            result = RZDSearchResult(
                origin_station,
                destination_station,
                tuple(trains),
                raw,
                origin_resolution.source,
                destination_resolution.source,
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
