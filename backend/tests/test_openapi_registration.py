from app.main import app


def test_openapi_exports_browser_and_provider_routes():
    paths = app.openapi()["paths"]

    assert "/api/v1/browser/health" in paths
    assert "/api/v1/browser/ping" in paths
    assert "/api/v1/browser/screenshot" in paths
    assert "/api/v1/browser/metrics" in paths
    assert "/api/v1/providers" in paths
    assert "/api/v1/providers/health" in paths
    assert "/api/v1/providers/{provider_id}/enable" in paths
    assert "/api/v1/providers/{provider_id}/disable" in paths
    assert "/api/v1/providers/tutu/test" in paths
    assert "/api/v1/providers/tutu/live-test" in paths
