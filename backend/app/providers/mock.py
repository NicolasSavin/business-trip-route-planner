from datetime import date, datetime, time
from app.models.routes import RouteSegment, TransportType
from app.providers.base import TransportProvider


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour=hour, minute=minute))


class MockTransportProvider(TransportProvider):
    def get_segments(
        self,
        departure_date: date,
        allowed_transport: list[TransportType],
    ) -> list[RouteSegment]:
        segments = [
            RouteSegment(id="tr-msk-ekb-001", origin="Москва", destination="Екатеринбург", transport_type=TransportType.TRAIN, number="Поезд 016М", departure_time=at(departure_date, 9), arrival_time=at(departure_date, 23), available_seats=8),
            RouteSegment(id="tr-msk-kzn-001", origin="Москва", destination="Казань", transport_type=TransportType.TRAIN, number="Поезд 024М", departure_time=at(departure_date, 8), arrival_time=at(departure_date, 15), available_seats=12),
            RouteSegment(id="bus-kzn-ekb-001", origin="Казань", destination="Екатеринбург", transport_type=TransportType.BUS, number="Автобус К-204", departure_time=at(departure_date, 17), arrival_time=at(departure_date, 23, 30), available_seats=10),
            RouteSegment(id="bus-msk-smr-001", origin="Москва", destination="Самара", transport_type=TransportType.BUS, number="Автобус МС-77", departure_time=at(departure_date, 7), arrival_time=at(departure_date, 16), available_seats=20),
            RouteSegment(id="tr-smr-ekb-001", origin="Самара", destination="Екатеринбург", transport_type=TransportType.TRAIN, number="Поезд 102Й", departure_time=at(departure_date, 18), arrival_time=at(departure_date, 23, 45), available_seats=18),
            RouteSegment(id="tr-msk-nnov-001", origin="Москва", destination="Нижний Новгород", transport_type=TransportType.TRAIN, number="Поезд 732Г", departure_time=at(departure_date, 10), arrival_time=at(departure_date, 14), available_seats=6),
            RouteSegment(id="bus-nnov-ekb-001", origin="Нижний Новгород", destination="Екатеринбург", transport_type=TransportType.BUS, number="Автобус НН-Е96", departure_time=at(departure_date, 15), arrival_time=at(departure_date, 22), available_seats=1),
            RouteSegment(id="bus-msk-kzn-002", origin="Москва", destination="Казань", transport_type=TransportType.BUS, number="Автобус МК-12", departure_time=at(departure_date, 6), arrival_time=at(departure_date, 14), available_seats=4),
        ]
        allowed = set(allowed_transport)
        return [segment for segment in segments if segment.transport_type in allowed]
