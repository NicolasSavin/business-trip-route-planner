from dataclasses import MISSING, fields
from app.domain import TransportSegment


class ValidationService:
    def validate_segment(self, segment: TransportSegment) -> None:
        required = [field.name for field in fields(TransportSegment) if field.default is MISSING and field.default_factory is MISSING]
        if segment.metadata.get("availability_unknown"):
            required = [name for name in required if name not in {"available_seats", "transport_class"}]
        for name in required:
            if getattr(segment, name, None) is None:
                raise ValueError(f"Segment {segment.id} is missing required field: {name}")
        if segment.arrival_datetime <= segment.departure_datetime:
            raise ValueError(f"Segment {segment.id} arrival must be later than departure")
        if segment.duration_minutes < 0:
            raise ValueError(f"Segment {segment.id} duration must be non-negative")
        if segment.available_seats is not None and segment.available_seats < 0:
            raise ValueError(f"Segment {segment.id} available seats must be non-negative")

    def validate_segments(self, segments: list[TransportSegment]) -> None:
        for segment in segments:
            self.validate_segment(segment)
