from __future__ import annotations

import gc
import json
import logging
import os
import re
import sqlite3
import tempfile
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
SQLITE_PATH = Path(os.getenv("YANDEX_STATIONS_SQLITE_PATH", "/tmp/business-trip-route-planner/yandex_stations.sqlite3"))
YANDEX_STATIONS_AUTO_SYNC = os.getenv("YANDEX_STATIONS_AUTO_SYNC", "false").lower() in {"1", "true", "yes", "on"}
logger = logging.getLogger(__name__)

STOP_WORDS = {"вокзал", "станция", "ст", "жд", "ж д", "железнодорожный", "железнодорожная"}
ALIASES = {"спб": "санкт петербург", "питер": "санкт петербург", "мск": "москва", "екб": "екатеринбург", "нск": "новосибирск", "moscow": "москва"}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"\s*\((?:train|bus|train/bus|поезд|автобус|поезд/автобус)\)\s*$", "", text)
    text = re.sub(r"[\-–—.,/]+", " ", text); text = re.sub(r"\bж\s*д\b", "жд", text)
    words = [w for w in text.split() if w not in STOP_WORDS]
    text = " ".join(words)
    return ALIASES.get(text, text)


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
    code: str; title: str; type: YandexPointType
    transport_types: tuple[str, ...] = field(default_factory=tuple)
    stations: tuple[YandexStation, ...] = field(default_factory=tuple)
    latitude: float | None = None; longitude: float | None = None
    aliases_used: tuple[str, ...] = field(default_factory=tuple)
    source: str = "local"; cache_hit: bool = False
    country: str | None = None; region: str | None = None; settlement: str | None = None; station_type: str | None = None
    confidence: float = 1.0
    @property
    def station_codes(self) -> tuple[str, ...]:
        return (self.code,) if self.type == "station" else (tuple(s.code for s in self.stations) or (self.code,))
    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "code": self.code, "type": self.type, "country": self.country, "region": self.region, "settlement": self.settlement, "station_type": self.station_type, "transport_types": list(self.transport_types), "latitude": self.latitude, "longitude": self.longitude, "confidence": self.confidence, "stations": [s.__dict__ | {"transport_types": list(s.transport_types), "aliases": list(s.aliases)} for s in self.stations], "aliases_used": list(self.aliases_used), "source": self.source, "cache_hit": self.cache_hit}

LOCAL_POINTS: tuple[YandexLocationMatch, ...] = (
    YandexLocationMatch("c213", "Москва", "city", ("train", "bus"), (YandexStation("s2000003", "Москва Казанская", "railway_station", ("train",), settlement="Москва"), YandexStation("s2006004", "Москва Ленинградская", "railway_station", ("train",), settlement="Москва")), aliases_used=("мск", "moscow"), region="Москва", settlement="Москва"),
    YandexLocationMatch("c2", "Санкт-Петербург", "city", ("train", "bus"), (YandexStation("s9602494", "Санкт-Петербург-Главн.", "railway_station", ("train",), settlement="Санкт-Петербург"),), aliases_used=("спб", "питер", "санкт петербург", "санкт-петербург"), region="Санкт-Петербург", settlement="Санкт-Петербург"),
    YandexLocationMatch("c42", "Сарапул", "city", ("train", "bus"), (YandexStation("s9612363", "Сарапул", "railway_station", ("train",), settlement="Сарапул"), YandexStation("s9635668", "Автовокзал Сарапул", "bus_station", ("bus",), settlement="Сарапул")), region="Удмуртия", settlement="Сарапул"),
    YandexLocationMatch("c197", "Бийск", "city", ("train", "bus"), (YandexStation("s9610404", "Бийск", "railway_station", ("train",), settlement="Бийск"),), region="Алтайский край", settlement="Бийск"),
    YandexLocationMatch("c54", "Екатеринбург", "city", ("train", "bus"), region="Свердловская область", settlement="Екатеринбург"),
    YandexLocationMatch("c65", "Новосибирск", "city", ("train", "bus"), (YandexStation("s9610189", "Новосибирск-главный", "railway_station", ("train",), settlement="Новосибирск"),), region="Новосибирская область", settlement="Новосибирск"),
)

