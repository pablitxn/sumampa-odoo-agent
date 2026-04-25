"""Odoo tools available to the agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryMoveInput,
    DeliveryValidationInput,
    InvoiceInput,
    InvoiceLineInput,
    InvoiceMoveType,
    InvoiceValidationInput,
    PartnerInput,
    ProductInput,
    SearchInput,
)

ToolCallable = Callable[..., Awaitable[dict[str, Any]]]
ToolFactory = Callable[[OdooGateway], ToolCallable]


@dataclass(frozen=True, slots=True)
class OdooToolSpec:
    name: str
    build: ToolFactory


async def _dump_model(result: Awaitable[BaseModel]) -> dict[str, Any]:
    return (await result).model_dump()


def _create_partner_tool(odoo: OdooGateway) -> ToolCallable:
    async def create_partner(
        name: Annotated[str, "Partner name"],
        vat: Annotated[str | None, "Partner tax ID or VAT number"] = None,
        email: Annotated[str | None, "Partner email address"] = None,
        supplier_rank: Annotated[int, "Supplier rank"] = 1,
    ) -> dict[str, Any]:
        """Create a partner in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_partner(
                PartnerInput(
                    name=name,
                    vat=vat,
                    email=email,
                    supplier_rank=supplier_rank,
                )
            )
        )

    return create_partner


