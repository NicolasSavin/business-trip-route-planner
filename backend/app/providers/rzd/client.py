from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol

from app.domain import TransportClass
from app.providers.rzd.models import RzdCarAvailability, RzdStation, RzdTrainOption


class RzdClient(Protocol):
    def search_trains(self, departure_date: date) -> list[RzdTrainOption]: ...

    def healthcheck(self) -> bool: ...


class MockRzdClient:
    """Deterministic mock client; does not call RZD sites or external APIs."""

    stations = {
        "moscow": RzdStation("2000000", "Москва Казанская", "Москва"),
        "spb": RzdStation("2004000", "Санкт-Петербург-Главн.", "Санкт-Петербург"),
        "nn": RzdStation("2060001", "Нижний Новгород Московский", "Нижний Новгород"),
        "kazan": RzdStation("2060615", "Казань-Пасс.", "Казань"),
        "ekb": RzdStation("2030000", "Екатеринбург-Пасс.", "Екатеринбург"),
        "samara": RzdStation("2024000", "Самара", "Самара"),
    }

    def search_trains(self, departure_date: date) -> list[RzdTrainOption]:
        return [
            self._train(departure_date, "016М", "Урал", "moscow", "ekb", 9, 14, ((TransportClass.COUPE, 12, 5400), (TransportClass.PLATZKART, 28, 3100))),
            self._train(departure_date, "024М", None, "moscow", "kazan", 8, 7, ((TransportClass.SEATED, 18, 1800), (TransportClass.COUPE, 6, 3600))),
            self._train(departure_date, "102Й", "Премиум", "samara", "ekb", 18, 5, ((TransportClass.COUPE, 10, 4200), (TransportClass.SLEEPER, 4, 7200))),
            self._train(departure_date, "732Г", "Ласточка", "moscow", "nn", 10, 4, ((TransportClass.SEATED, 42, 1500),)),
            self._train(departure_date, "059А", "Волга", "spb", "nn", 16, 12, ((TransportClass.PLATZKART, 21, 2800), (TransportClass.COUPE, 9, 4700))),
        ]

    def healthcheck(self) -> bool:
        return True

    def _train(self, day: date, number: str, name: str | None, origin: str, destination: str, hour: int, duration_hours: int, cars: tuple[tuple[TransportClass, int, float], ...]) -> RzdTrainOption:
        dep = datetime.combine(day, time(hour=hour))
        arr = dep + timedelta(hours=duration_hours)
        return RzdTrainOption(number, name, self.stations[origin], self.stations[destination], dep, arr, tuple(RzdCarAvailability(*car) for car in cars))
