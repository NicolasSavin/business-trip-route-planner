from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from app.locations import LocationRepository, location_repository
from app.providers.yandex.exceptions import YandexRaspUnknownCityError

YandexPointType = Literal["city", "station"]
CACHE_TTL_SECONDS = int(os.getenv("YANDEX_STATIONS_CACHE_TTL_SECONDS", str(7 * 24 * 60 * 60)))
CACHE_PATH = Path(os.getenv("YANDEX_STATIONS_CACHE_PATH", "/tmp/business-trip-route-planner/yandex_stations_list.json"))
logger = logging.getLogger(__name__)

STOP_WORDS = {"вокзал", "станция", "ст", "жд", "ж д", "железнодорожный", "железнодорожная"}
ALIASES = {"спб": "санкт петербург", "питер": "санкт петербург", "мск": "москва", "екб": "екатеринбург", "нск": "новосибирск"}


@dataclass(frozen=True)
class YandexStation:
    code: str
    title: str
    type: str = "station"
    transport_types: tuple[str, ...] = field(default_factory=tuple)
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    region: str | None = None
    settlement: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


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
    country: str | None = None
    region: str | None = None
    settlement: str | None = None
    station_type: str | None = None
    confidence: float = 1.0

    @property
    def station_codes(self) -> tuple[str, ...]:
        if self.type == "station":
            return (self.code,)
        return tuple(station.code for station in self.stations) or (self.code,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "code": self.code, "type": self.type, "country": self.country,
            "region": self.region, "settlement": self.settlement, "station_type": self.station_type,
            "transport_types": list(self.transport_types), "latitude": self.latitude, "longitude": self.longitude,
            "confidence": self.confidence,
            "stations": [station.__dict__ | {"transport_types": list(station.transport_types), "aliases": list(station.aliases)} for station in self.stations],
            "aliases_used": list(self.aliases_used), "source": self.source, "cache_hit": self.cache_hit,
        }


LOCAL_POINTS: tuple[YandexLocationMatch, ...] = (
    YandexLocationMatch("c213", "Москва", "city", ("train", "bus"), (YandexStation("s2000003", "Москва Казанская", "railway_station", ("train",), settlement="Москва"), YandexStation("s2006004", "Москва Ленинградская", "railway_station", ("train",), settlement="Москва"), YandexStation("s9879173", "Москва Восточная", "railway_station", ("train",), settlement="Москва")), aliases_used=("мск", "moscow"), region="Москва", settlement="Москва"),
    YandexLocationMatch("c2", "Санкт-Петербург", "city", ("train", "bus"), (YandexStation("s9602494", "Санкт-Петербург-Главн.", "railway_station", ("train",), settlement="Санкт-Петербург"),), aliases_used=("спб", "питер", "санкт петербург", "санкт-петербург"), region="Санкт-Петербург", settlement="Санкт-Петербург"),
    YandexLocationMatch("c42", "Сарапул", "city", ("train", "bus"), (YandexStation("s9612363", "Сарапул", "railway_station", ("train",), settlement="Сарапул"), YandexStation("s9635668", "Автовокзал Сарапул", "bus_station", ("bus",), settlement="Сарапул")), region="Удмуртия", settlement="Сарапул"),
    YandexLocationMatch("c197", "Бийск", "city", ("train", "bus"), (YandexStation("s9610404", "Бийск", "railway_station", ("train",), settlement="Бийск"), YandexStation("s9657040", "автовокзал Бийск", "bus_station", ("bus",), settlement="Бийск")), region="Алтайский край", settlement="Бийск"),
    YandexLocationMatch("c54", "Екатеринбург", "city", ("train", "bus"), source="local", region="Свердловская область", settlement="Екатеринбург"),
    YandexLocationMatch("c65", "Новосибирск", "city", ("train", "bus"), (YandexStation("s9610189", "Новосибирск-главный", "railway_station", ("train",), settlement="Новосибирск"),), region="Новосибирская область", settlement="Новосибирск"),
)


