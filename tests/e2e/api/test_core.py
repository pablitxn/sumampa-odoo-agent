"""E2E smoke tests for API base runtime."""

from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.config import AppSettings


def _test_settings() -> AppSettings:
    return AppSettings.model_validate(
        {
            "service": {"name": "sumampa-odoo-agent", "version": "0.1.0"},
            "agent": {"mode": "disabled"},
            "session_store": {"mode": "memory"},
            "attachments": {"store_mode": "memory"},
        }
    )


def test_health_endpoint_is_exposed() -> None:
    app = create_app(settings=_test_settings())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "sumampa-odoo-agent"
