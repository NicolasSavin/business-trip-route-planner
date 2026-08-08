import json
import logging
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.hotels.repository import JsonHotelRepository

spec = importlib.util.spec_from_file_location("hotels_api_for_test", Path(__file__).parents[1] / "app/api/hotels.py")
hotels = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(hotels)


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTELS_USERS_JSON", json.dumps([
        {"surname": "Иванов", "password": "0101"},
        {"surname": "Админов", "password": "1510"},
        {"surname": "Мельников", "password": "2403"},
    ]))
    monkeypatch.setenv("HOTELS_ADMIN_SURNAME", "Админов")
    monkeypatch.setenv("HOTELS_COOKIE_SECURE", "false")
    hotels.repository = JsonHotelRepository(tmp_path / "hotels.json", hotels.repository.seed_path)
    app = FastAPI(); app.include_router(hotels.router)
    return TestClient(app)


def login(c, surname="Иванов", password="0101"):
    return c.post("/api/hotels/auth/login", json={"surname": surname, "password": password})


def test_unauthenticated_hotels_is_private(tmp_path, monkeypatch):
    assert client(tmp_path, monkeypatch).get("/api/hotels").status_code == 401


def test_valid_login_trims_and_ignores_surname_case(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch); response = login(c, "  иВаНоВ ", " 0101 ")
    assert response.status_code == 200
    assert response.json() == {"surname": "Иванов", "is_admin": False}
    assert "HttpOnly" in response.headers["set-cookie"]
    assert c.get("/api/hotels/auth/me").status_code == 200


def test_invalid_and_excluded_login(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert login(c, password="9999").status_code == 401
    assert login(c, "Мельников", "2403").status_code == 401


def test_password_is_not_logged(tmp_path, monkeypatch, caplog):
    c = client(tmp_path, monkeypatch)
    with caplog.at_level(logging.DEBUG): login(c, "Иванов", "highly-secret")
    assert "highly-secret" not in caplog.text


def test_logout_invalidates_browser_session(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch); assert login(c).status_code == 200
    assert c.post("/api/hotels/auth/logout").status_code == 204
    assert c.get("/api/hotels/auth/me").status_code == 401


def test_normal_user_cannot_mutate_and_admin_can_edit(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch); login(c)
    original = c.get("/api/hotels").json()[0]
    body = {**original, "name": "Новое имя"}; body.pop("id")
    assert c.put(f"/api/hotels/{original['id']}", json=body).status_code == 403
    c.post("/api/hotels/auth/logout"); assert login(c, "Админов", "1510").json()["is_admin"]
    response = c.put(f"/api/hotels/{original['id']}", json=body)
    assert response.status_code == 200 and response.json()["name"] == "Новое имя"
