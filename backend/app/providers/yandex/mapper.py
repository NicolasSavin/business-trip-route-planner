from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain import Carrier, City, Station, TransportClass, TransportSegment, TransportType


class YandexRaspMapper:
    def to_segments(self, payload: dict[str, Any]) -> list[TransportSegment]:
        segments: list[TransportSegment] = []
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list):
            return []
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            if item.get("has_transfers"):
                details = item.get("details") or []
                if not isinstance(details, list):
                    continue
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    segment = self._segment(detail, parent=item)
                    if segment:
                        segments.append(segment)
            else:
                segment = self._segment(item)
                if segment:
                    segments.append(segment)
        return segments

    def _segment(self, item: dict[str, Any], parent: dict[str, Any] | None = None) -> TransportSegment | None:
        thread = item.get("thread") or {}
        if not isinstance(thread, dict):
            thread = {}
        from_obj = item.get("from") or (parent and parent.get("from")) or {}
        to_obj = item.get("to") or (parent and parent.get("to")) or {}
        if not isinstance(from_obj, dict) or not isinstance(to_obj, dict):
            return None
        departure = item.get("departure")
        arrival = item.get("arrival")
        if not departure or not arrival or not from_obj or not to_obj:
            return None
        departure_dt = datetime.fromisoformat(departure)
        arrival_dt = datetime.fromisoformat(arrival)
        transport_type = self._transport_type(thread.get("transport_type"))
        carrier = thread.get("carrier") or item.get("carrier") or {}
        if not isinstance(carrier, dict):
            carrier = {}
        from_settlement = from_obj.get("settlement") or {}
        to_settlement = to_obj.get("settlement") or {}
        if not isinstance(from_settlement, dict):
            from_settlement = {}
        if not isinstance(to_settlement, dict):
            to_settlement = {}
        origin_city = City(from_settlement.get("title") or from_obj.get("title") or "")
        destination_city = City(to_settlement.get("title") or to_obj.get("title") or "")
        uid = thread.get("uid") or f"{from_obj.get('code')}-{to_obj.get('code')}-{departure}"
        return TransportSegment(
            id=f"yandex-{uid}-{departure}",
            provider="yandex_rasp",
            carrier=Carrier(str(carrier.get("code") or carrier.get("id") or "yandex"), carrier.get("title") or carrier.get("name") or "Яндекс Расписания"),
            transport_type=transport_type,
            transport_class=None,
            vehicle_number=thread.get("number") or thread.get("title") or item.get("number") or "рейс",
            origin_city=origin_city,
            origin_station=Station(str(from_obj.get("code") or from_obj.get("station_type") or from_obj.get("title")), from_obj.get("title") or origin_city.name, origin_city),
            destination_city=destination_city,
            destination_station=Station(str(to_obj.get("code") or to_obj.get("station_type") or to_obj.get("title")), to_obj.get("title") or destination_city.name, destination_city),
            departure_datetime=departure_dt,
            arrival_datetime=arrival_dt,
            duration_minutes=int((arrival_dt - departure_dt).total_seconds() // 60),
            available_seats=None,
            price=self._price(item),
            metadata={"source": "Яндекс Расписания", "availability_unknown": True, "raw_transport_type": thread.get("transport_type")},
        )

    def _transport_type(self, value: str | None) -> TransportType:
        if value == "bus":
            return TransportType.BUS
        return TransportType.TRAIN

    def _price(self, item: dict[str, Any]) -> float | None:
        tickets_info = item.get("tickets_info") or {}
        if not isinstance(tickets_info, dict):
            return None
        places = tickets_info.get("places") or []
        first_place = places[0] if isinstance(places, list) and places and isinstance(places[0], dict) else {}
        price = first_place.get("price")
        if isinstance(price, dict):
            return price.get("whole")
        return price
