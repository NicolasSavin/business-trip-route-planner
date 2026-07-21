from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain import Transfer, TransportSegment, TransportType
from app.scoring.service import is_night_transfer_start


class TransferType(StrEnum):
    WALK = "walk"
    METRO = "metro"
    BUS = "bus"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TransferAssessment:
    transfer_type: TransferType
    estimated_duration_minutes: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TransferEngine:
    minimum_transfer_minutes: int = 35
    maximum_transfer_minutes: int = 360

    def build_transfer(self, first: TransportSegment, second: TransportSegment) -> Transfer:
        minutes = int((second.departure_datetime - first.arrival_datetime).total_seconds() // 60)
        assessment = self.assess(first, second, minutes)
        return Transfer(
            from_segment=first,
            to_segment=second,
            duration_minutes=minutes,
            city=first.destination_city,
            is_night=is_night_transfer_start(first.arrival_datetime.hour),
            transfer_type=assessment.transfer_type.value,
            estimated_transfer_minutes=assessment.estimated_duration_minutes,
            warnings=assessment.warnings,
            station_change=first.destination_station.id != second.origin_station.id,
            city_change=first.destination_city.name != second.origin_city.name,
        )

    def assess(self, first: TransportSegment, second: TransportSegment, wait_minutes: int | None = None) -> TransferAssessment:
        wait = wait_minutes if wait_minutes is not None else int((second.departure_datetime - first.arrival_datetime).total_seconds() // 60)
        same_station = first.destination_station.id == second.origin_station.id
        same_city = first.destination_city.name == second.origin_city.name
        transfer_type = self._type(first, second, same_station, same_city)
        estimated = self._estimated_minutes(transfer_type)
        warnings: list[str] = []
        if wait < self.minimum_transfer_minutes:
            warnings.append(f"Пересадка менее {self.minimum_transfer_minutes} минут")
        if wait > self.maximum_transfer_minutes:
            warnings.append("Долгая пересадка")
        if is_night_transfer_start(first.arrival_datetime.hour):
            warnings.append("Ночная пересадка")
        if not same_station:
            warnings.append("Смена станции")
        if not same_city:
            warnings.append("Смена города")
        if wait < estimated:
            warnings.append("Нет доступного транспорта после прибытия")
        return TransferAssessment(transfer_type, estimated, tuple(warnings))

    def _type(self, first: TransportSegment, second: TransportSegment, same_station: bool, same_city: bool) -> TransferType:
        if same_station:
            return TransferType.WALK
        if not same_city:
            return TransferType.BUS
        if TransportType.TRAIN in {first.transport_type, second.transport_type}:
            return TransferType.METRO
        return TransferType.UNKNOWN

    def _estimated_minutes(self, transfer_type: TransferType) -> int:
        return {TransferType.WALK: 10, TransferType.METRO: 45, TransferType.BUS: 90, TransferType.UNKNOWN: 60}[transfer_type]
