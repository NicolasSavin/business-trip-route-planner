from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import rzd_debug
from app.main import app
from app.providers.rzd_availability.exceptions import RZDAvailabilityError


@dataclass
class FakeSearchResult:
    raw: dict[str, str]
    trains: list[str]


class SuccessfulClient:
    async def search(self, *args, **kwargs):
        return FakeSearchResult(raw={"provider": "rzd"}, trains=["008С"])


class FailingClient:
    async def search(self, *args, **kwargs):
        raise RZDAvailabilityError("provider unavailable")


def test_application_import_creates_fastapi_app():
    assert isinstance(app, FastAPI)


def test_debug_search_success(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", SuccessfulClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
            "passengers": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["raw"] == {"provider": "rzd"}
    assert response.json()["normalized"]["trains"] == ["008С"]


def test_debug_search_provider_failure(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(rzd_debug, "RZDClient", FailingClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "code": "rzd_debug_failed",
        "error_type": "RZDAvailabilityError",
        "message": "provider unavailable",
        "details": {
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    }


def test_debug_search_is_hidden_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(rzd_debug, "RZDClient", SuccessfulClient)

    response = TestClient(app).post(
        "/api/v1/debug/rzd/search",
        json={
            "origin": "Москва",
            "destination": "Санкт-Петербург",
            "date": "2026-08-10",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
