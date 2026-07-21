from datetime import date


from app.domain import TransportClass, TransportType
from app.providers.rzd import MockRzdClient, RzdConfiguration, RzdMapper, RzdProvider
from app.providers.unified import build_default_registry


def test_rzd_configuration_defaults_disabled():
    config = RzdConfiguration()
    assert config.enabled is False
    assert config.priority == 10
    assert config.timeout == 5.0
    assert config.retry_count == 0


def test_mock_rzd_client_returns_realistic_train_options():
    trains = MockRzdClient().search_trains(date(2026, 8, 10))
    assert trains
    assert {train.train_number for train in trains} >= {"016М", "024М"}
    assert all(train.origin.code and train.destination.code for train in trains)
    assert any(any(car.car_type == TransportClass.COUPE and car.seats > 0 for car in train.cars) for train in trains)


def test_rzd_mapper_converts_client_models_to_route_segments():
    segments = RzdMapper().to_segments(MockRzdClient().search_trains(date(2026, 8, 10)))
    segment = segments[0]
    assert segment.provider == "rzd"
    assert segment.carrier.name == "РЖД"
    assert segment.transport_type == TransportType.TRAIN
    assert segment.available_seats > 0
    assert segment.metadata["source"] == "rzd_mock"


def test_rzd_provider_uses_injected_client_and_filters_transport():
    provider = RzdProvider(client=MockRzdClient())
    assert provider.get_segments(date(2026, 8, 10), [TransportType.BUS]) == []
    assert provider.get_segments(date(2026, 8, 10), [TransportType.TRAIN])
    assert provider.healthcheck() is True


def test_default_registry_contains_disabled_rzd_provider():
    registry = build_default_registry()
    rzd = registry.get("rzd")
    assert rzd is not None
    assert rzd.name == "РЖД"
    assert rzd.enabled is False
    assert rzd.metadata["ready_to_connect"] is True
    assert "rzd" not in [registration.id for registration, _ in registry.enabled([TransportType.TRAIN])]


def test_provider_health_endpoint_checks_rzd_readiness():
    from fastapi.testclient import TestClient
    from app.main import app

    response = TestClient(app).get("/api/v1/providers/health")
    assert response.status_code == 200
    rzd = next(item for item in response.json() if item["id"] == "rzd")
    assert rzd["health"] == "healthy"
    assert rzd["metadata"]["status_label"] == "готов к подключению"
