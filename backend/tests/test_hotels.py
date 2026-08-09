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
    hotels = sorted(client.get("/api/v1/hotels").json(), key=lambda hotel: hotel["id"])
    assert len(hotels) == 84
    assert [hotel["id"] for hotel in hotels] == list(range(1, 85))
    expected_pairs = {
        1: ("У Моста", 3000),
        2: ("Шайба", 3500),
        5: ("900км, УЮТ - с Москвы правая сторона", 3900),
        14: ("Слобода", 3900),
        31: ("Караван (Омск)", 4500),
        41: ("Курское (солнечная горка)", 3600),
        45: ("Итель", 3500),
        47: ("Терса", 4100),
        70: ("Екатеринбург (отель Свердлова 27)", 5500),
        77: ("С-Посад, УЮТ", 4700),
        84: ("С-Петербург", 5500),
    }
    assert {hotel_id: (hotels[hotel_id - 1]["name"], hotels[hotel_id - 1]["report_amount"]) for hotel_id in expected_pairs} == expected_pairs
    assert not {"Амакс", "Азимут", "Алтай", "Байкал", "Метрополь", "Рэдиссон"} & {hotel["name"] for hotel in hotels}
    assert all(hotel["actual_price"] is None for hotel in hotels)
    assert all(not hotel[field] for hotel in hotels for field in ("city", "address", "phone", "website", "photo_url"))
    assert hotels[13]["notes"] == "+100 ₽ / 4000 ₽"


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

    persisted = admin.get(f"/api/v1/hotels?search={hotel['name']}").json()[0]
    persisted["actual_price"] = None
    response = admin.put(
        f"/api/v1/hotels/{hotel['id']}",
        json={key: value for key, value in persisted.items() if key != "id"},
    )
    assert response.status_code == 200
    assert response.json()["actual_price"] is None
    with hotels_module.connect() as database:
        assert database.execute("SELECT actual_price FROM hotels WHERE id = ?", (hotel["id"],)).fetchone()[0] is None
