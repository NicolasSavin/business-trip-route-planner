import json

from app.models import AvailabilityCheckResponse, AvailabilityStatus


def test_availability_status_pydantic_serializes_as_string():
    response = AvailabilityCheckResponse(status=AvailabilityStatus.CONFIRMED)

    assert response.model_dump(mode="json")["status"] == "confirmed"
    assert json.loads(response.model_dump_json())["status"] == "confirmed"
    assert AvailabilityCheckResponse.model_validate(
        {"status": "partially_confirmed"}
    ).status is AvailabilityStatus.PARTIALLY_CONFIRMED


def test_availability_status_values_are_unchanged():
    assert [status.value for status in AvailabilityStatus] == [
        "confirmed",
        "partially_confirmed",
        "unavailable",
        "unknown",
        "provider_error",
    ]
