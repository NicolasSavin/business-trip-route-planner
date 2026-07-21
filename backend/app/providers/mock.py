from datetime import date, datetime, time, timedelta
from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.providers.base import TransportProvider


def at(day: date, hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    return datetime.combine(day + timedelta(days=day_offset), time(hour=hour % 24, minute=minute))


CITIES = [
    "Москва", "Санкт-Петербург", "Нижний Новгород", "Казань", "Самара", "Уфа", "Екатеринбург", "Челябинск", "Пермь", "Тюмень",
    "Омск", "Новосибирск", "Красноярск", "Иркутск", "Ростов-на-Дону", "Воронеж", "Волгоград", "Краснодар", "Сочи", "Ярославль",
    "Саратов", "Тула", "Рязань", "Киров", "Ижевск",
]


class MockTransportProvider(TransportProvider):
    provider_name = "mock"

    def get_segments(self, departure_date: date, allowed_transport: list[TransportType]) -> list[TransportSegment]:
        segments: list[TransportSegment] = []
        for index, origin in enumerate(CITIES):
            destination = CITIES[(index + 1) % len(CITIES)]
            segments.append(self._segment(departure_date, index, origin, destination, TransportType.TRAIN, 7 + index % 12, 5 + index % 6, 20 + index % 30))
            segments.append(self._segment(departure_date, index + 100, origin, destination, TransportType.BUS, 9 + index % 10, 7 + index % 7, 8 + index % 18))
            express_destination = CITIES[(index + 2) % len(CITIES)]
            segments.append(self._segment(departure_date, index + 200, origin, express_destination, TransportType.TRAIN, 13 + index % 8, 8 + index % 5, 4 + index % 14))
            reverse_origin = CITIES[(index + 3) % len(CITIES)]
            segments.append(self._segment(departure_date, index + 300, reverse_origin, origin, TransportType.BUS, 16 + index % 6, 6 + index % 5, 6 + index % 20))

        # Stable fixtures for tests and demo routes from Moscow to Ekaterinburg.
        segments.extend([
            self._segment(departure_date, 900, "Москва", "Екатеринбург", TransportType.TRAIN, 9, 14, 8, "016М"),
            self._segment(departure_date, 901, "Москва", "Казань", TransportType.TRAIN, 8, 7, 12, "024М"),
            self._segment(departure_date, 902, "Казань", "Екатеринбург", TransportType.BUS, 17, 6, 10, "К-204"),
            self._segment(departure_date, 903, "Москва", "Самара", TransportType.BUS, 7, 9, 20, "МС-77"),
            self._segment(departure_date, 904, "Самара", "Екатеринбург", TransportType.TRAIN, 18, 5, 18, "102Й"),
            self._segment(departure_date, 905, "Москва", "Нижний Новгород", TransportType.TRAIN, 10, 4, 6, "732Г"),
            self._segment(departure_date, 906, "Нижний Новгород", "Екатеринбург", TransportType.BUS, 15, 7, 1, "НН-Е96"),
            self._segment(departure_date, 907, "Москва", "Казань", TransportType.BUS, 6, 8, 4, "МК-12"),
            self._segment(departure_date, 908, "Москва", "Воронеж", TransportType.TRAIN, 6, 5, 9, "020М"),
            self._segment(departure_date, 909, "Воронеж", "Самара", TransportType.BUS, 13, 6, 9, "ВС-63"),
            self._segment(departure_date, 910, "Самара", "Екатеринбург", TransportType.TRAIN, 21, 6, 9, "104Й"),
        ])
        allowed = set(allowed_transport)
        return [segment for segment in segments if segment.transport_type in allowed]

    def _segment(self, day: date, idx: int, origin: str, destination: str, ttype: TransportType, hour: int, duration_hours: int, seats: int, number: str | None = None) -> TransportSegment:
        dep = at(day, hour)
        arr = dep + timedelta(hours=duration_hours, minutes=(idx % 4) * 15)
        origin_city, destination_city = City(origin), City(destination)
        carrier = Carrier(f"carrier-{ttype.value}", "РЖД" if ttype == TransportType.TRAIN else "РегионАвто")
        station_suffix = "rail" if ttype == TransportType.TRAIN else "bus"
        transport_class = TransportClass.COUPE if ttype == TransportType.TRAIN and idx % 2 else TransportClass.SEATED
        return TransportSegment(
            id=f"{ttype.value}-{idx:03d}-{origin[:3]}-{destination[:3]}",
            provider=self.provider_name,
            carrier=carrier,
            transport_type=ttype,
            transport_class=transport_class,
            vehicle_number=("Поезд " if ttype == TransportType.TRAIN else "Автобус ") + (number or f"{idx:03d}"),
            origin_city=origin_city,
            origin_station=Station(f"{origin}-{station_suffix}", f"{origin} {'вокзал' if ttype == TransportType.TRAIN else 'автовокзал'}", origin_city),
            destination_city=destination_city,
            destination_station=Station(f"{destination}-{station_suffix}", f"{destination} {'вокзал' if ttype == TransportType.TRAIN else 'автовокзал'}", destination_city),
            departure_datetime=dep,
            arrival_datetime=arr,
            duration_minutes=int((arr - dep).total_seconds() // 60),
            available_seats=seats,
            price=1200 + idx * 17,
            metadata={"mock": True},
        )
