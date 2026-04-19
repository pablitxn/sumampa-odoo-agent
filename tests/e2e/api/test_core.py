"""E2E smoke tests for API base runtime."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.adapters.api.main import create_app


@pytest.fixture
def core_only_enabled_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "schema_version": 1,
        "enabled_modules": ["core"],
    }
    enabled_path = tmp_path / "enabled_modules.json"
    enabled_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ORCHID_ENABLED_MODULES_PATH", str(enabled_path))


def test_health_endpoint_is_exposed(core_only_enabled_modules: None) -> None:
    del core_only_enabled_modules
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["enabled_modules"] == ["core"]


def test_capabilities_endpoint_is_exposed(core_only_enabled_modules: None) -> None:
    del core_only_enabled_modules
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "sumampa-odoo-agent"
    assert {module["name"] for module in payload["modules"]} == {"agent", "core", "odoo"}


def test_disabled_module_route_returns_consistent_http_error(
    core_only_enabled_modules: None,
) -> None:
    del core_only_enabled_modules
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/odoo/products", json={"name": "Mate"})

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "http_error"
    assert payload["message"] == "Not Found"


def test_purchase_invoice_demo_route_is_available(core_only_enabled_modules: None) -> None:
    del core_only_enabled_modules
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/demo/purchase-invoices")

    assert response.status_code == 200
    assert "Sumampa Compras Chat" in response.text


def test_purchase_invoice_demo_copy_route_is_available(core_only_enabled_modules: None) -> None:
    del core_only_enabled_modules
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/demo/purchase-invoices-copy.js")

    assert response.status_code == 200
    assert "window.PURCHASE_INVOICE_DEMO_COPY" in response.text
