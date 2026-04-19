"""E2E smoke tests for enabled Odoo and agent modules."""

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.adapters.api.main import create_app
from sumampa_odoo_agent.application.requests.odoo import ExtractedPurchaseInvoiceDocument
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatReplyRequest,
    PurchaseChatTurnDecision,
)
from sumampa_odoo_agent.infrastructure.agent.service import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.infrastructure.extraction.service import (
    OpenAIPurchaseInvoiceExtractor,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    OpenAIPurchaseChatAssistant,
)
from sumampa_odoo_agent.infrastructure.runtime.state import reset_runtime_state_for_tests


@pytest.fixture(autouse=True)
def patch_runtime_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_PURCHASE_CHAT_MODE", "openai")
    monkeypatch.setenv("ORCHID_AGENT_MODE", "disabled")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    reset_runtime_state_for_tests()

    async def fake_extract(self, command):  # type: ignore[no-untyped-def]
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

    async def fake_decide(self, *, stage, user_message, proposal, last_apply_result):  # type: ignore[no-untyped-def]
        del self, user_message, proposal, last_apply_result
        if stage == "awaiting_invoice_confirmation":
            return PurchaseChatTurnDecision(action="confirm_invoice")
        if stage == "awaiting_stock_confirmation":
            return PurchaseChatTurnDecision(action="confirm_stock")
        if stage == "awaiting_price_confirmation":
            return PurchaseChatTurnDecision(action="confirm_prices")
        return PurchaseChatTurnDecision(action="reply_only")

    async def fake_reply(self, request: PurchaseChatReplyRequest):  # type: ignore[no-untyped-def]
        return f"event={request.event}"

    monkeypatch.setattr(OpenAIPurchaseInvoiceExtractor, "extract", fake_extract)
    monkeypatch.setattr(OpenAIPurchaseChatAssistant, "decide", fake_decide)
    monkeypatch.setattr(OpenAIPurchaseChatAssistant, "reply", fake_reply)
    yield
    reset_runtime_state_for_tests()


def test_create_product_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/products",
            json={
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
            "/api/v1/odoo/partners",
            json={
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
        response = client.get("/api/v1/odoo/partners/search", params={"query": "sumampa"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "res.partner"
    assert payload["hits"][0]["display_name"] == "Sumampa SRL"


def test_search_products_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/odoo/products/search", params={"query": "mate"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["model"] == "product.template"
    assert payload["hits"][0]["display_name"] == "Mate camionero"


def test_search_journals_uses_dry_run_backend() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/odoo/journals/search", params={"query": "ventas"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "account.journal"
    assert payload["hits"][0]["extra"]["code"] == "VTA"


def test_validate_invoice_draft_reports_missing_context() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/odoo/invoices/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "invoice"
    assert payload["ok"] is False
    assert {"partner_id", "journal_id", "lines"} <= set(payload["missing_fields"])


def test_validate_argentina_invoice_draft_reports_fiscal_gaps() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/odoo/invoices/validate-argentina",
            params={
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
        response = client.get("/api/v1/odoo/deliveries/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "delivery"
    assert payload["ok"] is False
    assert {"partner_id", "picking_type_id", "location_id", "location_dest_id", "moves"} <= set(
        payload["missing_fields"]
    )


def test_analyze_purchase_invoice_builds_markup_proposal_from_uploaded_image() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/purchase-invoices/proposals",
            data={"supplier_name": "Sumampa SRL", "markup_percentage": "30"},
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
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


def test_analyze_purchase_invoice_accepts_multiple_images() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/purchase-invoices/proposals",
            data={"supplier_name": "Sumampa SRL", "markup_percentage": "30"},
            files=[
                ("invoice_images", ("factura-acme-1.jpg", b"fake-image-1", "image/jpeg")),
                ("invoice_images", ("factura-acme-2.jpg", b"fake-image-2", "image/jpeg")),
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["supplier_name"] == "Sumampa SRL"
    assert payload["invoice_number"] == "TEST-0001"


def test_apply_purchase_invoice_proposal_returns_product_and_bill_operations() -> None:
    app = create_app()
    with TestClient(app) as client:
        proposal_response = client.post(
            "/api/v1/odoo/purchase-invoices/proposals",
            data={"supplier_name": "Sumampa SRL", "markup_percentage": "30"},
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
        )
        proposal = proposal_response.json()
        response = client.post(
            "/api/v1/odoo/purchase-invoices/apply",
            json={
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


def test_purchase_chat_flow_goes_from_invoice_to_price_update() -> None:
    app = create_app()
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "message": "te paso una factura nueva",
                "supplier_name": "Sumampa SRL",
                "markup_percentage": "30",
            },
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
        )
        first_payload = first.json()

        second = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, cargar factura",
                "supplier_id": "102",
                "journal_id": "301",
                "markup_percentage": "30",
            },
        )
        second_payload = second.json()

        third = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, actualizar precios",
                "supplier_id": "102",
                "journal_id": "301",
                "markup_percentage": "30",
            },
        )
        third_payload = third.json()

    assert first.status_code == 200
    assert first_payload["stage"] == "awaiting_invoice_confirmation"
    assert first_payload["proposal"]["invoice_number"] is not None

    assert second.status_code == 200
    assert second_payload["stage"] == "awaiting_price_confirmation"
    assert second_payload["last_apply_result"]["applied"] is True

    assert third.status_code == 200
    assert third_payload["stage"] == "completed"
    assert third_payload["assistant_message"] == "event=price_applied"


def test_purchase_chat_keeps_supplier_resolution_across_turns_when_form_leaves_supplier_blank() -> None:
    app = create_app()
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "message": "te paso una factura nueva",
                "supplier_name": "Sumampa SRL",
                "markup_percentage": "30",
            },
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
        )
        first_payload = first.json()

        second = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, cargar factura",
                "journal_id": "301",
            },
        )
        second_payload = second.json()

    assert first.status_code == 200
    assert first_payload["stage"] == "awaiting_invoice_confirmation"
    assert first_payload["proposal"]["supplier_resolution"]["selected_partner_id"] == 102

    assert second.status_code == 200
    assert second_payload["stage"] == "awaiting_price_confirmation"
    assert second_payload["last_apply_result"]["applied"] is True
    assert any(
        operation["model"] == "account.move"
        for operation in second_payload["last_apply_result"]["operations"]
    )


