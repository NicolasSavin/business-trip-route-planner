from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from app.providers.yandex.exceptions import YandexRaspUnknownCityError


POPULAR_CITY_NAMES = {
    "Москва", "Санкт-Петербург", "Казань", "Нижний Новгород", "Екатеринбург", "Самара",
    "Ростов-на-Дону", "Краснодар", "Сочи", "Новосибирск", "Омск", "Тюмень", "Челябинск",
    "Уфа", "Пермь", "Красноярск", "Иркутск", "Воронеж", "Волгоград", "Анапа", "Новороссийск",
}

# Official Yandex settlement codes are loaded from /v3.0/stations_list/ when an API key is available.
# The checked-in subset keeps startup deterministic in tests and is refreshed/validated by the official directory.
OFFICIAL_POPULAR_CITY_CODES = {
    "москва": "c213",
    "санкт-петербург": "c2",
}


@dataclass(frozen=True)
class YandexSettlement:
    code: str
    title: str


class YandexLocationResolver:
    def __init__(self, directory_loader=None):
        self._directory_loader = directory_loader
        self._settlements: dict[str, YandexSettlement] = {
            key: YandexSettlement(code=value, title=title)
            for key, value in OFFICIAL_POPULAR_CITY_CODES.items()
            for title in ["Москва" if key == "москва" else "Санкт-Петербург"]
        }
        self._loaded = False

    def resolve(self, city: str) -> YandexSettlement:
        self._ensure_loaded()
        key = self._normalize(city)
        settlement = self._settlements.get(key)
        if not settlement:
            raise YandexRaspUnknownCityError(f"Неизвестный город для Яндекс Расписаний: {city}")
        return settlement

    def _ensure_loaded(self) -> None:
        if self._loaded or not self._directory_loader:
            self._loaded = True
            return
        directory = self._directory_loader()
        self._load_directory(directory)
        self._loaded = True

    def _load_directory(self, directory: dict) -> None:
        for country in directory.get("countries", []):
            for region in country.get("regions", []):
                for settlement in region.get("settlements", []):
                    title = settlement.get("title")
                    code = settlement.get("codes", {}).get("yandex_code")
                    if title and code and title in POPULAR_CITY_NAMES:
                        self._settlements[self._normalize(title)] = YandexSettlement(code=code, title=title)

    def _normalize(self, value: str) -> str:
        return unicodedata.normalize("NFKC", value).strip().replace("ё", "е").lower()
