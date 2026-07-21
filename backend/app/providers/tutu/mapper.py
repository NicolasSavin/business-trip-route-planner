from __future__ import annotations

from app.availability.seats import BerthPosition, GenderRestriction, RailwayCarriageAvailability, RailwayPlace
from app.domain import TransportClass
from app.providers.tutu.models import TutuCarriageDTO, TutuPlaceDTO


class TutuMapper:
    provider = "tutu"

    def to_place(self, dto: TutuPlaceDTO, carriage: TutuCarriageDTO) -> RailwayPlace:
        return RailwayPlace(
            provider=self.provider,
            place_number=dto.place_number,
            carriage_number=dto.carriage_number,
            transport_class=self._transport_class(carriage.carriage_type),
            place_type=dto.place_type or "unknown",
            berth_position=self._berth(dto.berth_position),
            compartment_number=dto.compartment_number,
            is_side=bool(dto.is_side),
            gender_restriction=self._gender(dto.gender_restriction or carriage.gender_restriction),
            is_available=dto.is_available,
            metadata={"source": "tutu", "has_place_map": True},
        )

    def to_carriage(self, carriage: TutuCarriageDTO, places: list[TutuPlaceDTO] | None) -> RailwayCarriageAvailability:
        mapped_places = tuple(self.to_place(place, carriage) for place in (places or []))
        return RailwayCarriageAvailability(
            provider=self.provider,
            carriage_number=carriage.carriage_number,
            transport_class=self._transport_class(carriage.carriage_type),
            service_class=carriage.service_class or "unknown",
            carriage_type=carriage.carriage_type or "unknown",
            gender_restriction=self._gender(carriage.gender_restriction),
            available_places_count=sum(1 for p in mapped_places if p.is_available) if places is not None else carriage.available_places_count,
            places=mapped_places,
            metadata={"source": "tutu", "has_place_map": places is not None},
        )

    def _transport_class(self, value: str | None) -> TransportClass:
        normalized = (value or "").lower()
        return {"coupe": TransportClass.COUPE, "platzkart": TransportClass.PLATZKART, "sleeper": TransportClass.SLEEPER, "seated": TransportClass.SEATED}.get(normalized, TransportClass.ECONOMY)

    def _berth(self, value: str | None) -> BerthPosition:
        normalized = (value or "").lower()
        return {"lower": BerthPosition.LOWER, "upper": BerthPosition.UPPER}.get(normalized, BerthPosition.UNKNOWN)

    def _gender(self, value: str | None) -> GenderRestriction:
        normalized = (value or "").lower()
        return {"male": GenderRestriction.MALE, "female": GenderRestriction.FEMALE, "mixed": GenderRestriction.MIXED}.get(normalized, GenderRestriction.UNKNOWN)
