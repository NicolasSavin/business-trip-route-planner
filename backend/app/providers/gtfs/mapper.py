from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType
from app.providers.gtfs.models import GTFSRoute, GTFSStop, GTFSStopTime, GTFSTrip


class GTFSTransportSegmentMapper:
    provider_name = "gtfs"

    def to_segment(self, service_date: date, route: GTFSRoute, trip: GTFSTrip, origin: GTFSStop, destination: GTFSStop, origin_time: GTFSStopTime, destination_time: GTFSStopTime) -> TransportSegment:
        departure = self._datetime(service_date, origin_time.departure_seconds)
        arrival = self._datetime(service_date, destination_time.arrival_seconds)
        origin_city = City(origin.city_name)
        destination_city = City(destination.city_name)
        transport_type = self._transport_type(route.route_type)
        route_name = route.route_short_name or route.route_long_name or route.route_id
        return TransportSegment(
            id=f"gtfs:{trip.trip_id}:{origin_time.stop_sequence}:{destination_time.stop_sequence}",
            provider=self.provider_name,
            carrier=Carrier(route.agency_id or "gtfs", route.agency_id or "GTFS"),
            transport_type=transport_type,
            transport_class=TransportClass.SEATED,
            vehicle_number=route_name,
            origin_city=origin_city,
            origin_station=Station(origin.stop_id, origin.stop_name, origin_city),
            destination_city=destination_city,
            destination_station=Station(destination.stop_id, destination.stop_name, destination_city),
            departure_datetime=departure,
            arrival_datetime=arrival,
            duration_minutes=int((arrival - departure).total_seconds() // 60),
            available_seats=999,
            price=None,
            metadata={"gtfs_route_id": route.route_id, "gtfs_trip_id": trip.trip_id, "gtfs_service_id": trip.service_id},
        )

    def _datetime(self, service_date: date, seconds: int) -> datetime:
        return datetime.combine(service_date, time.min) + timedelta(seconds=seconds)

    def _transport_type(self, route_type: int) -> TransportType:
        return TransportType.TRAIN if route_type in {2, 100, 101, 102, 103, 106, 109} else TransportType.BUS
