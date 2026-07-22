from fastapi.testclient import TestClient

from app.main import app


def test_resolve_endpoint_returns_sarapul_codes():
    response = TestClient(app).get("/api/v1/locations/resolve", params={"q": "Сарапул"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["normalized_query"] == "сарапул"
    assert payload["matches"][0]["code"] == "c42"
    assert {item["code"] for item in payload["matches"][0]["stations"]} >= {"s9612363", "s9635668"}
