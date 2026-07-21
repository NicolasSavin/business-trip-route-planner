from datetime import date

import pytest
from fastapi import HTTPException

from app.api.providers import enable_provider
from app.availability import BerthPosition, GenderRestriction, SeatAllocationService, SeatPreferences
from app.domain import TransportClass
from app.providers.tutu import MockTutuClient, TutuConfiguration, TutuMapper, TutuAvailabilityProvider
from app.providers.tutu.models import TutuCarriageDTO, TutuPlaceDTO
from app.providers.unified import build_default_registry

DAY = date(2026, 7, 21)


def test_tutu_configuration_defaults_disabled_and_unconfigured(monkeypatch):
    for key in ["TUTU_ENABLED", "TUTU_BASE_URL", "TUTU_API_KEY", "TUTU_LOGIN", "TUTU_PASSWORD", "TUTU_TIMEOUT_SECONDS"]:
        monkeypatch.delenv(key, raising=False)
    config = TutuConfiguration.from_env()
    assert not config.enabled
    assert not config.configured
    assert config.timeout_seconds == 20


def test_tutu_configuration_hides_secrets_in_repr():
    config = TutuConfiguration(base_url="https://partner.example", api_key="secret-key", login="login", password="secret-password")
    text = repr(config)
    assert "secret-key" not in text
    assert "secret-password" not in text
    assert config.configured


def test_provider_registry_registers_tutu_disabled_without_credentials():
    provider = build_default_registry().get("tutu")
    assert provider is not None
    assert provider.name == "Туту"
    assert not provider.enabled
    assert provider.metadata["configured"] is False
    assert provider.metadata["status"] == "disabled"
    assert provider.metadata["message"] == "Требуется официальный партнёрский доступ Туту"
    assert provider.capabilities.supports_place_map
    assert provider.capabilities.supports_gender_restrictions


def test_enable_without_credentials_returns_clear_error(monkeypatch):
    import app.api.providers as api_module

    monkeypatch.setattr(api_module, "registry", build_default_registry())
    with pytest.raises(HTTPException) as exc:
        enable_provider("tutu")
    assert exc.value.status_code == 400
    assert exc.value.detail == "Требуется официальный партнёрский доступ Туту"


def test_existing_providers_still_registered():
    ids = {item.id for item in build_default_registry().list()}
    assert {"mock", "rzd", "tutu"}.issubset(ids)


def test_mock_tutu_client_scenarios_are_deterministic():
    client = MockTutuClient()
    trains = client.search_trains(origin="Москва", destination="Казань", departure_date=DAY)
    assert [train.train_reference for train in trains] == ["tutu-full-coupe", "tutu-no-seats", "tutu-no-map"]
    assert client.get_carriage_places(train_reference="tutu-no-map", carriage_number="01") is None
    assert all(not place.is_available for place in client.get_carriage_places(train_reference="tutu-no-seats", carriage_number="01"))


def test_tutu_mapper_maps_coupe_lower_upper_compartment_gender_and_side():
    mapper = TutuMapper()
    carriage = TutuCarriageDTO("04", "platzkart", "3Э", "female", 1)
    place = mapper.to_place(TutuPlaceDTO("37", "platzkart", "lower", "9", "04", True, None, True), carriage)
    assert place.provider == "tutu"
    assert place.transport_class == TransportClass.PLATZKART
    assert place.berth_position == BerthPosition.LOWER
    assert place.compartment_number == "9"
    assert place.is_side
    assert place.gender_restriction == GenderRestriction.FEMALE


def test_tutu_mapper_uses_unknown_for_missing_values_and_no_raw_payload():
    availability = TutuMapper().to_carriage(TutuCarriageDTO("01", None, None, None, 4), None)
    assert availability.carriage_type == "unknown"
    assert availability.service_class == "unknown"
    assert availability.metadata == {"source": "tutu", "has_place_map": False}
    assert availability.available_places_count == 4


def _places():
    provider = TutuAvailabilityProvider()
    return provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=2))


def test_provider_integrates_with_seat_allocation_service_for_full_coupe():
    carriages = _places()
    first = next(item for item in carriages if item.carriage_number == "01" and item.metadata["train_reference"] == "tutu-full-coupe")
    assert first.seat_allocation is not None
    assert first.seat_allocation.matches_preferences
    assert len(first.seat_allocation.selected_places) == 2


def test_lower_and_upper_preferences():
    provider = TutuAvailabilityProvider()
    lower = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=2, prefer_lower=True))[0]
    upper = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=2, prefer_upper=True))[0]
    assert {p.berth_position for p in lower.seat_allocation.selected_places} == {BerthPosition.LOWER}
    assert {p.berth_position for p in upper.seat_allocation.selected_places} == {BerthPosition.UPPER}


def test_same_empty_compartment_and_not_enough_in_partial_compartment():
    provider = TutuAvailabilityProvider()
    ok = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=4, require_same_compartment=True, require_empty_compartment=True))[0]
    fail = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=5, require_same_compartment=True))[0]
    assert ok.seat_allocation.matches_preferences
    assert {p.compartment_number for p in ok.seat_allocation.selected_places} == {"1"}
    assert not fail.seat_allocation.matches_preferences


def test_different_carriages_can_be_used_when_same_carriage_is_not_required():
    client = MockTutuClient()
    carriages = [c for c in client.get_train_carriages(train_reference="tutu-full-coupe") if c.carriage_number in {"02", "03"}]
    mapper = TutuMapper()
    places = []
    for carriage in carriages:
        places.extend(mapper.to_carriage(carriage, client.get_carriage_places(train_reference="tutu-full-coupe", carriage_number=carriage.carriage_number)).places)
    result = SeatAllocationService().match(places, SeatPreferences(passengers=6, require_same_carriage=False))
    assert result.matches_preferences
    assert {p.carriage_number for p in result.selected_places} == {"02", "03"}


def test_side_berths_can_be_excluded():
    provider = TutuAvailabilityProvider()
    result = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=3, exclude_side_berths=True))
    platzkart = next(item for item in result if item.carriage_number == "04")
    assert not platzkart.seat_allocation.matches_preferences


def test_male_and_female_compartment_restrictions():
    provider = TutuAvailabilityProvider()
    female = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=2, gender=GenderRestriction.FEMALE))
    male = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=2, gender=GenderRestriction.MALE))
    assert next(item for item in female if item.carriage_number == "02").seat_allocation.matches_preferences
    assert next(item for item in male if item.carriage_number == "03").seat_allocation.matches_preferences


def test_no_place_map_and_no_available_places():
    provider = TutuAvailabilityProvider()
    result = provider.check_availability(origin="Москва", destination="Казань", departure_date=DAY, preferences=SeatPreferences(passengers=1))
    no_map = next(item for item in result if item.metadata.get("train_reference") is None and item.carriage_number == "01" and not item.places and item.available_places_count == 4)
    no_seats = [item for item in result if item.available_places_count == 0]
    assert no_map.metadata["has_place_map"] is False
    assert no_seats
