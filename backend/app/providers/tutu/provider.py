from __future__ import annotations

from datetime import date

from app.availability.seats import RailwayCarriageAvailability, SeatAllocationService, SeatPreferences
from app.providers.tutu.client import MockTutuClient, TutuClient
from app.providers.tutu.config import TutuConfiguration
from app.providers.tutu.exceptions import TutuConfigurationError
from app.providers.tutu.mapper import TutuMapper


class TutuAvailabilityProvider:
    provider_name = "tutu"

    def __init__(self, client: TutuClient | None = None, mapper: TutuMapper | None = None, configuration: TutuConfiguration | None = None, seat_allocation_service: SeatAllocationService | None = None) -> None:
        self.client = client or MockTutuClient()
        self.mapper = mapper or TutuMapper()
        self.configuration = configuration or TutuConfiguration()
        self.seat_allocation_service = seat_allocation_service or SeatAllocationService()

    def check_availability(self, *, origin: str, destination: str, departure_date: date, preferences: SeatPreferences) -> list[RailwayCarriageAvailability]:
        trains = self.client.search_trains(origin=origin, destination=destination, departure_date=departure_date)
        result: list[RailwayCarriageAvailability] = []
        for train in trains:
            for carriage in self.client.get_train_carriages(train_reference=train.train_reference):
                place_dtos = self.client.get_carriage_places(train_reference=train.train_reference, carriage_number=carriage.carriage_number)
                availability = self.mapper.to_carriage(carriage, place_dtos)
                if availability.places:
                    allocation = self.seat_allocation_service.match(availability.places, preferences)
                    availability = availability.__class__(**{**availability.__dict__, "seat_allocation": allocation, "metadata": {**availability.metadata, "train_reference": train.train_reference, "train_number": train.train_number}})
                result.append(availability)
        return result

    def healthcheck(self) -> bool:
        return False

    def ensure_can_enable(self) -> None:
        if not self.configuration.configured:
            raise TutuConfigurationError("Требуется официальный партнёрский доступ Туту")
        raise TutuConfigurationError("Официальный клиент Туту ещё не подключён; реальные запросы не выполняются")
