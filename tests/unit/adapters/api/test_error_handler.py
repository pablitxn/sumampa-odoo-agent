"""Unit tests for API error handler behavior."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from sumampa_odoo_agent.adapters.api.error_handler import register_exception_handlers
from sumampa_odoo_agent.application.errors import (
    DisabledModuleError,
    NotFoundError,
    TooManyRequestsError,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    class InputPayload(BaseModel):
        name: str

    @app.get("/not-found")
    async def not_found() -> dict[str, str]:
        raise NotFoundError(
            "Resource not found",
            code="resource_not_found",
            details={"resource": "demo"},
        )

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    @app.get("/module-disabled")
    async def module_disabled() -> dict[str, str]:
        raise DisabledModuleError("odoo")

    @app.get("/rate-limited")
    async def rate_limited() -> dict[str, str]:
        raise TooManyRequestsError(
            "Retry later",
            code="agent_rate_limited",
            details={"retry_after_seconds": 2.4},
        )

    @app.post("/validate")
    async def validate(payload: InputPayload) -> dict[str, str]:
        return {"name": payload.name}

    return app


def test_application_error_maps_to_consistent_payload() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "NotFoundError"
    assert body["code"] == "resource_not_found"
    assert body["details"]["resource"] == "demo"


def test_unhandled_error_maps_to_internal_error_payload() -> None:
    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "InternalServerError"
    assert body["code"] == "internal_error"


def test_validation_error_has_consistent_shape() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.post("/validate", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "ValidationError"
    assert body["code"] == "validation_error"
    assert isinstance(body["details"]["errors"], list)


def test_disabled_module_error_maps_to_404() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/module-disabled")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "module_disabled"
    assert body["details"]["module"] == "odoo"


def test_rate_limited_error_maps_to_429_and_sets_retry_after_header() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/rate-limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3"
    body = response.json()
    assert body["code"] == "agent_rate_limited"
    assert body["details"]["retry_after_seconds"] == 2.4
