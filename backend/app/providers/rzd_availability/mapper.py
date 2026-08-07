from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.availability.journey import AvailabilityStatus, SegmentAvailabilityResult
from app.domain import TransportSegment
from app.providers.rzd_availability.models import RZDSeat, RZDTrainAvailability

_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "У": "Y",
        "Х": "X",
    }
)


def normalize_train_number(value: str) -> str:
    compact = (
        re.sub(r"[^0-9A-Za-zА-Яа-я]", "", unicodedata.normalize("NFC", value).strip())
        .upper()
        .translate(_CYRILLIC_TO_LATIN)
    )
    match = re.fullmatch(r"0*(\d+)(.*)", compact)
    return f"{int(match.group(1))}{match.group(2)}" if match else compact


def _items(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def map_train(raw: dict[str, Any]) -> RZDTrainAvailability:
    number = str(
        raw.get("train_number")
        or raw.get("trainNumber")
        or raw.get("number")
        or raw.get("num")
        or ""
    )
    carriages = _items(raw, "cars", "carriages", "lst")
    seats: list[RZDSeat] = []
    total = 0
    for carriage in carriages:
        car_number = str(
            carriage.get("number")
            or carriage.get("carNumber")
            or carriage.get("carriage_number")
            or ""
        )
        car_type = str(
            carriage.get("type")
            or carriage.get("carType")
            or carriage.get("class")
            or "unknown"
        )
        raw_seats = _items(carriage, "seats", "places", "freePlaces")
        for seat in raw_seats:
            available = bool(seat.get("available", seat.get("isAvailable", True)))
            if available:
                seats.append(
                    RZDSeat(
                        str(seat.get("number") or seat.get("place") or ""),
                        car_number,
                        car_type,
                        str(seat.get("compartment") or "") or None,
                    )
                )
        count = (
            carriage.get("freeSeats")
            or carriage.get("availableSeats")
            or carriage.get("available_places")
            or carriage.get("availablePlaces")
            or carriage.get("placeQuantity")
            or carriage.get("place_quantity")
        )
        total += int(
            count
            or len(
                [
                    seat
                    for seat in raw_seats
                    if seat.get("available", seat.get("isAvailable", True))
                ]
            )
        )
    total = int(
        raw.get("available_seats")
        or raw.get("availableSeats")
        or raw.get("freeSeats")
        or total
    )
    price = raw.get("min_price") or raw.get("minPrice") or raw.get("minimum_price")
    return RZDTrainAvailability(
        number,
        total,
        tuple(seats),
        tuple(carriages),
        float(price) if price is not None else None,
        raw,
    )


def train_number_match_type(expected: str, actual: str) -> str:
    """Return a conservative diagnostic match classification."""
    if unicodedata.normalize("NFC", expected).strip().upper() == unicodedata.normalize("NFC", actual).strip().upper():
        return "exact"
    expected_compact = re.sub(r"[^0-9A-Za-zА-Яа-я]", "", unicodedata.normalize("NFC", expected).upper()).translate(_CYRILLIC_TO_LATIN)
    actual_compact = re.sub(r"[^0-9A-Za-zА-Яа-я]", "", unicodedata.normalize("NFC", actual).upper()).translate(_CYRILLIC_TO_LATIN)
    if expected_compact == actual_compact:
        return "normalized_exact"
    expected_match = re.fullmatch(r"0*(\d+)([A-ZА-Я]*)", expected_compact)
    actual_match = re.fullmatch(r"0*(\d+)([A-ZА-Я]*)", actual_compact)
    if expected_match and actual_match and expected_match.groups() == actual_match.groups():
        return "numeric_plus_suffix"
    return "no_match"


def to_segment_result(
    segment: TransportSegment,
    train: RZDTrainAvailability,
    passengers: int,
    preferences_requested: bool = False,
) -> SegmentAvailabilityResult:
    confirmed = train.available_seats >= passengers
    status = AvailabilityStatus.CONFIRMED if confirmed else AvailabilityStatus.UNAVAILABLE
    warnings: tuple[str, ...] = ()
    preference_status = status
    if confirmed and preferences_requested and not train.seats:
        status = AvailabilityStatus.PARTIALLY_CONFIRMED
        preference_status = AvailabilityStatus.UNKNOWN
        warnings = ("Места есть, но требования к расположению мест РЖД не подтвердил",)
    return SegmentAvailabilityResult(
        segment_id=segment.id,
        provider="rzd",
        status=status,
        schedule_confirmed=True,
        seats_confirmed=confirmed,
        passengers_supported=confirmed,
        available_places_count=train.available_seats,
        seat_preferences_status=preference_status,
        warnings=warnings,
        metadata={
            "matched_train": train.train_number,
            "availability_match": "exact_train_and_query",
            "requested_passengers": passengers,
            "travel_date": segment.departure_datetime.date().isoformat(),
            "origin_station_id": segment.origin_station.id,
            "destination_station_id": segment.destination_station.id,
            "places": [seat.__dict__ for seat in train.seats],
            "carriages": list(train.carriages),
            "min_price": train.min_price,
            "price_per_passenger": train.min_price,
            "price_semantics": "per_passenger",
        },
    )
