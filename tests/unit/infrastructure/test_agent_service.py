"""Unit tests for agent service helpers."""

from typing import Any, cast

import httpx
from agent_framework.exceptions import ChatClientException
from openai import RateLimitError

from sumampa_odoo_agent.application.errors import TooManyRequestsError
from sumampa_odoo_agent.application.requests.odoo import ApplyPurchaseInvoiceProposalResult
from sumampa_odoo_agent.infrastructure.agent.purchase_flow import PurchaseWorkflowState
from sumampa_odoo_agent.infrastructure.agent.service import (
    _load_openai_chat_client,
    _translate_agent_run_error,
)


def test_load_openai_chat_client_handles_upstream_version_gap() -> None:
    client_cls = _load_openai_chat_client()
    assert client_cls.__name__ == "OpenAIChatClient"


def test_translate_agent_run_error_maps_rate_limit_to_application_error() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        429,
        headers={"retry-after": "2.536"},
        request=request,
    )
    rate_limit_error = RateLimitError(
        "Rate limit reached for gpt-5.4-mini. Please try again in 2.536s.",
        response=response,
        body={},
    )

    try:
        raise ChatClientException("chat client failed", inner_exception=rate_limit_error) from rate_limit_error
    except ChatClientException as exc:
        translated = _translate_agent_run_error(exc, model="gpt-5.4-mini")

    assert isinstance(translated, TooManyRequestsError)
    assert translated.code == "agent_rate_limited"
    assert translated.details["provider"] == "openai"
    assert translated.details["model"] == "gpt-5.4-mini"
    assert translated.details["retry_after_seconds"] == 2.536


def test_purchase_workflow_state_agent_snapshot_compacts_large_proposals() -> None:
    state = PurchaseWorkflowState.model_validate(
        {
            "session_id": "purchase-session-1",
            "context": {
                "supplier_id": 102,
                "create_stock_receipt": False,
                "markup_percentage": 30.0,
            },
            "proposal": {
                "mode": "dry-run",
                "supplier_name": "Sumampa SRL",
                "supplier_vat": None,
                "supplier_resolution": {
                    "status": "candidate",
                    "selected_partner_id": None,
                    "selected_display_name": None,
                    "selected_vat": None,
                    "extracted_name": "Sumampa SRL",
                    "extracted_vat": None,
                    "candidates": [
                        {
                            "partner_id": 102,
                            "display_name": "Sumampa SRL",
                            "vat": None,
                            "email": None,
                            "confidence": 0.98,
                            "reason": "Nombre exacto",
                        }
                    ],
                },
                "invoice_number": "TEST-0001",
                "invoice_date": "2026-04-19",
                "document_type": "Factura A",
                "currency": "ARS",
                "markup_percentage": 30.0,
                "totals": {"untaxed": 100.0, "vat": 21.0, "total": 121.0},
                "extracted_totals": {"untaxed": 100.0, "vat": 21.0, "total": 121.0},
                "lines": [
                    {
                        "line_number": 1,
                        "description": "Mate camionero",
                        "quantity": 2,
                        "unit_price_gross": 100.0,
                        "vat_rate": 21.0,
                        "unit_price_net": 82.64,
                        "subtotal_net": 165.29,
                        "subtotal_vat": 34.71,
                        "subtotal_gross": 200.0,
                        "product_match": {
                            "product_id": 2001,
                            "display_name": "Mate camionero",
                            "default_code": "MATE-1",
                            "current_sale_price": 140.0,
                            "current_cost": 80.0,
                            "current_stock": 10.0,
                            "confidence": 0.99,
                        },
                        "product_resolution": {
                            "status": "exact",
                            "selected_product_id": 2001,
                            "selected_display_name": "Mate camionero",
                            "selected_default_code": "MATE-1",
                            "candidates": [],
                        },
                        "suggested_sale_price": 140.0,
                        "suggested_markup_percentage": 30.0,
                        "stock_after_update": 10.0,
                    },
                    {
                        "line_number": 2,
                        "description": "Bombilla premium",
                        "quantity": 1,
                        "unit_price_gross": 50.0,
                        "vat_rate": 21.0,
                        "unit_price_net": 41.32,
                        "subtotal_net": 41.32,
                        "subtotal_vat": 8.68,
                        "subtotal_gross": 50.0,
                        "product_match": {
                            "product_id": None,
                            "display_name": None,
                            "default_code": None,
                            "current_sale_price": None,
                            "current_cost": None,
                            "current_stock": None,
                            "confidence": 0.0,
                        },
                        "product_resolution": {
                            "status": "candidate",
                            "selected_product_id": None,
                            "selected_display_name": None,
                            "selected_default_code": None,
                            "candidates": [
                                {
                                    "product_id": 3001,
                                    "display_name": "Bombilla premium 1",
                                    "default_code": "BOMB-1",
                                    "current_sale_price": 90.0,
                                    "current_cost": 40.0,
                                    "current_stock": 4.0,
                                    "confidence": 0.72,
                                    "reason": "Descripcion parecida",
                                }
                            ],
                        },
                        "suggested_sale_price": 65.0,
                        "suggested_markup_percentage": 30.0,
                        "stock_after_update": None,
                    },
                ],
                "needs_user_resolution": True,
                "warnings": ["Revisar producto pendiente"],
                "assumptions": [],
            },
            "last_result": ApplyPurchaseInvoiceProposalResult(
                mode="dry-run",
                applied=False,
                operations=[
                    {
                        "action": "create",
                        "model": "account.move",
                        "payload": {"invoice_number": "TEST-0001"},
                    }
                ],
                warnings=["Falta confirmar"],
            ).model_dump(mode="json"),
        }
    )

    snapshot = state.agent_snapshot()

    proposal = cast(dict[str, Any], snapshot["proposal"])
    unresolved_lines = cast(list[dict[str, Any]], proposal["unresolved_lines"])
    assert proposal["line_count"] == 2
    assert proposal["resolved_line_count"] == 1
    assert "lines" not in proposal
    assert unresolved_lines[0]["description"] == "Bombilla premium"
    assert unresolved_lines[0]["candidate_count"] == 1

    last_apply_result = cast(dict[str, Any], snapshot["last_apply_result"])
    assert last_apply_result["operation_count"] == 1
    assert last_apply_result["operation_models"] == ["account.move"]
    assert "operations" not in last_apply_result