def _search_partners_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_partners(
        query: Annotated[str, "Partial customer name, email, tax ID, or VAT number"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search partners in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_partners(SearchInput(query=query, limit=limit)))

    return search_partners


def _search_products_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_products(
        query: Annotated[str, "Partial product name or SKU"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search products in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_products(SearchInput(query=query, limit=limit)))

    return search_products


def _search_journals_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_journals(
        query: Annotated[str, "Partial journal name or code"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search journals in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_journals(SearchInput(query=query, limit=limit)))

    return search_journals


def _search_taxes_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_taxes(
        query: Annotated[str, "Partial tax name, for example VAT 21"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search taxes in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_taxes(SearchInput(query=query, limit=limit)))

    return search_taxes


def _search_picking_types_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_picking_types(
        query: Annotated[str, "Partial picking type name or code"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search picking types in Odoo and return candidate IDs."""
        return await _dump_model(
            odoo.search_picking_types(SearchInput(query=query, limit=limit))
        )

    return search_picking_types


def _search_locations_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_locations(
        query: Annotated[str, "Partial stock location name"],
        limit: Annotated[int, "Maximum number of results"] = 10,
    ) -> dict[str, Any]:
        """Search stock locations in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_locations(SearchInput(query=query, limit=limit)))

    return search_locations


def _validate_invoice_draft_tool(odoo: OdooGateway) -> ToolCallable:
    async def validate_invoice_draft(
        partner_id: Annotated[int | None, "Customer partner ID"] = None,
        journal_id: Annotated[int | None, "Sales journal ID"] = None,
        move_type: Annotated[InvoiceMoveType, "Invoice move type"] = "out_invoice",
        line_count: Annotated[int, "Number of invoice lines"] = 0,
    ) -> dict[str, Any]:
        """Validate invoice prerequisites before trying to create it."""
        return await _dump_model(
            odoo.validate_invoice_draft(
                InvoiceValidationInput(
                    partner_id=partner_id,
                    journal_id=journal_id,
                    move_type=move_type,
                    line_count=line_count,
                )
            )
        )

    return validate_invoice_draft


def _validate_argentina_invoice_draft_tool(odoo: OdooGateway) -> ToolCallable:
    async def validate_argentina_invoice_draft(
        emitter_vat: Annotated[str | None, "Emitter tax ID or VAT number"] = None,
        emitter_taxpayer_type: Annotated[
            str | None,
            "Emitter taxpayer category such as registered taxpayer, simplified regime, or exempt",
        ] = None,
        point_of_sale: Annotated[int | None, "AFIP/ARCA point of sale"] = None,
        wsfe_service: Annotated[str, "Expected fiscal web service, usually wsfev1"] = "wsfev1",
        document_letter: Annotated[str | None, "Invoice document letter: A, B, or C"] = None,
        partner_name: Annotated[str | None, "Recipient name or legal name"] = None,
        partner_vat: Annotated[str | None, "Recipient tax ID or VAT number"] = None,
        partner_doc_type: Annotated[str | None, "Recipient document type"] = None,
        partner_taxpayer_type: Annotated[str | None, "Recipient taxpayer category"] = None,
        line_count: Annotated[int, "Number of invoice lines"] = 0,
        email_to: Annotated[str | None, "Recipient email address for invoice delivery"] = None,
    ) -> dict[str, Any]:
        """Validate Argentine electronic invoice prerequisites before issuing a document."""
        return await _dump_model(
            odoo.validate_argentina_invoice_draft(
                ArgentinaInvoiceValidationInput(
                    emitter_vat=emitter_vat,
                    emitter_taxpayer_type=emitter_taxpayer_type,
                    point_of_sale=point_of_sale,
                    wsfe_service=wsfe_service,
                    document_letter=document_letter,
                    partner_name=partner_name,
                    partner_vat=partner_vat,
                    partner_doc_type=partner_doc_type,
                    partner_taxpayer_type=partner_taxpayer_type,
                    line_count=line_count,
                    email_to=email_to,
                )
            )
        )

    return validate_argentina_invoice_draft


def _validate_delivery_draft_tool(odoo: OdooGateway) -> ToolCallable:
    async def validate_delivery_draft(
        partner_id: Annotated[int | None, "Customer partner ID"] = None,
        picking_type_id: Annotated[int | None, "Picking type ID"] = None,
        location_id: Annotated[int | None, "Source stock location ID"] = None,
        location_dest_id: Annotated[int | None, "Destination stock location ID"] = None,
        move_count: Annotated[int, "Number of stock moves"] = 0,
    ) -> dict[str, Any]:
        """Validate delivery prerequisites before trying to create it."""
        return await _dump_model(
            odoo.validate_delivery_draft(
                DeliveryValidationInput(
                    partner_id=partner_id,
                    picking_type_id=picking_type_id,
                    location_id=location_id,
                    location_dest_id=location_dest_id,
                    move_count=move_count,
                )
            )
        )

    return validate_delivery_draft


def _create_product_tool(odoo: OdooGateway) -> ToolCallable:
    async def create_product(
        name: Annotated[str, "Product commercial name"],
        default_code: Annotated[str | None, "Internal code or SKU"] = None,
        list_price: Annotated[float, "Sales price"] = 0.0,
        standard_price: Annotated[float | None, "Standard cost"] = None,
        description_sale: Annotated[str | None, "Sales description"] = None,
    ) -> dict[str, Any]:
        """Create a product in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_product(
                ProductInput(
                    name=name,
                    default_code=default_code,
                    list_price=list_price,
                    standard_price=standard_price,
                    description_sale=description_sale,
                )
            )
        )

    return create_product


def _create_invoice_tool(odoo: OdooGateway) -> ToolCallable:
    async def create_invoice(
        partner_id: Annotated[int, "Odoo partner or customer ID"],
        lines: Annotated[
            list[dict[str, Any]],
            "Invoice lines with product_id, quantity, price_unit, and optional name",
        ],
        move_type: Annotated[
            InvoiceMoveType,
            "Invoice move type, defaults to out_invoice",
        ] = "out_invoice",
        invoice_date: Annotated[str | None, "Invoice date in ISO format"] = None,
        narration: Annotated[str | None, "Internal notes or invoice narration"] = None,
    ) -> dict[str, Any]:
        """Create an invoice in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_invoice(
                InvoiceInput(
                    partner_id=partner_id,
                    move_type=move_type,
                    invoice_date=invoice_date,
                    narration=narration,
                    lines=[InvoiceLineInput.model_validate(line) for line in lines],
                )
            )
        )

    return create_invoice


def _create_delivery_tool(odoo: OdooGateway) -> ToolCallable:
    async def create_delivery(
        partner_id: Annotated[int, "Odoo partner or customer ID"],
        picking_type_id: Annotated[int, "Stock picking type ID"],
        location_id: Annotated[int, "Source stock location ID"],
        location_dest_id: Annotated[int, "Destination stock location ID"],
        moves: Annotated[
            list[dict[str, Any]],
            "Stock moves with product_id, quantity, and name",
        ],
        origin: Annotated[str | None, "Commercial origin for the delivery order"] = None,
        scheduled_date: Annotated[str | None, "Scheduled date in ISO format"] = None,
    ) -> dict[str, Any]:
        """Create a delivery order in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_delivery(
                DeliveryInput(
                    partner_id=partner_id,
                    picking_type_id=picking_type_id,
                    location_id=location_id,
                    location_dest_id=location_dest_id,
                    origin=origin,
                    scheduled_date=scheduled_date,
                    moves=[DeliveryMoveInput.model_validate(move) for move in moves],
                )
            )
        )

    return create_delivery


_ODOO_TOOL_SPECS: tuple[OdooToolSpec, ...] = (
    OdooToolSpec("create_partner", _create_partner_tool),
    OdooToolSpec("search_partners", _search_partners_tool),
    OdooToolSpec("search_products", _search_products_tool),
    OdooToolSpec("search_journals", _search_journals_tool),
    OdooToolSpec("search_taxes", _search_taxes_tool),
    OdooToolSpec("search_picking_types", _search_picking_types_tool),
    OdooToolSpec("search_locations", _search_locations_tool),
    OdooToolSpec("validate_invoice_draft", _validate_invoice_draft_tool),
    OdooToolSpec("validate_argentina_invoice_draft", _validate_argentina_invoice_draft_tool),
    OdooToolSpec("validate_delivery_draft", _validate_delivery_draft_tool),
    OdooToolSpec("create_product", _create_product_tool),
    OdooToolSpec("create_invoice", _create_invoice_tool),
    OdooToolSpec("create_delivery", _create_delivery_tool),
)


def build_odoo_tools(odoo: OdooGateway) -> list[Any]:
    return [spec.build(odoo) for spec in _ODOO_TOOL_SPECS]
