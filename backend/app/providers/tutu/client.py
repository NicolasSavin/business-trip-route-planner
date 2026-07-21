from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol

from app.providers.tutu.models import TutuCarriageDTO, TutuPlaceDTO, TutuTrainDTO


class TutuClient(Protocol):
    def search_trains(self, *, origin: str, destination: str, departure_date: date) -> list[TutuTrainDTO]: ...

    def get_train_carriages(self, *, train_reference: str) -> list[TutuCarriageDTO]: ...

    def get_carriage_places(self, *, train_reference: str, carriage_number: str) -> list[TutuPlaceDTO] | None: ...

    def healthcheck(self) -> bool: ...


class MockTutuClient:
    """Детерминированный клиент: не делает HTTP-запросы и не моделирует endpoints Туту."""

    def search_trains(self, *, origin: str, destination: str, departure_date: date) -> list[TutuTrainDTO]:
        return [
            TutuTrainDTO("tutu-full-coupe", "001Т", datetime.combine(departure_date, time(9)), datetime.combine(departure_date, time(17)), origin, destination),
            TutuTrainDTO("tutu-no-seats", "002Т", datetime.combine(departure_date, time(11)), datetime.combine(departure_date, time(19)), origin, destination),
            TutuTrainDTO("tutu-no-map", "003Т", datetime.combine(departure_date, time(13)), datetime.combine(departure_date, time(21)), origin, destination),
        ]

    def get_train_carriages(self, *, train_reference: str) -> list[TutuCarriageDTO]:
        if train_reference == "tutu-no-seats":
            return [TutuCarriageDTO("01", "coupe", "2К", None, 0)]
        if train_reference == "tutu-no-map":
            return [TutuCarriageDTO("01", "coupe", "2К", None, 4)]
        return [
            TutuCarriageDTO("01", "coupe", "2К", None, 8),
            TutuCarriageDTO("02", "coupe", "2К", "female", 4),
            TutuCarriageDTO("03", "coupe", "2К", "male", 4),
            TutuCarriageDTO("04", "platzkart", "3Э", None, 6),
        ]

    def get_carriage_places(self, *, train_reference: str, carriage_number: str) -> list[TutuPlaceDTO] | None:
        if train_reference == "tutu-no-map":
            return None
        if train_reference == "tutu-no-seats":
            return [self._place(str(n), carriage_number, (n + 3) // 4, available=False) for n in range(1, 5)]
        if carriage_number == "01":
            return [
                self._place("1", "01", 1, "lower"), self._place("2", "01", 1, "upper"), self._place("3", "01", 1, "lower"), self._place("4", "01", 1, "upper"),
                self._place("5", "01", 2, "lower"), self._place("6", "01", 2, "upper", available=False), self._place("7", "01", 2, "lower"), self._place("8", "01", 2, "upper"),
            ]
        if carriage_number == "02":
            return [self._place(str(n), "02", 1, "lower" if n % 2 else "upper", gender="female") for n in range(1, 5)]
        if carriage_number == "03":
            return [self._place(str(n), "03", 1, "lower" if n % 2 else "upper", gender="male") for n in range(1, 5)]
        if carriage_number == "04":
            return [
                self._place("1", "04", None, "lower", place_type="platzkart"), self._place("2", "04", None, "upper", place_type="platzkart"),
                self._place("37", "04", None, "lower", side=True, place_type="platzkart"), self._place("38", "04", None, "upper", side=True, place_type="platzkart"),
                self._place("39", "04", None, "lower", side=True, place_type="platzkart"), self._place("40", "04", None, "upper", side=True, place_type="platzkart"),
            ]
        return []

    def healthcheck(self) -> bool:
        return False

    def _place(self, number: str, carriage: str, compartment: int | None, berth: str = "lower", *, side: bool = False, gender: str | None = None, available: bool = True, place_type: str = "coupe") -> TutuPlaceDTO:
        return TutuPlaceDTO(number, place_type, berth, str(compartment) if compartment is not None else None, carriage, side, gender, available)
