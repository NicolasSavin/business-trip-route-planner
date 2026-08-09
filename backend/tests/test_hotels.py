import importlib

from fastapi.testclient import TestClient


def configure(monkeypatch, tmp_path):
    monkeypatch.setenv("HOTELS_DATABASE", str(tmp_path / "hotels.sqlite3"))
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret-at-least-32-characters")
    monkeypatch.setenv("HOTELS_ADMIN_USERNAME", "administrator")
    monkeypatch.setenv("HOTELS_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("HOTELS_USER_USERNAME", "employee")
    monkeypatch.setenv("HOTELS_USER_PASSWORD", "user-password")


def login(client, username, password):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]


def test_seed_contains_exactly_84_valid_hotels(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    from app.main import app
    client = TestClient(app)
    login(client, "employee", "user-password")
    hotels = client.get("/api/v1/hotels").json()
    assert len(hotels) == 84
    assert len({hotel["id"] for hotel in hotels}) == 84
    assert not any(hotel["name"].startswith("Гостиница ") for hotel in hotels)
    assert {hotel["report_amount"] for hotel in hotels} <= {3000, 3500, 3600, 3900, 4000, 4100, 4500, 4700, 5500}
    assert all(hotel["actual_price"] is None for hotel in hotels)
    assert all(not hotel[field] for hotel in hotels for field in ("city", "address", "phone", "website", "photo_url", "notes"))


def test_permissions_search_and_persistence(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    from app.main import app
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/hotels").status_code == 401
    user = TestClient(app)
    login(user, "employee", "user-password")
    hotel = user.get("/api/v1/hotels?search=Моста").json()[0]
    hotel["actual_price"] = 2750
    assert user.put(f"/api/v1/hotels/{hotel['id']}", json={k: v for k, v in hotel.items() if k != "id"}).status_code == 403
    admin = TestClient(app)
    login(admin, "administrator", "admin-password")
    assert admin.put(f"/api/v1/hotels/{hotel['id']}", json={k: v for k, v in hotel.items() if k != "id"}).status_code == 200

    # Re-importing the storage module simulates a new application process; the one-time seed must not overwrite edits.
    import app.hotels as hotels_module
    importlib.reload(hotels_module)
    with hotels_module.connect() as database:
        assert database.execute("SELECT actual_price FROM hotels WHERE id = ?", (hotel["id"],)).fetchone()[0] == 2750
