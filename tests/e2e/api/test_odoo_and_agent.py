"""E2E smoke tests for Odoo services and conversation flows."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.integrations.agent_service import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.integrations.openai_extraction import (
    OpenAIPurchaseInvoiceExtractor,
)
from sumampa_odoo_agent.services.models.odoo import ExtractedPurchaseInvoiceDocument


def _image_attachment(filename: str = "factura-acme.jpg") -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": "image/jpeg",
        "content_base64": base64.b64encode(b"fake-image").decode("ascii"),
    }


@pytest.fixture(autouse=True)
def patch_runtime_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_extract(self, command):
        supplier_name = command.supplier_name or "Proveedor Demo SA"
        return ExtractedPurchaseInvoiceDocument.model_validate(
            {
                "supplier_name": supplier_name,
                "supplier_vat": command.supplier_vat,
                "invoice_number": "TEST-0001",
                "invoice_date": "2026-04-19",
                "document_type": "Factura A",
                "currency": "ARS",
                "subtotal_untaxed": 165.29,
                "total_vat": 34.71,
                "total_amount": 200.0,
                "lines": [
                    {
                        "description": "Mate camionero",
                        "quantity": 2,
                        "unit_price_gross": 100.0,
                        "vat_rate": 21.0,
                    }
                ],
            }
        )

    monkeypatch.setattr(OpenAIPurchaseInvoiceExtractor, "extract", fake_extract)


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


def test_analyze_purchase_invoice_builds_markup_proposal_from_json_attachment() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/purchase-invoices/analyze",
            json={
                "supplier_name": "Sumampa SRL",
                "markup_percentage": 30.0,
                "attachments": [_image_attachment()],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["supplier_name"] == "Sumampa SRL"
    assert payload["supplier_resolution"]["status"] == "exact"
    assert payload["needs_user_resolution"] is False
    assert payload["document_type"] == "Factura A"
    assert payload["totals"]["total"] > 0
    assert payload["extracted_totals"]["total"] > 0
    assert payload["lines"][0]["suggested_markup_percentage"] == 30.0
    assert payload["lines"][0]["product_match"]["product_id"] is not None


def test_apply_purchase_invoice_proposal_returns_product_and_bill_operations() -> None:
    app = create_app()
    with TestClient(app) as client:
        proposal_response = client.post(
            "/api/v1/purchase-invoices/analyze",
            json={
                "supplier_name": "Sumampa SRL",
                "markup_percentage": 30.0,
                "attachments": [_image_attachment()],
            },
        )
        proposal = proposal_response.json()
        response = client.post(
            "/api/v1/odoo/mutations",
            json={
                "kind": "apply_purchase_invoice",
                "supplier_id": 102,
                "journal_id": 301,
                "create_vendor_bill": True,
                "update_products": True,
                "create_stock_receipt": False,
                "proposal": proposal,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["applied"] is True
    assert any(operation["model"] == "product.template" for operation in payload["operations"])
    assert any(operation["model"] == "account.move" for operation in payload["operations"])


def test_messages_endpoint_delegates_to_agent() -> None:
    async def fake_run(self, *, prompt, context, session_id=None):
        assert prompt == "revisá los productos"
        assert context["transport"]["channel"] == "whatsapp"
        assert context["transport"]["user_id"] == "5491112345678"
        return {
            "mode": "microsoft-agent-framework-openai",
            "session_id": session_id or "purchase-session-1",
            "text": "Te encontré 2 productos pendientes para revisar.",
            "purchase_flow": {
                "stage": "awaiting_resolution",
                "proposal": {
                    "mode": "dry-run",
                    "supplier_name": "Sumampa SRL",
                    "supplier_vat": None,
                    "supplier_resolution": {
                        "status": "exact",
                        "selected_partner_id": 102,
                        "selected_display_name": "Sumampa SRL",
                        "selected_vat": None,
                        "extracted_name": "Sumampa SRL",
                        "extracted_vat": None,
                        "candidates": [],
                    },
                    "invoice_number": "TEST-0001",
                    "invoice_date": "2026-04-19",
                    "document_type": "Factura A",
                    "currency": "ARS",
                    "markup_percentage": 30.0,
                    "lines": [],
                    "totals": {"untaxed": 100.0, "vat": 21.0, "total": 121.0},
                    "needs_user_resolution": True,
                    "warnings": [],
                    "assumptions": [],
                },
                "last_apply_result": None,
                "context": {},
            },
        }

    app = create_app()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "purchase-session-1",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "text": "revisá los productos",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "purchase-session-1"
    assert payload["messages"][0]["text"] == "Te encontré 2 productos pendientes para revisar."
    assert payload["workflow_state"]["stage"] == "awaiting_resolution"
    assert payload["workflow_state"]["proposal"]["invoice_number"] == "TEST-0001"


def test_messages_endpoint_serializes_attachments_for_agent() -> None:
    async def fake_run(self, *, prompt, context, session_id=None):
        del self, session_id
        assert prompt == "Analizá la factura adjunta y guiame con el siguiente paso."
        attachments = context["purchase_workflow"]["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "factura-acme.jpg"
        return {
            "mode": "microsoft-agent-framework-openai",
            "session_id": "attachment-session",
            "text": "Mandame la próxima confirmación.",
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
                    "context": {"supplier_name": "Sumampa SRL"},
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_state"]["stage"] == "awaiting_invoice"
    assert payload["messages"][0]["text"] == "Mandame la próxima confirmación."