class YandexStationsCache:
    def __init__(self, loader=None, path: Path = CACHE_PATH, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.loader, self.path, self.ttl_seconds = loader, path, ttl_seconds
        self.last_source = "fallback"
        self.last_error: str | None = None

    def load(self, *, force: bool = False) -> dict[str, Any] | None:
        cached = self._read()
        if cached and not force and self.age_seconds() is not None and self.age_seconds() < self.ttl_seconds:
            self.last_source = "cache"; return cached
        if self.loader:
            try:
                remote = self.loader()
                self._write(remote)
                self.last_source = "remote"; self.last_error = None
                return remote
            except Exception as exc:
                self.last_error = str(exc) or exc.__class__.__name__
                logger.warning("Yandex stations_list sync failed, using cache/fallback: %s", self.last_error)
        if cached:
            self.last_source = "cache"; return cached
        self.last_source = "fallback"; return None

    def refresh_background(self) -> None:
        threading.Thread(target=lambda: self.load(force=True), name="yandex-stations-sync", daemon=True).start()

    def age_seconds(self) -> float | None:
        try: return time.time() - self.path.stat().st_mtime
        except FileNotFoundError: return None

    def _read(self) -> dict[str, Any] | None:
        try:
            with self.path.open("r", encoding="utf-8") as fh: return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError): return None

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh: json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, self.path)


