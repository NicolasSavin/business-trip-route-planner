from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal
from collections import OrderedDict

from pydantic import BaseModel

LocationType = Literal["city", "station", "bus_station", "railway_station", "settlement"]


class LocationSuggestion(BaseModel):
    id: str
    name: str
    display_name: str
    type: LocationType
    provider_code: str | None = None
    region: str | None = None
    country: str | None = "Россия"


class LocationSuggestResponse(BaseModel):
    items: list[LocationSuggestion]


class LocationNormalizer:
    aliases = {
        "спб": "санкт петербург",
        "питер": "санкт петербург",
        "нижний": "нижний новгород",
        "ростов": "ростов на дону",
    }

    @classmethod
    def normalize(cls, text: str) -> str:
        value = " ".join(text.lower().replace("ё", "е").replace("-", " ").split())
        return cls.aliases.get(value, value)


@dataclass(frozen=True)
class LocationRecord:
    id: str
    name: str
    display_name: str
    type: LocationType
    provider_code: str | None
    region: str | None
    country: str = "Россия"
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def searchable(self) -> tuple[str, ...]:
        return tuple(LocationNormalizer.normalize(item) for item in (self.name, self.display_name, *self.aliases))

    def to_suggestion(self) -> LocationSuggestion:
        return LocationSuggestion(**{k: getattr(self, k) for k in ("id", "name", "display_name", "type", "provider_code", "region", "country")})


DEFAULT_LOCATIONS = [
    LocationRecord("city:c213", "Москва", "Москва", "city", "c213", "Москва", aliases=("мск", "moscow")),
    LocationRecord("station:s2000003", "Москва Казанская", "Москва, Казанский вокзал", "railway_station", "s2000003", "Москва", aliases=("казанский вокзал", "москва казанский")),
    LocationRecord("station:s2006004", "Москва Ленинградская", "Москва, Ленинградский вокзал", "railway_station", "s2006004", "Москва", aliases=("ленинградский вокзал", "москва ленинградский")),
    LocationRecord("station:s9879173", "Москва Восточная", "Москва, Восточный вокзал", "railway_station", "s9879173", "Москва", aliases=("восточный вокзал",)),
    LocationRecord("city:c2", "Санкт-Петербург", "Санкт-Петербург", "city", "c2", "Санкт-Петербург", aliases=("спб", "питер", "санкт петербург")),
    LocationRecord("station:s9602494", "Санкт-Петербург-Главн.", "Санкт-Петербург, Московский вокзал", "railway_station", "s9602494", "Санкт-Петербург", aliases=("московский вокзал",)),
    LocationRecord("city:c42", "Сарапул", "Сарапул", "city", "c42", "Удмуртия"),
    LocationRecord("city:c197", "Бийск", "Бийск", "city", "c197", "Алтайский край"),
    LocationRecord("station:s9610404", "Бийск", "Бийск, железнодорожная станция", "railway_station", "s9610404", "Алтайский край"),
    LocationRecord("city:c194", "Саратов", "Саратов", "city", "c194", "Саратовская область"),
    LocationRecord("city:c195", "Саранск", "Саранск", "city", "c195", "Мордовия"),
    LocationRecord("city:c51", "Нижний Новгород", "Нижний Новгород", "city", "c51", "Нижегородская область", aliases=("нижний",)),
    LocationRecord("city:c39", "Ростов-на-Дону", "Ростов-на-Дону", "city", "c39", "Ростовская область", aliases=("ростов",)),
    LocationRecord("city:c54", "Екатеринбург", "Екатеринбург", "city", "c54", "Свердловская область", aliases=("екатеринбург",)),
    LocationRecord("city:c65", "Новосибирск", "Новосибирск", "city", "c65", "Новосибирская область"),
    LocationRecord("city:c43", "Казань", "Казань", "city", "c43", "Татарстан"),
    LocationRecord("city:c172", "Уфа", "Уфа", "city", "c172", "Башкортостан"),
    LocationRecord("city:c35", "Краснодар", "Краснодар", "city", "c35", "Краснодарский край"),
]


class TtlCache:
    def __init__(self, ttl_seconds: int = 1200, max_size: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: OrderedDict[tuple[str, int], tuple[float, list[LocationSuggestion]]] = OrderedDict()

    def get(self, key: tuple[str, int]) -> list[LocationSuggestion] | None:
        item = self._items.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: tuple[str, int], value: list[LocationSuggestion]) -> None:
        self._items[key] = (time.time() + self.ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)


class LocationRepository:
    def __init__(self, records: list[LocationRecord] | None = None, cache: TtlCache | None = None):
        self.records = records or DEFAULT_LOCATIONS
        self.cache = cache or TtlCache()

    def suggest(self, query: str, limit: int = 10) -> list[LocationSuggestion]:
        normalized = LocationNormalizer.normalize(query)
        limit = max(1, min(limit, 10))
        if len(normalized) < 2:
            return []
        key = (normalized, limit)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        ranked: list[tuple[int, int, str, LocationRecord]] = []
        type_rank = {"city": 0, "settlement": 1, "railway_station": 2, "bus_station": 3, "station": 4}
        for record in self.records:
            best: int | None = None
            for text in record.searchable:
                words = text.split()
                if text == normalized:
                    score = 0
                elif text.startswith(normalized):
                    score = 1
                elif any(word.startswith(normalized) for word in words):
                    score = 2
                elif normalized in text:
                    score = 3
                else:
                    continue
                best = score if best is None else min(best, score)
            if best is not None:
                ranked.append((best, type_rank[record.type], record.display_name, record))
        result = [record.to_suggestion() for *_ignore, record in sorted(ranked)[:limit]]
        self.cache.set(key, result)
        return result


location_repository = LocationRepository()
