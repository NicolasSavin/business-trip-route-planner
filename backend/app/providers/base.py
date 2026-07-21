from abc import ABC, abstractmethod
from datetime import date
from app.models.routes import RouteSegment, TransportType


class TransportProvider(ABC):
    """Абстракция источника транспортных сегментов.

    Mock-провайдер можно заменить провайдерами РЖД, автобусов или агрегаторов,
    не меняя маршрутный движок.
    """

    @abstractmethod
    def get_segments(
        self,
        departure_date: date,
        allowed_transport: list[TransportType],
    ) -> list[RouteSegment]:
        """Вернуть доступные сегменты на указанную дату."""