class YandexStationsRepository:
    def resolve(self, query: str, transport_types: list[str] | tuple[str, ...] | None = None) -> list[YandexLocationMatch]: raise NotImplementedError
    def get_by_code(self, code: str) -> YandexLocationMatch | None: raise NotImplementedError
    def list_stations_for_settlement(self, settlement: str, transport_types: list[str] | tuple[str, ...] | None = None) -> list[YandexStation]: raise NotImplementedError
    def cache_info(self) -> dict[str, Any]: raise NotImplementedError
    def refresh(self) -> dict[str, Any]: raise NotImplementedError

class SQLiteYandexStationsRepository(YandexStationsRepository):
    def __init__(self, path: Path = SQLITE_PATH, loader=None, json_cache_path: Path = CACHE_PATH):
        self.path = path; self.loader = loader; self.json_cache_path = json_cache_path; self._initialized = False
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path); con.row_factory = sqlite3.Row; return con
    def _ensure_schema(self):
        if self._initialized and self.path.exists(): return
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS locations(code TEXT PRIMARY KEY,title TEXT NOT NULL,normalized_title TEXT NOT NULL,point_type TEXT NOT NULL,settlement TEXT,normalized_settlement TEXT,region TEXT,country TEXT,station_type TEXT,transport_types TEXT,latitude REAL,longitude REAL,aliases TEXT);
            CREATE INDEX IF NOT EXISTS idx_locations_normalized_title ON locations(normalized_title);
            CREATE INDEX IF NOT EXISTS idx_locations_code ON locations(code);
            CREATE INDEX IF NOT EXISTS idx_locations_settlement ON locations(normalized_settlement);
            CREATE INDEX IF NOT EXISTS idx_locations_region ON locations(region);
            """)
        self._initialized = True
    def cache_info(self):
        exists = self.path.exists(); count = 0
        if exists:
            self._ensure_schema()
            with self._connect() as con: count = con.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
        return {"storage": "sqlite", "path": str(self.path), "exists": exists, "locations": count, "mtime": self.path.stat().st_mtime if exists else None}
    def resolve(self, query, transport_types=None):
        self._ensure_schema(); key = normalize(query); rows=[]
        with self._connect() as con:
            rows = list(con.execute("SELECT * FROM locations WHERE normalized_title=? OR code=? OR aliases LIKE ? OR normalized_settlement=? LIMIT 20", (key, query, f"%|{key}|%", key)))
            if not rows and len(key) >= 4:
                rows = list(con.execute("SELECT * FROM locations WHERE normalized_title LIKE ? OR normalized_settlement LIKE ? LIMIT 20", (key+"%", key+"%")))
        return [self._row_to_match(r) for r in rows if self._transport_ok(r, transport_types)]
    def get_by_code(self, code):
        self._ensure_schema()
        with self._connect() as con: row = con.execute("SELECT * FROM locations WHERE code=?", (code,)).fetchone()
        return self._row_to_match(row) if row else None
    def list_stations_for_settlement(self, settlement, transport_types=None):
        self._ensure_schema(); key=normalize(settlement)
        with self._connect() as con: rows=list(con.execute("SELECT * FROM locations WHERE point_type='station' AND normalized_settlement=?", (key,)))
        return [self._row_to_station(r) for r in rows if self._transport_ok(r, transport_types)]
    def refresh(self):
        if not self.loader: raise RuntimeError("Yandex stations loader is not configured; run sync outside web process or provide cache")
        data = self.loader(); return self.rebuild_from_directory(data)
    def rebuild_from_directory(self, directory: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp"); os.close(fd); tmp=Path(tmp_name)
        count=0
        try:
            con=sqlite3.connect(tmp)
            con.executescript("CREATE TABLE locations(code TEXT PRIMARY KEY,title TEXT NOT NULL,normalized_title TEXT NOT NULL,point_type TEXT NOT NULL,settlement TEXT,normalized_settlement TEXT,region TEXT,country TEXT,station_type TEXT,transport_types TEXT,latitude REAL,longitude REAL,aliases TEXT); CREATE INDEX idx_locations_normalized_title ON locations(normalized_title); CREATE INDEX idx_locations_code ON locations(code); CREATE INDEX idx_locations_settlement ON locations(normalized_settlement); CREATE INDEX idx_locations_region ON locations(region);")
            for m in LOCAL_POINTS: count += self._insert_match(con, m)
            for country in directory.get("countries", []):
                country_title=country.get("title")
                for region in country.get("regions", []):
                    region_title=region.get("title")
                    for settlement in region.get("settlements", []):
                        st_title=settlement.get("title"); city_code=(settlement.get("codes") or {}).get("yandex_code")
                        station_rows=[]
                        for item in settlement.get("stations", []):
                            code=item.get("code") or (item.get("codes") or {}).get("yandex_code"); title=item.get("title")
                            if not code or not title: continue
                            transport=item.get("transport_type") or item.get("station_type") or ""; transports=tuple(x for x in (transport,) if x in {"train","bus","suburban","plane","water"})
                            station=YandexStation(str(code), title, item.get("station_type") or "station", transports, item.get("latitude"), item.get("longitude"), country_title, region_title, st_title)
                            station_rows.append(station); count += self._insert_match(con, YandexLocationMatch(station.code, station.title, "station", station.transport_types, (station,), station.latitude, station.longitude, country=country_title, region=region_title, settlement=st_title, station_type=station.type, source="stations_list"))
                        if st_title and city_code:
                            transports=tuple(sorted({t for s in station_rows for t in s.transport_types}))
                            count += self._insert_match(con, YandexLocationMatch(str(city_code), st_title, "city", transports, tuple(station_rows[:50]), country=country_title, region=region_title, settlement=st_title, source="stations_list"))
            con.commit(); con.close(); os.replace(tmp, self.path); self._initialized=True; gc.collect(); return self.cache_info() | {"written": count}
        finally:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
    def _insert_match(self, con, m):
        aliases="|"+"|".join(sorted({normalize(a) for a in m.aliases_used if a}))+"|"
        con.execute("INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (m.code,m.title,normalize(m.title),m.type,m.settlement,normalize(m.settlement or ""),m.region,m.country,m.station_type,",".join(m.transport_types),m.latitude,m.longitude,aliases)); return 1
    def _transport_ok(self, row, types):
        if not types: return True
        have=set((row["transport_types"] or "").split(","))-{""}; want=set(types); want |= {"suburban"} if "train" in want else set(); return not have or bool(have & want)
    def _row_to_station(self, r): return YandexStation(r["code"], r["title"], r["station_type"] or "station", tuple(filter(None,(r["transport_types"] or "").split(","))), r["latitude"], r["longitude"], r["country"], r["region"], r["settlement"])
    def _row_to_match(self, r):
        station = self._row_to_station(r) if r["point_type"] == "station" else None
        stations = (station,) if station else tuple(self.list_stations_for_settlement(r["settlement"] or r["title"], (r["transport_types"] or "").split(","))[:50])
        return YandexLocationMatch(r["code"], r["title"], r["point_type"], tuple(filter(None,(r["transport_types"] or "").split(","))), stations, r["latitude"], r["longitude"], source="sqlite", country=r["country"], region=r["region"], settlement=r["settlement"], station_type=r["station_type"])

class YandexStationsCache:
    def __init__(self, loader=None, path: Path = CACHE_PATH, ttl_seconds: int = CACHE_TTL_SECONDS): self.loader=loader; self.path=path; self.ttl_seconds=ttl_seconds; self.last_source="fallback"; self.last_error=None
    def age_seconds(self):
        try: return time.time()-self.path.stat().st_mtime
        except FileNotFoundError: return None
    def load(self, *, force=False):
        if not force: return None
        if not self.loader: return None
        return self.loader()

class YandexLocationResolver:
    def __init__(self, directory_loader=None, repository: LocationRepository | None = None, cache_path: Path = CACHE_PATH, ttl_seconds: int = CACHE_TTL_SECONDS, stations_repository: YandexStationsRepository | None = None):
        self._repository = repository or location_repository
        self._directory_cache = YandexStationsCache(directory_loader, cache_path, ttl_seconds)
        sqlite_path = cache_path.with_suffix(".sqlite3") if cache_path != CACHE_PATH else SQLITE_PATH
        self._stations_repository = stations_repository or SQLiteYandexStationsRepository(path=sqlite_path, loader=directory_loader)
        self._cache: dict[str, list[YandexLocationMatch]] = {}; self._last_diag: dict[str, Any] = {}; self._initialized=False
    normalize = staticmethod(normalize)
    def resolve(self, query: str) -> YandexLocationMatch:
        matches=self.resolve_all(query)
        if not matches: raise YandexRaspUnknownCityError(f"Неизвестный город или станция для Яндекс Расписаний: {query}")
        return matches[0]
    def resolve_code(self, code: str, fallback_title: str | None = None) -> YandexLocationMatch:
        self._maybe_seed_repository()
        match = self._stations_repository.get_by_code(code)
        if match:
            return match
        for item in LOCAL_POINTS:
            if item.code == code:
                return item
            for station in item.stations:
                if station.code == code:
                    return YandexLocationMatch(station.code, station.title, "station", station.transport_types, (station,), station.latitude, station.longitude, country=station.country, region=station.region, settlement=station.settlement, station_type=station.type)
        point_type: YandexPointType = "city" if code.startswith("c") else "station"
        title = fallback_title or code
        return YandexLocationMatch(code, title, point_type, settlement=title if point_type == "city" else None, source="provider_code")
    def resolve_all(self, query: str) -> list[YandexLocationMatch]:
        self._maybe_seed_repository()
        self._initialized=True; key=normalize(query)
        if key in self._cache: return [self._with_cache_hit(m) for m in self._cache[key]]
        matches=self._stations_repository.resolve(query) or self._local(query) or self._fallback_repository(query)
        self._cache[key]=matches; self._last_diag={"source":self._directory_cache.last_source if self._directory_cache.last_source != "fallback" else ("cache" if self._stations_repository.cache_info().get("locations", 0) else "sqlite"),"cache_info":self._stations_repository.cache_info(),"selected_codes":[m.code for m in matches],"ambiguous":len(matches)>1}
        return matches
    def diagnostic(self, query): return {"query":query,"normalized_query":normalize(query),"matches":[m.to_dict() for m in self.resolve_all(query)],"diagnostics":self._last_diag}
    def _maybe_seed_repository(self):
        info = self._stations_repository.cache_info()
        if info.get("locations", 0) == 0 and self._directory_cache.loader:
            try:
                self._stations_repository.refresh()
                self._directory_cache.last_source = "remote"
            except Exception as exc:
                self._directory_cache.last_error = str(exc) or exc.__class__.__name__
    def refresh(self):
        self._cache.clear()
        stats = self._stations_repository.refresh()
        self._directory_cache.last_source = "remote"
        return stats | {"total_points": stats.get("locations", 0)}
    def warm_from_existing_cache(self): self._stations_repository.cache_info()
    def startup_refresh_background(self):
        if YANDEX_STATIONS_AUTO_SYNC: logger.warning("YANDEX_STATIONS_AUTO_SYNC is enabled; prefer build-job sync in production")
    def stats(self): return self._stations_repository.cache_info() | {"lazy_load": True, "auto_sync": YANDEX_STATIONS_AUTO_SYNC}
    def _local(self, query):
        key=normalize(query); res=[]
        for m in LOCAL_POINTS:
            keys={normalize(m.title), normalize(m.code), *(normalize(a) for a in m.aliases_used)}
            if key in keys: res.append(m)
        return res
    def _fallback_repository(self, query):
        matches=[]
        for item in self._repository.suggest(query, 10):
            if item.provider_code:
                pt: YandexPointType = "city" if item.type in {"city", "settlement"} else "station"
                matches.append(YandexLocationMatch(item.provider_code, item.name, pt, source="location_repository", region=item.region, country=item.country, settlement=item.name if pt == "city" else None))
        return matches
    def _with_cache_hit(self, m): return YandexLocationMatch(**{**m.__dict__, "cache_hit": True})
