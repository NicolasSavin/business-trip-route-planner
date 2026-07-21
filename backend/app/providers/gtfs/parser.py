from __future__ import annotations

import csv
from datetime import date
from io import StringIO

from app.domain import TransportSegment, TransportType
from app.providers.gtfs.mapper import GTFSTransportSegmentMapper
from app.providers.gtfs.models import GTFSCalendar, GTFSFeed, GTFSRoute, GTFSStop, GTFSStopTime, GTFSTrip


class GTFSParser:
    def __init__(self, mapper: GTFSTransportSegmentMapper | None = None):
        self.mapper = mapper or GTFSTransportSegmentMapper()

    def parse_feed(self, files: dict[str, str]) -> GTFSFeed:
        stops = {row["stop_id"]: GTFSStop(row["stop_id"], row["stop_name"], row.get("city_name") or row.get("stop_city") or row["stop_name"], self._float(row.get("stop_lat")), self._float(row.get("stop_lon"))) for row in self._rows(files["stops.txt"])}
        routes = {row["route_id"]: GTFSRoute(row["route_id"], row.get("route_short_name", ""), row.get("route_long_name", ""), int(row["route_type"]), row.get("agency_id") or None) for row in self._rows(files["routes.txt"])}
        trips = {row["trip_id"]: GTFSTrip(row["route_id"], row["service_id"], row["trip_id"], row.get("trip_headsign", "")) for row in self._rows(files["trips.txt"])}
        stop_times_by_trip: dict[str, list[GTFSStopTime]] = {}
        for row in self._rows(files["stop_times.txt"]):
            stop_times_by_trip.setdefault(row["trip_id"], []).append(GTFSStopTime(row["trip_id"], self._time(row["arrival_time"]), self._time(row["departure_time"]), row["stop_id"], int(row["stop_sequence"])))
        sorted_stop_times = {trip_id: tuple(sorted(times, key=lambda item: item.stop_sequence)) for trip_id, times in stop_times_by_trip.items()}
        calendars = {row["service_id"]: GTFSCalendar(row["service_id"], tuple(row[name] == "1" for name in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")), self._date(row["start_date"]), self._date(row["end_date"])) for row in self._rows(files["calendar.txt"])}
        calendar_dates: dict[str, dict[date, int]] = {}
        for row in self._rows(files.get("calendar_dates.txt", "")):
            calendar_dates.setdefault(row["service_id"], {})[self._date(row["date"])] = int(row["exception_type"])
        return GTFSFeed(stops, routes, trips, sorted_stop_times, calendars, calendar_dates)

    def create_segments(self, feed: GTFSFeed, service_date: date, allowed_transport: list[TransportType]) -> list[TransportSegment]:
        allowed = set(allowed_transport)
        segments: list[TransportSegment] = []
        for trip in feed.trips.values():
            if not self._service_active(feed, trip.service_id, service_date):
                continue
            route = feed.routes[trip.route_id]
            times = feed.stop_times_by_trip.get(trip.trip_id, ())
            for origin_time, destination_time in zip(times, times[1:]):
                segment = self.mapper.to_segment(service_date, route, trip, feed.stops[origin_time.stop_id], feed.stops[destination_time.stop_id], origin_time, destination_time)
                if segment.transport_type in allowed:
                    segments.append(segment)
        return segments

    def _service_active(self, feed: GTFSFeed, service_id: str, service_date: date) -> bool:
        exception = feed.calendar_dates.get(service_id, {}).get(service_date)
        if exception == 1:
            return True
        if exception == 2:
            return False
        calendar = feed.calendars.get(service_id)
        return bool(calendar and calendar.start_date <= service_date <= calendar.end_date and calendar.weekdays[service_date.weekday()])

    def _rows(self, text: str):
        if not text.strip():
            return []
        return list(csv.DictReader(StringIO(text)))

    def _time(self, value: str) -> int:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
        return hours * 3600 + minutes * 60 + seconds

    def _date(self, value: str) -> date:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))

    def _float(self, value: str | None) -> float | None:
        return float(value) if value else None
