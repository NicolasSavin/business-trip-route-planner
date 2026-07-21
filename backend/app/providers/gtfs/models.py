from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class GTFSStop:
    stop_id: str
    stop_name: str
    city_name: str
    stop_lat: float | None = None
    stop_lon: float | None = None


@dataclass(frozen=True)
class GTFSRoute:
    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int
    agency_id: str | None = None


@dataclass(frozen=True)
class GTFSTrip:
    route_id: str
    service_id: str
    trip_id: str
    trip_headsign: str = ""


@dataclass(frozen=True)
class GTFSStopTime:
    trip_id: str
    arrival_seconds: int
    departure_seconds: int
    stop_id: str
    stop_sequence: int


@dataclass(frozen=True)
class GTFSCalendar:
    service_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: date
    end_date: date


@dataclass(frozen=True)
class GTFSFeed:
    stops: dict[str, GTFSStop]
    routes: dict[str, GTFSRoute]
    trips: dict[str, GTFSTrip]
    stop_times_by_trip: dict[str, tuple[GTFSStopTime, ...]]
    calendars: dict[str, GTFSCalendar]
    calendar_dates: dict[str, dict[date, int]]
