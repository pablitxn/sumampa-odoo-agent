"""Unit tests for Odoo gateway behavior used by agent tools."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from sumampa_odoo_agent.integrations.odoo import DryRunOdooClient, OdooJsonRpcClient
from sumampa_odoo_agent.integrations.odoo.payloads import delivery_payload, invoice_payload
from sumampa_odoo_agent.services.errors import UpstreamServiceError
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryMoveInput,
    InvoiceInput,
    InvoiceLineInput,
    InvoiceValidationInput,
    ProductInput,
    SearchInput,
)


@pytest.mark.asyncio
async def test_dry_run_client_searches_and_mutates_in_memory() -> None:
    client = DryRunOdooClient()

    created = await client.create_product(
        ProductInput(
            name="Steel thermos",
            default_code="STEEL-THERMOS",
            list_price=45.0,
        )
    )
    search = await client.search_products(SearchInput(query="thermos", limit=5))

    assert created.mode == "dry-run"
    assert created.model == "product.template"
    assert any(hit.id == created.record_id for hit in search.hits)


@pytest.mark.asyncio
async def test_validation_results_match_between_dry_run_and_jsonrpc_modes() -> None:
    dry_run = DryRunOdooClient()
    jsonrpc = OdooJsonRpcClient(
        base_url="http://127.0.0.1:8069",
        database="sumampa",
        username="admin",
        password="admin",
    )

    try:
        query = InvoiceValidationInput()
        dry_run_result = await dry_run.validate_invoice_draft(query)
        jsonrpc_result = await jsonrpc.validate_invoice_draft(query)
    finally:
        await jsonrpc.aclose()

    assert dry_run_result.mode == "dry-run"
    assert jsonrpc_result.mode == "jsonrpc"
    assert dry_run_result.model_dump(exclude={"mode"}) == jsonrpc_result.model_dump(
        exclude={"mode"}
    )


@pytest.mark.asyncio
async def test_argentina_invoice_validation_reports_fiscal_warnings() -> None:
    client = DryRunOdooClient()

    result = await client.validate_argentina_invoice_draft(
        ArgentinaInvoiceValidationInput(
            emitter_vat="30000000000",
            emitter_taxpayer_type="registered_taxpayer",
            point_of_sale=1,
            document_letter="C",
            partner_name="Demo customer",
            partner_taxpayer_type="registered_taxpayer",
            line_count=1,
        )
    )

    assert result.ok is True
    assert result.missing_fields == []
    warnings = {warning.code: warning.details for warning in result.warnings}
    assert warnings["document_letter_mismatch"] == {
        "expected_letter": "A",
        "actual_document_letter": "C",
    }
    assert warnings["partner_tax_id_or_doc_type_missing"] == {
        "required_any": ["partner_vat", "partner_doc_type"]
    }


def test_delivery_move_requires_agent_provided_name() -> None:
    with pytest.raises(ValidationError):
        DeliveryMoveInput.model_validate({"product_id": 201, "quantity": 2})


@pytest.mark.asyncio
async def test_dry_run_invoice_and_delivery_use_shared_payload_builders() -> None:
    client = DryRunOdooClient()
    invoice = InvoiceInput(
        partner_id=101,
        lines=[InvoiceLineInput(product_id=201, quantity=2, price_unit=12.5, name="Straw")],
        narration="WhatsApp order",
    )
    delivery = DeliveryInput(
        partner_id=101,
        picking_type_id=501,
        location_id=601,
        location_dest_id=602,
        moves=[DeliveryMoveInput(product_id=201, quantity=2, name="Straw")],
        origin="WhatsApp order",
    )

    invoice_result = await client.create_invoice(invoice)
    delivery_result = await client.create_delivery(delivery)

    assert invoice_result.payload == invoice_payload(invoice)
    assert delivery_result.payload == delivery_payload(delivery)


@pytest.mark.asyncio
async def test_jsonrpc_translates_odoo_error_payload_to_application_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "2.0", "error": {"message": "bad credentials"}},
        )

    client = OdooJsonRpcClient(
        base_url="http://127.0.0.1:8069",
        database="sumampa",
        username="admin",
        password="admin",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(UpstreamServiceError) as exc_info:
            await client.search_products(SearchInput(query="yerba", limit=5))
    finally:
        await client.aclose()

    assert exc_info.value.code == "odoo_upstream_failure"
    assert exc_info.value.details["provider"] == "odoo"
    assert exc_info.value.details["operation"] == "authenticate"


@pytest.mark.asyncio
async def test_jsonrpc_rejects_missing_result_payload_as_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"jsonrpc": "2.0"},
        )

    client = OdooJsonRpcClient(
        base_url="http://127.0.0.1:8069",
        database="sumampa",
        username="admin",
        password="admin",
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(UpstreamServiceError) as exc_info:
            await client.search_products(SearchInput(query="yerba", limit=5))
    finally:
        await client.aclose()

    assert exc_info.value.code == "odoo_invalid_response"
    assert exc_info.value.details["provider"] == "odoo"
    assert exc_info.value.details["operation"] == "authenticate"
