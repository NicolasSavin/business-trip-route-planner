from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_NEARBY_CITIES: dict[str, tuple[str, ...]] = {
    "Геленджик": ("Новороссийск", "Краснодар", "Анапа"),
    "Новороссийск": ("Краснодар", "Анапа", "Геленджик"),
    "Анапа": ("Новороссийск", "Краснодар", "Геленджик"),
    "Краснодар": ("Новороссийск", "Анапа", "Геленджик"),
    "Москва": ("Тула", "Рязань", "Ярославль"),
}


@dataclass(frozen=True)
class NearbyCityResolver:
    nearby_cities: dict[str, tuple[str, ...]] = field(default_factory=lambda: DEFAULT_NEARBY_CITIES.copy())

    def alternatives_for(self, city: str) -> tuple[str, ...]:
        return self.nearby_cities.get(city, ())
