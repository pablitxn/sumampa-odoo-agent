"""MCP tools for Odoo write operations."""

from __future__ import annotations

from sumampa_odoo_agent.adapters.mcp.tools.common import ToolSpec
from sumampa_odoo_agent.application.requests.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreateProductCommand,
    SearchJournalsQuery,
    SearchLocationsQuery,
    SearchPartnersQuery,
    SearchPickingTypesQuery,
    SearchProductsQuery,
    SearchTaxesQuery,
    ValidateArgentinaInvoiceDraftQuery,
    ValidateDeliveryDraftQuery,
    ValidateInvoiceDraftQuery,
)


async def _search_partners(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchPartnersQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _search_products(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchProductsQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _search_journals(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchJournalsQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _search_taxes(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchTaxesQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _search_picking_types(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchPickingTypesQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _search_locations(container, arguments: dict[str, object]) -> dict[str, object]:
    query = SearchLocationsQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _validate_invoice_draft(container, arguments: dict[str, object]) -> dict[str, object]:
    query = ValidateInvoiceDraftQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _validate_argentina_invoice_draft(
    container, arguments: dict[str, object]
) -> dict[str, object]:
    query = ValidateArgentinaInvoiceDraftQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _validate_delivery_draft(container, arguments: dict[str, object]) -> dict[str, object]:
    query = ValidateDeliveryDraftQuery.model_validate(arguments)
    result = await container.query_bus.dispatch(query)
    return {"result": result.model_dump()}


async def _create_product(container, arguments: dict[str, object]) -> dict[str, object]:
    command = CreateProductCommand.model_validate(arguments)
    result = await container.command_bus.dispatch(command)
    return {"result": result.model_dump()}


async def _create_invoice(container, arguments: dict[str, object]) -> dict[str, object]:
    command = CreateInvoiceCommand.model_validate(arguments)
    result = await container.command_bus.dispatch(command)
    return {"result": result.model_dump()}


async def _create_delivery(container, arguments: dict[str, object]) -> dict[str, object]:
    command = CreateDeliveryCommand.model_validate(arguments)
    result = await container.command_bus.dispatch(command)
    return {"result": result.model_dump()}


def get_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="odoo_search_partners",
            description="Search res.partner records in Odoo by name, email or VAT.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=_search_partners,
        ),
        ToolSpec(
            name="odoo_search_products",
            description="Search product.template records in Odoo by name or default_code.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=_search_products,
        ),
        ToolSpec(
            name="odoo_search_journals",
            description="Search account.journal records in Odoo.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
            handler=_search_journals,
        ),
        ToolSpec(
            name="odoo_search_taxes",
            description="Search account.tax records in Odoo.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
            handler=_search_taxes,
        ),
        ToolSpec(
            name="odoo_search_picking_types",
            description="Search stock.picking.type records in Odoo.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
            handler=_search_picking_types,
        ),
        ToolSpec(
            name="odoo_search_locations",
            description="Search stock.location records in Odoo.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
            handler=_search_locations,
        ),
        ToolSpec(
            name="odoo_validate_invoice_draft",
            description="Validate whether the minimal context for creating an invoice is complete.",
            input_schema={
                "type": "object",
                "properties": {
                    "partner_id": {"type": "integer"},
                    "journal_id": {"type": "integer"},
                    "move_type": {"type": "string"},
                    "line_count": {"type": "integer"},
                },
            },
            handler=_validate_invoice_draft,
        ),
        ToolSpec(
            name="odoo_validate_argentina_invoice_draft",
            description="Validate Argentine electronic invoice prerequisites before creating a fiscal document.",
            input_schema={
                "type": "object",
                "properties": {
                    "emitter_vat": {"type": "string"},
                    "emitter_taxpayer_type": {"type": "string"},
                    "point_of_sale": {"type": "integer"},
                    "wsfe_service": {"type": "string"},
                    "document_letter": {"type": "string"},
                    "partner_name": {"type": "string"},
                    "partner_vat": {"type": "string"},
                    "partner_doc_type": {"type": "string"},
                    "partner_taxpayer_type": {"type": "string"},
                    "line_count": {"type": "integer"},
                    "email_to": {"type": "string"},
                },
            },
            handler=_validate_argentina_invoice_draft,
        ),
        ToolSpec(
            name="odoo_validate_delivery_draft",
            description="Validate whether the minimal context for creating a delivery is complete.",
            input_schema={
                "type": "object",
                "properties": {
                    "partner_id": {"type": "integer"},
                    "picking_type_id": {"type": "integer"},
                    "location_id": {"type": "integer"},
                    "location_dest_id": {"type": "integer"},
                    "move_count": {"type": "integer"},
                },
            },
            handler=_validate_delivery_draft,
        ),
        ToolSpec(
            name="odoo_create_product",
            description="Create a product.template record in Odoo.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "default_code": {"type": "string"},
                    "list_price": {"type": "number"},
                    "description_sale": {"type": "string"},
                },
                "required": ["name"],
            },
            handler=_create_product,
        ),
        ToolSpec(
            name="odoo_create_invoice",
            description="Create an account.move invoice in Odoo.",
            input_schema={
                "type": "object",
                "properties": {
                    "partner_id": {"type": "integer"},
                    "move_type": {"type": "string"},
                    "invoice_date": {"type": "string"},
                    "narration": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "number"},
                                "price_unit": {"type": "number"},
                                "name": {"type": "string"},
                            },
                            "required": ["product_id", "quantity", "price_unit"],
                        },
                    },
                },
                "required": ["partner_id", "lines"],
            },
            handler=_create_invoice,
        ),
        ToolSpec(
            name="odoo_create_delivery",
            description="Create a stock.picking delivery order in Odoo.",
            input_schema={
                "type": "object",
                "properties": {
                    "partner_id": {"type": "integer"},
                    "picking_type_id": {"type": "integer"},
                    "location_id": {"type": "integer"},
                    "location_dest_id": {"type": "integer"},
                    "origin": {"type": "string"},
                    "scheduled_date": {"type": "string"},
                    "moves": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "number"},
                                "name": {"type": "string"},
                            },
                            "required": ["product_id", "quantity"],
                        },
                    },
                },
                "required": [
                    "partner_id",
                    "picking_type_id",
                    "location_id",
                    "location_dest_id",
                    "moves",
                ],
            },
            handler=_create_delivery,
        ),
    ]
