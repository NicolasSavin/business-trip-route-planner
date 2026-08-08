import json
import time

import pytest
from fastapi.testclient import TestClient

from app.hotels import HotelRepository, read_session, sign_session
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("HOTELS_USERS_JSON", json.dumps([
        {"surname": "Иванов", "password": "0101"},
        {"surname": "Петров", "password": "0202"},
        {"surname": "Мельников", "password": "2403"},
        {"surname": "Фурин", "password": "0303"},
    ], ensure_ascii=False))
    monkeypatch.setenv("HOTELS_ADMIN_SURNAME", "Иванов")
    monkeypatch.setenv("HOTELS_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("HOTELS_DATA_PATH", str(tmp_path / "hotels.json"))
    return TestClient(app)


def login(client, surname="Иванов", password="0101"):
    return client.post("/api/hotels/auth/login", json={"surname": surname, "password": password})


def test_authentication_normalization_and_safe_response(client):
    response = login(client, "  иВаНоВ  ")
    assert response.status_code == 200
    assert response.json() == {"surname": "Иванов", "is_admin": True}
    assert "0101" not in response.text
    assert client.get("/api/hotels/auth/me").json() == response.json()


@pytest.mark.parametrize("surname,password", [("Иванов", "9999"), ("Неизвестный", "0101"), ("Мельников", "2403"), ("Фурин", "0303")])
def test_rejected_credentials(client, surname, password):
    assert login(client, surname, password).status_code == 401


def test_permissions_and_crud(client):
    assert client.get("/api/hotels").status_code == 401
    assert login(client, "Петров", "0202").status_code == 200
    payload = {"name":"Тест", "locality":"Москва", "address":"", "photo_url":"", "report_amount":3500, "actual_price":None, "notes":""}
    assert client.get("/api/hotels").status_code == 200
    for method in (client.post, lambda u, **kw: client.put(u.replace("/api/hotels", "/api/hotels/1"), **kw), lambda u, **kw: client.delete(u + "/1")):
        assert method("/api/hotels", json=payload).status_code == 403
    login(client)
    created = client.post("/api/hotels", json=payload); assert created.status_code == 201
    hotel_id = created.json()["id"]
    payload["name"] = "Новый"
    assert client.put(f"/api/hotels/{hotel_id}", json=payload).json()["name"] == "Новый"
    assert client.delete(f"/api/hotels/{hotel_id}").status_code == 204
    assert client.delete(f"/api/hotels/{hotel_id}").status_code == 404


def test_invalid_expired_and_tampered_sessions(client):
    assert client.get("/api/hotels", cookies={"hotels_session":"invalid"}).status_code == 401
    expired = sign_session({"surname":"Иванов", "is_admin":True}, now=int(time.time()) - 50_000)
    assert client.get("/api/hotels", cookies={"hotels_session":expired}).status_code == 401
    valid = sign_session({"surname":"Иванов", "is_admin":True})
    assert client.get("/api/hotels", cookies={"hotels_session":valid + "x"}).status_code == 401


def test_atomic_repository_seed_has_84_records(tmp_path):
    repo = HotelRepository(tmp_path / "directory.json")
    assert len(repo.list()) == 84


def test_production_secret_required(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production"); monkeypatch.delenv("HOTELS_SESSION_SECRET", raising=False)
    from app.hotels import session_secret
    with pytest.raises(RuntimeError): session_secret()
