from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.availability.models import AvailabilityPolicy, SegmentAvailability
from app.domain import TransportClass, TransportSegment


class AvailabilityProvider(Protocol):
    def check_segment(self, segment: TransportSegment, policy: AvailabilityPolicy) -> SegmentAvailability: ...


class MockAvailabilityProvider:
    source = "mock"

    def __init__(
        self,
        overrides: dict[str, int | None] | None = None,
        class_overrides: dict[str, tuple[TransportClass, ...] | list[TransportClass] | set[TransportClass]] | None = None,
        checked_at_overrides: dict[str, datetime] | None = None,
        stale_after_seconds: int | None = None,
        split_only_segment_ids: set[str] | None = None,
    ):
        self.overrides = overrides or {}
        self.class_overrides = class_overrides or {}
        self.checked_at_overrides = checked_at_overrides or {}
        self.stale_after_seconds = stale_after_seconds
        self.split_only_segment_ids = split_only_segment_ids or set()

    def check_segment(self, segment: TransportSegment, policy: AvailabilityPolicy) -> SegmentAvailability:
        checked_at = self.checked_at_overrides.get(segment.id, datetime.now(timezone.utc))
        warnings: list[str] = []
        if segment.metadata.get("availability_unknown") or segment.available_seats is None or (segment.id in self.overrides and self.overrides[segment.id] is None):
            return SegmentAvailability(
                segment.id,
                True,
                None,
                policy.passengers,
                segment.transport_class,
                checked_at,
                self.source,
                None,
                ("Источник расписаний не подтверждает наличие и расположение мест",),
                self.stale_after_seconds,
            )

        seats = int(self.overrides.get(segment.id, segment.available_seats))
        transport_class = segment.transport_class
        if segment.id in self.class_overrides and transport_class not in self.class_overrides[segment.id]:
            reason = f"На участке {segment.origin_city.name} → {segment.destination_city.name} нет мест в выбранном классе"
            return SegmentAvailability(
                segment.id,
                False,
                seats,
                policy.passengers,
                transport_class,
                checked_at,
                self.source,
                reason,
                ("transport class is not allowed by policy",),
                self.stale_after_seconds,
            )

        reason = None
        if seats <= 0:
            reason = f"На участке {segment.origin_city.name} → {segment.destination_city.name} нет мест"
            warnings.append("no seats")
        elif not policy.accepts_class(transport_class):
            reason = f"На участке {segment.origin_city.name} → {segment.destination_city.name} нет мест в выбранном классе"
            warnings.append("transport class is not allowed by policy")
        elif seats < policy.passengers and not policy.allow_split_group:
            reason = f"На участке {segment.origin_city.name} → {segment.destination_city.name} доступно только {seats} места из необходимых {policy.passengers}"
            warnings.append("not enough seats for the full group")
        elif segment.id in self.split_only_segment_ids and policy.require_group_together:
            reason = "Группа может быть размещена только раздельно"
            warnings.append("group can only be split")

        available = reason is None and policy.has_enough_seats(seats) and policy.accepts_class(transport_class)
        if segment.id in self.split_only_segment_ids and policy.allow_split_group:
            available = seats > 0 and policy.accepts_class(transport_class)
            reason = None if available else reason
        return SegmentAvailability(
            segment.id,
            available,
            seats,
            policy.passengers,
            transport_class,
            checked_at,
            self.source,
            reason,
            tuple(warnings),
            self.stale_after_seconds,
        )
