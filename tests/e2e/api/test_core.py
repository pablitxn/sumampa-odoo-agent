"""E2E smoke tests for API base runtime."""

from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app


def test_health_endpoint_is_exposed() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "sumampa-odoo-agent"

def test_legacy_capabilities_endpoint_is_removed() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/capabilities")
    assert response.status_code == 404
    assert response.json()["code"] == "http_error"

def test_legacy_demo_route_is_removed() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/demo/purchase-invoices")

    assert response.status_code == 404
    assert response.json()["code"] == "http_error"
