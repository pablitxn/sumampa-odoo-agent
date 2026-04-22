"""E2E smoke tests for Odoo services and conversation flows."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.integrations.agent_service import (
    MicrosoftAgentFrameworkOpenAIService,
)


def _image_attachment(filename: str = "adjunto.jpg") -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": "image/jpeg",
        "content_base64": base64.b64encode(b"fake-image").decode("ascii"),
    }


@pytest.fixture(autouse=True)
def patch_runtime_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_create_product_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/mutations",
            json={
                "kind": "create_product",
                "name": "Bombilla inox",
                "default_code": "BOMB-INOX",
                "list_price": 12.5,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "product.template"
    assert payload["payload"]["name"] == "Bombilla inox"


def test_create_partner_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/mutations",
            json={
                "kind": "create_partner",
                "name": "Proveedor Demo SA",
                "vat": "30712345678",
                "supplier_rank": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "res.partner"
    assert payload["payload"]["name"] == "Proveedor Demo SA"


def test_search_partners_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/lookups",
            json={"kind": "partners", "query": "sumampa"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "res.partner"
    assert payload["hits"][0]["display_name"] == "Sumampa SRL"


def test_search_products_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/lookups",
            json={"kind": "products", "query": "mate"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "product.template"
    assert payload["hits"][0]["display_name"] == "Mate camionero"


def test_search_journals_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/lookups",
            json={"kind": "journals", "query": "ventas"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "account.journal"
    assert payload["hits"][0]["extra"]["code"] == "VTA"


def test_validate_invoice_draft_reports_missing_context() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/validations",
            json={"kind": "invoice"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "invoice"
    assert payload["ok"] is False
    assert {"partner_id", "journal_id", "lines"} <= set(payload["missing_fields"])


def test_validate_argentina_invoice_draft_reports_fiscal_gaps() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/validations",
            json={
                "kind": "argentina_invoice",
                "emitter_taxpayer_type": "responsable_inscripto",
                "document_letter": "C",
                "partner_name": "Cliente demo",
                "partner_taxpayer_type": "responsable_inscripto",
                "line_count": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "argentina_invoice"
    assert payload["ok"] is False
    assert {"emitter_vat", "point_of_sale"} <= set(payload["missing_fields"])
    assert any("Letra esperada A" in warning for warning in payload["warnings"])


def test_validate_delivery_draft_reports_missing_context() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/validations",
            json={"kind": "delivery"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "delivery"
    assert payload["ok"] is False
    assert {"partner_id", "picking_type_id", "location_id", "location_dest_id", "moves"} <= set(
        payload["missing_fields"]
    )


def test_messages_endpoint_delegates_to_agent() -> None:
    async def fake_run(self, *, prompt, context, session_id=None):
        del self
        assert prompt == "revisá los productos"
        assert context["transport"]["channel"] == "whatsapp"
        assert context["transport"]["user_id"] == "5491112345678"
        return {
            "mode": "microsoft-agent-framework-openai",
            "session_id": session_id or "conversation-1",
            "text": "Te encontré 2 productos pendientes para revisar.",
            "stage": "idle",
        }

    app = create_app()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "conversation-1",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "text": "revisá los productos",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "conversation-1"
    assert payload["messages"][0]["text"] == "Te encontré 2 productos pendientes para revisar."
    assert payload["workflow_state"]["stage"] == "idle"


def test_messages_endpoint_serializes_attachments_for_agent() -> None:
    async def fake_run(self, *, prompt, context, session_id=None):
        del self, session_id
        assert prompt == "Hay un adjunto del usuario. Decime qué necesitás para seguir."
        attachments = context["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "adjunto.jpg"
        return {
            "mode": "microsoft-agent-framework-openai",
            "session_id": "attachment-session",
            "text": "Mandame la próxima confirmación.",
            "stage": "idle",
        }

    app = create_app()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "attachment-session",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "attachments": [_image_attachment()],
                    "context": {"customer_name": "Sumampa SRL"},
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_state"]["stage"] == "idle"
    assert payload["messages"][0]["text"] == "Mandame la próxima confirmación."