class YandexLocationResolver:
    def __init__(self, directory_loader=None, repository: LocationRepository | None = None, cache_path: Path = CACHE_PATH, ttl_seconds: int = CACHE_TTL_SECONDS):
        self._repository = repository or location_repository
        self._directory_cache = YandexStationsCache(directory_loader, cache_path, ttl_seconds)
        self._loaded = False; self._cache: dict[str, list[YandexLocationMatch]] = {}
        self._matches: list[YandexLocationMatch] = list(LOCAL_POINTS); self._index: dict[str, list[YandexLocationMatch]] = {}
        self._last_diag: dict[str, Any] = {}; self._rebuild_index()

    def resolve(self, query: str) -> YandexLocationMatch:
        matches = self.resolve_all(query)
        if not matches: raise YandexRaspUnknownCityError(f"Неизвестный город или станция для Яндекс Расписаний: {query}")
        if len(matches) > 1 and matches[0].confidence < 0.95:
            raise YandexRaspUnknownCityError(f"Неоднозначный город или станция для Яндекс Расписаний: {query}")
        return matches[0]

    def resolve_all(self, query: str) -> list[YandexLocationMatch]:
        self._ensure_loaded(); key = self.normalize(query)
        if key in self._cache: return [self._with_cache_hit(m) for m in self._cache[key]]
        exact = self._dedupe(self._index.get(key, [])); fuzzy: list[YandexLocationMatch] = []
        if not exact:
            fuzzy = self._fuzzy(key)
        matches = exact or fuzzy or self._fallback_repository(query)
        self._cache[key] = matches
        self._last_diag = {"source": self._directory_cache.last_source, "cache_age": self._directory_cache.age_seconds(), "total_points": len(self._matches), "exact_matches": len(exact), "fuzzy_matches": len(fuzzy), "ambiguous": len(matches) > 1, "selected_codes": [m.code for m in matches]}
        return matches

    def diagnostic(self, query: str) -> dict[str, Any]:
        matches = self.resolve_all(query)
        return {"query": query, "normalized_query": self.normalize(query), "matches": [m.to_dict() for m in matches], "diagnostics": self._last_diag}

    def refresh(self) -> dict[str, Any]:
        directory = self._directory_cache.load(force=True)
        self._matches = list(LOCAL_POINTS)
        if directory: self._load_directory(directory)
        self._rebuild_index(); self._cache.clear(); self._loaded = True
        stats = self.stats(); logger.info("Yandex stations loaded: %s", stats); return stats

    def warm_from_existing_cache(self) -> None:
        directory = self._directory_cache._read()
        if directory:
            self._matches = list(LOCAL_POINTS)
            self._load_directory(directory)
            self._directory_cache.last_source = "cache"
            self._loaded = True
            self._rebuild_index()

    def startup_refresh_background(self) -> None:
        threading.Thread(target=self.refresh, name="yandex-stations-sync", daemon=True).start()

    def stats(self) -> dict[str, Any]:
        return {"cache_path": str(self._directory_cache.path), "cache_ttl_seconds": self._directory_cache.ttl_seconds, "cache_age": self._directory_cache.age_seconds(), "source": self._directory_cache.last_source, "countries": len({m.country for m in self._matches if m.country}), "regions": len({m.region for m in self._matches if m.region}), "settlements": len({m.settlement for m in self._matches if m.settlement}), "stations": len({m.code for m in self._matches if m.type == "station"}), "total_points": len({m.code for m in self._matches})}

    @classmethod
    def normalize(cls, value: str) -> str:
        text = unicodedata.normalize("NFKC", value or "").strip().lower().replace("ё", "е")
        text = re.sub(r"[\-–—.,/]+", " ", text); text = re.sub(r"\bж\s*д\b", "жд", text)
        words = [w for w in text.split() if w not in STOP_WORDS]
        text = " ".join(words); return ALIASES.get(text, text)

    def _ensure_loaded(self) -> None:
        if self._loaded: return
        directory = self._directory_cache.load()
        if directory: self._load_directory(directory)
        self._loaded = True; self._rebuild_index()

    def _load_directory(self, directory: dict[str, Any]) -> None:
        for country in directory.get("countries", []):
            country_title = country.get("title")
            for region in country.get("regions", []):
                region_title = region.get("title")
                for settlement in region.get("settlements", []):
                    st_title = settlement.get("title"); code = (settlement.get("codes") or {}).get("yandex_code")
                    stations = tuple(s for s in (self._station(i, country_title, region_title, st_title) for i in settlement.get("stations", [])) if s)
                    if st_title and code:
                        transports = tuple(sorted({t for s in stations for t in s.transport_types}))
                        self._matches.append(YandexLocationMatch(str(code), st_title, "city", transports, stations, country=country_title, region=region_title, settlement=st_title, source="stations_list"))
                    for station in stations:
                        self._matches.append(YandexLocationMatch(station.code, station.title, "station", station.transport_types, (station,), station.latitude, station.longitude, country=country_title, region=region_title, settlement=st_title, station_type=station.type, source="stations_list"))

    def _station(self, item: dict[str, Any], country: str | None, region: str | None, settlement: str | None) -> YandexStation | None:
        code = item.get("code") or (item.get("codes") or {}).get("yandex_code"); title = item.get("title")
        if not code or not title: return None
        transport = item.get("transport_type") or item.get("station_type") or ""
        transports = tuple(x for x in (transport,) if x in {"train", "bus", "suburban", "plane", "water"})
        return YandexStation(str(code), title, item.get("station_type") or "station", transports, item.get("latitude"), item.get("longitude"), country, region, settlement)

    def _rebuild_index(self) -> None:
        self._index = {}
        for match in self._dedupe(self._matches):
            keys = {self.normalize(match.title), self.normalize(match.code), *(self.normalize(a) for a in match.aliases_used)}
            if match.settlement: keys.add(self.normalize(match.settlement))
            for station in match.stations:
                keys.update({self.normalize(station.title), self.normalize(station.code)})
                if station.settlement: keys.add(self.normalize(f"{station.settlement} {station.title}"))
                keys.update(self.normalize(a) for a in station.aliases)
            for key in keys:
                if key: self._index.setdefault(key, []).append(match)

    def _fuzzy(self, key: str) -> list[YandexLocationMatch]:
        ranked = []
        for idx_key, values in self._index.items():
            ratio = SequenceMatcher(None, key, idx_key).ratio()
            if ratio >= 0.86 or (len(key) >= 4 and idx_key.startswith(key)):
                ranked.extend((ratio, m) for m in values)
        return [self._with_confidence(m, r) for r, m in sorted(ranked, key=lambda x: x[0], reverse=True)[:10] if r >= 0.86]

    def _fallback_repository(self, query: str) -> list[YandexLocationMatch]:
        matches = []
        for item in self._repository.suggest(query, 10):
            if item.provider_code:
                point_type: YandexPointType = "city" if item.type in {"city", "settlement"} else "station"
                matches.append(YandexLocationMatch(item.provider_code, item.name, point_type, source="location_repository", region=item.region, country=item.country, settlement=item.name if point_type == "city" else None))
        return matches

    def _dedupe(self, matches):
        seen = set(); result = []
        for m in matches:
            if m.code not in seen: seen.add(m.code); result.append(m)
        return result

    def _with_cache_hit(self, match: YandexLocationMatch) -> YandexLocationMatch: return YandexLocationMatch(**{**match.__dict__, "cache_hit": True})
    def _with_confidence(self, match: YandexLocationMatch, confidence: float) -> YandexLocationMatch: return YandexLocationMatch(**{**match.__dict__, "confidence": round(confidence, 3)})
