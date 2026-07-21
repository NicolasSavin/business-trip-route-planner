from __future__ import annotations

from app.domain import Carrier, City, Route, RouteOption, Station, TransportClass, TransportSegment, TransportType
from app.providers.tutu.playwright.models import SeatAvailability, TutuPlaywrightResult


class TutuPlaywrightMapper:
    provider = "tutu_playwright"

    def to_segment(self, result: TutuPlaywrightResult, origin: str, destination: str) -> TransportSegment:
        seats = result.available_seats.total if isinstance(result.available_seats.total, int) else 0
        return TransportSegment(
            id=f"tutu-playwright:{result.train_number}:{result.departure.isoformat()}",
            provider=self.provider,
            carrier=Carrier(id="tutu", name="Туту"),
            transport_type=TransportType.TRAIN,
            transport_class=self._transport_class(result.carriage_type),
            vehicle_number=result.train_number,
            origin_city=City(origin),
            origin_station=Station(id=result.origin_station.lower(), name=result.origin_station, city=City(origin)),
            destination_city=City(destination),
            destination_station=Station(id=result.destination_station.lower(), name=result.destination_station, city=City(destination)),
            departure_datetime=result.departure,
            arrival_datetime=result.arrival,
            duration_minutes=result.duration_minutes,
            available_seats=seats,
            price=result.price,
            metadata={
                "source": self.provider,
                "transfers": result.transfers,
                "carriage_type": result.carriage_type,
                "seat_availability": result.available_seats.__dict__,
                "raw": result.raw,
            },
        )

    def to_route_option(self, result: TutuPlaywrightResult, origin: str, destination: str, rank: int = 0) -> RouteOption:
        segment = self.to_segment(result, origin, destination)
        return RouteOption(route=Route(segments=(segment,)), score=0.0, rank=rank, availability=result.available_seats)

    def to_segments(self, results: list[TutuPlaywrightResult], origin: str, destination: str) -> list[TransportSegment]:
        return [self.to_segment(result, origin, destination) for result in results]

    def _transport_class(self, carriage_type: str) -> TransportClass:
        value = carriage_type.lower()
        if "св" in value or "люкс" in value:
            return TransportClass.SLEEPER
        if "куп" in value:
            return TransportClass.COUPE
        if "плац" in value:
            return TransportClass.PLATZKART
        if "сид" in value:
            return TransportClass.SEATED
        return TransportClass.ECONOMY
