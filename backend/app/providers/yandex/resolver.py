from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from app.locations import LocationRepository, location_repository
from app.providers.yandex.exceptions import YandexRaspUnknownCityError

YandexPointType = Literal["city", "station"]


@dataclass(frozen=True)
class YandexStation:
    code: str
    title: str
    type: str = "station"
    transport_types: tuple[str, ...] = field(default_factory=tuple)
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class YandexLocationMatch:
    code: str
    title: str
    type: YandexPointType
    transport_types: tuple[str, ...] = field(default_factory=tuple)
    stations: tuple[YandexStation, ...] = field(default_factory=tuple)
    latitude: float | None = None
    longitude: float | None = None
    aliases_used: tuple[str, ...] = field(default_factory=tuple)
    source: str = "local"
    cache_hit: bool = False

    @property
    def station_codes(self) -> tuple[str, ...]:
        if self.type == "station":
            return (self.code,)
        return tuple(station.code for station in self.stations) or (self.code,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "code": self.code,
            "type": self.type,
            "transport_types": list(self.transport_types),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "stations": [station.__dict__ | {"transport_types": list(station.transport_types)} for station in self.stations],
            "aliases_used": list(self.aliases_used),
            "source": self.source,
            "cache_hit": self.cache_hit,
        }


# Checked-in cache of high-value official Yandex Rasp point codes. The resolver augments this
# with /v3.0/stations_list/ when available and LocationRepository as a final fallback.
LOCAL_POINTS: tuple[YandexLocationMatch, ...] = (
    YandexLocationMatch("c213", "Москва", "city", ("train", "bus"), (YandexStation("s2000003", "Москва Казанская", "railway_station", ("train",)), YandexStation("s2006004", "Москва Ленинградская", "railway_station", ("train",)), YandexStation("s9879173", "Москва Восточная", "railway_station", ("train",))), aliases_used=("мск", "moscow")),
    YandexLocationMatch("c2", "Санкт-Петербург", "city", ("train", "bus"), (YandexStation("s9602494", "Санкт-Петербург-Главн.", "railway_station", ("train",)),), aliases_used=("спб", "питер", "санкт петербург", "санкт-петербург")),
    YandexLocationMatch("c42", "Сарапул", "city", ("train", "bus"), (YandexStation("s9612363", "Сарапул", "railway_station", ("train",)), YandexStation("s9635668", "Автовокзал Сарапул", "bus_station", ("bus",))), source="local"),
    YandexLocationMatch("c197", "Бийск", "city", ("train", "bus"), (YandexStation("s9610404", "Бийск", "railway_station", ("train",)), YandexStation("s9657040", "автовокзал Бийск", "bus_station", ("bus",))), source="local"),
    YandexLocationMatch("c54", "Екатеринбург", "city", ("train", "bus"), source="local"),
    YandexLocationMatch("c65", "Новосибирск", "city", ("train", "bus"), (YandexStation("s9610189", "Новосибирск-главный", "railway_station", ("train",)),), source="local"),
)

ALIASES = {
    "спб": "санкт петербург",
    "питер": "санкт петербург",
    "мск": "москва",
    "екб": "екатеринбург",
    "нск": "новосибирск",
}


class YandexLocationResolver:
    def __init__(self, directory_loader=None, repository: LocationRepository | None = None):
        self._directory_loader = directory_loader
        self._repository = repository or location_repository
        self._loaded = False
        self._cache: dict[str, list[YandexLocationMatch]] = {}
        self._matches: list[YandexLocationMatch] = list(LOCAL_POINTS)
        self._index: dict[str, list[YandexLocationMatch]] = {}
        self._rebuild_index()

    def resolve(self, query: str) -> YandexLocationMatch:
        matches = self.resolve_all(query)
        if not matches:
            raise YandexRaspUnknownCityError(f"Неизвестный город или станция для Яндекс Расписаний: {query}")
        return matches[0]

    def resolve_all(self, query: str) -> list[YandexLocationMatch]:
        self._ensure_loaded()
        key = self.normalize(query)
        if key in self._cache:
            return [self._with_cache_hit(match) for match in self._cache[key]]
        matches = list(self._index.get(key, []))
        if not matches:
            matches = self._fallback_repository(query)
        self._cache[key] = matches
        return matches

    def diagnostic(self, query: str) -> dict[str, Any]:
        return {"query": query, "normalized_query": self.normalize(query), "matches": [match.to_dict() for match in self.resolve_all(query)]}

    @classmethod
    def normalize(cls, value: str) -> str:
        text = unicodedata.normalize("NFKC", value or "").strip().lower().replace("ё", "е")
        text = re.sub(r"[\-–—.,]+", " ", text)
        text = " ".join(text.split())
        return ALIASES.get(text, text)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._directory_loader:
            self._load_directory(self._directory_loader())
        self._loaded = True
        self._rebuild_index()

    def _load_directory(self, directory: dict[str, Any]) -> None:
        for country in directory.get("countries", []):
            for region in country.get("regions", []):
                for settlement in region.get("settlements", []):
                    title = settlement.get("title")
                    code = (settlement.get("codes") or {}).get("yandex_code")
                    stations = tuple(station for station in (self._station(item) for item in settlement.get("stations", [])) if station)
                    if title and code:
                        transports = tuple(sorted({t for s in stations for t in s.transport_types}))
                        self._matches.append(YandexLocationMatch(code, title, "city", transports, stations, source="stations_list"))
                    for station in stations:
                        self._matches.append(YandexLocationMatch(station.code, station.title, "station", station.transport_types, (station,), station.latitude, station.longitude, source="stations_list"))

    def _station(self, item: dict[str, Any]) -> YandexStation | None:
        code = item.get("code") or (item.get("codes") or {}).get("yandex_code")
        title = item.get("title")
        if not code or not title:
            return None
        ttype = item.get("transport_type") or item.get("station_type") or ""
        transports = tuple(x for x in (ttype,) if x in {"train", "bus", "suburban"})
        return YandexStation(str(code), title, item.get("station_type") or "station", transports, item.get("latitude"), item.get("longitude"))

    def _rebuild_index(self) -> None:
        self._index = {}
        for match in self._matches:
            keys = {self.normalize(match.title), self.normalize(match.code), *(self.normalize(a) for a in match.aliases_used)}
            for station in match.stations:
                keys.add(self.normalize(station.title))
                keys.add(self.normalize(station.code))
            for key in keys:
                self._index.setdefault(key, []).append(match)

    def _fallback_repository(self, query: str) -> list[YandexLocationMatch]:
        items = self._repository.suggest(query, 10)
        matches = []
        for item in items:
            if not item.provider_code:
                continue
            point_type: YandexPointType = "city" if item.type in {"city", "settlement"} else "station"
            matches.append(YandexLocationMatch(item.provider_code, item.name, point_type, source="location_repository"))
        return matches

    def _with_cache_hit(self, match: YandexLocationMatch) -> YandexLocationMatch:
        return YandexLocationMatch(**{**match.__dict__, "cache_hit": True})
