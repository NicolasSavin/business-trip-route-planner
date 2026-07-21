from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class StationResolver:
    city_stations: dict[str, tuple[str, ...]] = field(default_factory=lambda: DEFAULT_CITY_STATIONS.copy())

    def resolve_city_names(self, query: str, segments: list[TransportSegment]) -> tuple[str, ...]:
        normalized = self._normalize(query)
        known_cities = {segment.origin_city.name for segment in segments} | {segment.destination_city.name for segment in segments} | set(self.city_stations)
        for city in known_cities:
            if self._normalize(city) == normalized:
                return (city,)
        for city, stations in self.city_stations.items():
            if any(self._normalize(station) == normalized for station in stations):
                return (city,)
        return (query,)

    def stations_for_city(self, city: str, segments: list[TransportSegment]) -> tuple[Station, ...]:
        stations: dict[str, Station] = {}
        for segment in segments:
            for station in (segment.origin_station, segment.destination_station):
                if station.city.name == city:
                    stations[station.id] = station
        for name in self.city_stations.get(city, ()):
            stations.setdefault(f"{city}:{self._normalize(name)}", Station(f"{city}:{self._normalize(name)}", name, next(iter(stations.values())).city if stations else segment_city(city)))
        return tuple(stations.values())

    def _normalize(self, value: str) -> str:
        return " ".join(value.lower().replace("ё", "е").split())


def segment_city(name: str):
    from app.domain import City

    return City(name)