def test_purchase_chat_flow_splits_bill_stock_and_prices_when_requested() -> None:
    app = create_app()
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "message": "te paso una factura nueva",
                "supplier_name": "Sumampa SRL",
                "markup_percentage": "30",
                "create_stock_receipt": "true",
                "picking_type_id": "501",
                "location_id": "603",
                "location_dest_id": "601",
            },
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
        )
        first_payload = first.json()

        second = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, cargar factura",
                "supplier_id": "102",
                "journal_id": "301",
            },
        )
        second_payload = second.json()

        third = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, generar recepción",
            },
        )
        third_payload = third.json()

        fourth = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "session_id": first_payload["session_id"],
                "message": "si, actualizar precios",
            },
        )
        fourth_payload = fourth.json()

    assert first.status_code == 200
    assert first_payload["stage"] == "awaiting_invoice_confirmation"

    assert second.status_code == 200
    assert second_payload["stage"] == "awaiting_stock_confirmation"
    assert second_payload["last_apply_result"]["applied"] is True
    assert any(
        operation["model"] == "account.move"
        for operation in second_payload["last_apply_result"]["operations"]
    )
    assert all(
        operation["model"] != "stock.picking"
        for operation in second_payload["last_apply_result"]["operations"]
    )

    assert third.status_code == 200
    assert third_payload["stage"] == "awaiting_price_confirmation"
    assert any(
        operation["model"] == "stock.picking"
        for operation in third_payload["last_apply_result"]["operations"]
    )

    assert fourth.status_code == 200
    assert fourth_payload["stage"] == "completed"
    assert fourth_payload["assistant_message"] == "event=price_applied"


def test_purchase_chat_stops_in_resolution_when_supplier_is_ambiguous() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={
                "message": "te paso una factura nueva",
                "supplier_name": "Acme Proveedor SA",
                "markup_percentage": "30",
            },
            files={"invoice_image": ("factura-acme.jpg", b"fake-image", "image/jpeg")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "awaiting_resolution"
    assert payload["proposal"]["needs_user_resolution"] is True
    assert payload["assistant_message"] == "event=analysis_requires_resolution"


def test_purchase_chat_handles_small_talk_without_invoice() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/odoo/purchase-chat/messages",
            data={"message": "ey como va?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "awaiting_invoice"
    assert payload["assistant_message"] == "event=awaiting_invoice"


def test_run_agent_uses_openai_backend_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    reset_runtime_state_for_tests()

    async def fake_run(self, *, prompt, context, session_id=None):  # type: ignore[no-untyped-def]
        return {
            "mode": "microsoft-agent-framework-openai",
            "text": "respuesta simulada para test",
            "session_id": session_id,
            "context": context,
            "prompt": prompt,
        }

    monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/runs",
            json={
                "prompt": "Necesito preparar una factura simple",
                "session_id": "demo-session",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "microsoft-agent-framework-openai"
    assert payload["session_id"] == "demo-session"
    assert "simulada" in payload["text"].lower()
