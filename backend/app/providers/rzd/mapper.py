from __future__ import annotations

from app.domain import Carrier, City, Station, TransportSegment, TransportType
from app.providers.rzd.models import RzdTrainOption


class RzdMapper:
    provider_name = "rzd"

    def to_segments(self, trains: list[RzdTrainOption]) -> list[TransportSegment]:
        segments: list[TransportSegment] = []
        for train in trains:
            best_car = max(train.cars, key=lambda car: car.seats)
            origin_city = City(train.origin.city)
            destination_city = City(train.destination.city)
            segments.append(TransportSegment(
                id=f"rzd:{train.train_number}:{train.origin.code}:{train.destination.code}:{train.departure_datetime.date().isoformat()}",
                provider=self.provider_name,
                carrier=Carrier("rzd", train.carrier),
                transport_type=TransportType.TRAIN,
                transport_class=best_car.car_type,
                vehicle_number=f"Поезд {train.train_number}" + (f" {train.train_name}" if train.train_name else ""),
                origin_city=origin_city,
                origin_station=Station(train.origin.code, train.origin.name, origin_city),
                destination_city=destination_city,
                destination_station=Station(train.destination.code, train.destination.name, destination_city),
                departure_datetime=train.departure_datetime,
                arrival_datetime=train.arrival_datetime,
                duration_minutes=int((train.arrival_datetime - train.departure_datetime).total_seconds() // 60),
                available_seats=sum(car.seats for car in train.cars),
                price=min((car.min_price for car in train.cars if car.min_price is not None), default=None),
                metadata={"source": "rzd_mock", "train_name": train.train_name, "car_types": [car.car_type.value for car in train.cars]},
            ))
        return segments
