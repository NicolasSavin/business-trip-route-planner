from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain import TransportSegment


@dataclass(frozen=True)
class SegmentMatch:
    schedule_segment_id: str
    availability_segment_id: str
    confidence: float
    reasons: tuple[str, ...]


class SegmentEnrichmentService:
    """Matches schedule segments to provider-specific availability/enrichment rows."""

    def match(self, schedule: TransportSegment, candidates: list[TransportSegment]) -> SegmentMatch | None:
        best: SegmentMatch | None = None
        for candidate in candidates:
            confidence, reasons = self._score(schedule, candidate)
            if confidence < 0.72:
                continue
            match = SegmentMatch(schedule.id, candidate.id, round(confidence, 3), tuple(reasons))
            if best is None or match.confidence > best.confidence:
                best = match
        return best

    def _score(self, left: TransportSegment, right: TransportSegment) -> tuple[float, list[str]]:
        score = 0.0; reasons: list[str] = []
        if left.transport_type == right.transport_type:
            score += 0.2; reasons.append("тип транспорта совпал")
        if left.vehicle_number and left.vehicle_number.lower() == right.vehicle_number.lower():
            score += 0.25; reasons.append("номер рейса совпал")
        if left.carrier.name.lower() == right.carrier.name.lower() or left.carrier.id.lower() == right.carrier.id.lower():
            score += 0.15; reasons.append("перевозчик совпал")
        if left.origin_station.id.lower() == right.origin_station.id.lower() or left.origin_city.name == right.origin_city.name:
            score += 0.1; reasons.append("отправление совпало")
        if left.destination_station.id.lower() == right.destination_station.id.lower() or left.destination_city.name == right.destination_city.name:
            score += 0.1; reasons.append("прибытие совпало")
        dep_delta = abs(left.departure_datetime - right.departure_datetime)
        arr_delta = abs(left.arrival_datetime - right.arrival_datetime)
        if dep_delta <= timedelta(minutes=15):
            score += 0.1; reasons.append("время отправления совпало")
        if arr_delta <= timedelta(minutes=15):
            score += 0.1; reasons.append("время прибытия совпало")
        return score, reasons
