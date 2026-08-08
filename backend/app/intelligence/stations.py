from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from app.domain import Station, TransportSegment


DEFAULT_CITY_STATIONS: dict[str, tuple[str, ...]] = {
    "Москва": ("Казанский вокзал", "Ленинградский вокзал", "Ярославский вокзал", "Восточный вокзал", "Курский вокзал", "Саларьево"),
    "Краснодар": ("Краснодар-1 ЖД вокзал", "Краснодар автовокзал"),
    "Екатеринбург": ("Екатеринбург-Пассажирский ЖД вокзал", "Северный автовокзал"),
    "Санкт-Петербург": ("Московский вокзал", "Ладожский вокзал", "Автовокзал №2"),
    "Новороссийск": ("Новороссийск ЖД вокзал", "Новороссийск автовокзал"),
    "Анапа": ("Анапа ЖД вокзал", "Анапа автовокзал"),
    "Геленджик": ("Геленджик автовокзал",),
}


def normalize_location_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


# Only remove a parenthetical suffix when it is recognisably station metadata.
# Parentheses can be a meaningful part of a settlement's name, so a blanket
# ``rsplit("(")`` would merge unrelated places.
_STATION_QUALIFIER = re.compile(
    r"\b(?:вокзал|вокзала|станция|станции|аэропорт|автовокзал|"
    r"station|terminal|airport)\b",
    flags=re.IGNORECASE,
)
_TRAILING_QUALIFIER = re.compile(r"^(?P<city>.+?)\s*\((?P<qualifier>[^()]*)\)\s*$")


def city_name_without_station_qualifier(value: str) -> str:
    """Remove a recognisable trailing station qualifier, preserving display case."""
    normalized_value = unicodedata.normalize("NFKC", value).strip()
    match = _TRAILING_QUALIFIER.match(normalized_value)
    if match and _STATION_QUALIFIER.search(match.group("qualifier")):
        return match.group("city").strip()
    return normalized_value


def canonical_city_name(value: str) -> str:
    """Return a conservative comparison key for a city display name."""
    return normalize_location_name(city_name_without_station_qualifier(value))


def city_names_match(first: str, second: str) -> bool:
    """Compare city identities without broadening to substring matching."""
    first_key = canonical_city_name(first)
    return bool(first_key) and first_key == canonical_city_name(second)


@dataclass(frozen=True)
class StationResolver:
    city_stations: dict[str, tuple[str, ...]] = field(default_factory=lambda: DEFAULT_CITY_STATIONS.copy())

    def resolve_city_names(self, query: str, segments: list[TransportSegment]) -> tuple[str, ...]:
        normalized = self._normalize(query)
        known_cities = {segment.origin_city.name for segment in segments} | {segment.destination_city.name for segment in segments} | set(self.city_stations)
        for city in known_cities:
            if city_names_match(city, query):
                return (city,)
        # Provider settlements are canonical city names, while a station-level
        # search may carry the station title as its display value.
        for segment in segments:
            for station, city in (
                (segment.origin_station, segment.origin_city),
                (segment.destination_station, segment.destination_city),
            ):
                if self._normalize(station.name) == normalized:
                    return (city.name,)
        for city, stations in self.city_stations.items():
            if any(self._normalize(station) == normalized for station in stations):
                return (city,)
        return (query,)

    def stations_for_city(self, city: str, segments: list[TransportSegment]) -> tuple[Station, ...]:
        stations: dict[str, Station] = {}
        for segment in segments:
            for station in (segment.origin_station, segment.destination_station):
                if city_names_match(station.city.name, city):
                    stations[station.id] = station
        for name in self.city_stations.get(city, ()):
            stations.setdefault(f"{city}:{self._normalize(name)}", Station(f"{city}:{self._normalize(name)}", name, next(iter(stations.values())).city if stations else segment_city(city)))
        return tuple(stations.values())

    def _normalize(self, value: str) -> str:
        # Yandex and our location catalogue do not consistently spell compound
        # city names with the same kind of dash (or with a dash at all).
        return normalize_location_name(value)


def segment_city(name: str):
    from app.domain import City

    return City(name)
