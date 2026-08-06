from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from app.providers.rzd_availability.models import RZDStation

_EXPRESS_CODE = re.compile(r"^\d{7}$")
_YANDEX_STATION_CODE = re.compile(r"^s(\d{7})$", re.IGNORECASE)


@dataclass(frozen=True)
class StationCodeResolution:
    station: RZDStation
    source: str
    sdk_lookup_used: bool = False


class StationCodeResolver:
    """Resolve Express-3 codes without making remote lookup the normal path.

    The JSON directory is deliberately data, rather than Python conditionals, so it
    can be expanded or replaced by a generated cache. Yandex city codes (``c213``)
    are never treated as Express-3 codes; only seven-digit station codes and the
    equivalent Yandex ``s<digits>`` representation are format-compatible.
    """

    def __init__(self, mapping_path: Path | None = None):
        path = mapping_path or Path(__file__).with_name("station_mappings.json")
        records = json.loads(path.read_text(encoding="utf-8"))
        self._mapping = {record["normalized_name"]: record for record in records}

    @staticmethod
    def normalize_name(value: str) -> str:
        return " ".join(value.strip().casefold().replace("ё", "е").split())

    async def resolve(
        self,
        query: str,
        provider_code: str | None = None,
        location_id: str | None = None,
        sdk_lookup: Callable[[str], Awaitable[RZDStation]] | None = None,
        allow_sdk_lookup: bool = True,
    ) -> StationCodeResolution:
        for candidate in (provider_code, location_id):
            code = self._compatible_code(candidate)
            if code:
                return StationCodeResolution(RZDStation(code, query), "mapping")

        record = self._mapping.get(self.normalize_name(query))
        if record:
            return StationCodeResolution(RZDStation(record["rzd_code"], query), "cache")

        if allow_sdk_lookup and sdk_lookup is not None:
            return StationCodeResolution(
                await sdk_lookup(query), "sdk", sdk_lookup_used=True
            )
        raise ValueError(f"RZD station code is required for {query!r}")

    @staticmethod
    def _compatible_code(value: str | None) -> str | None:
        if not value:
            return None
        value = value.rsplit(":", 1)[-1].strip()
        if _EXPRESS_CODE.fullmatch(value):
            return value
        matched = _YANDEX_STATION_CODE.fullmatch(value)
        return matched.group(1) if matched else None
