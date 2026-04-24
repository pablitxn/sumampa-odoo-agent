"""Agent tools backed by Odoo gateways."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.services.models.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    DeliveryMoveInput,
    InvoiceLineInput,
    InvoiceMoveType,
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
        name: Annotated[str, "Nombre del partner"],
        vat: Annotated[str | None, "CUIT/CUIL del partner"] = None,
        email: Annotated[str | None, "Email del partner"] = None,
        supplier_rank: Annotated[int, "Rank de proveedor"] = 1,
    ) -> dict[str, Any]:
        """Create a partner in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_partner(
                CreatePartnerCommand(
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
        query: Annotated[str, "Nombre, email o CUIT parcial del cliente"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search partners in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_partners(SearchPartnersQuery(query=query, limit=limit)))

    return search_partners


def _search_products_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_products(
        query: Annotated[str, "Nombre o SKU parcial del producto"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search products in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_products(SearchProductsQuery(query=query, limit=limit)))

    return search_products


def _search_journals_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_journals(
        query: Annotated[str, "Nombre o codigo parcial del diario"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search journals in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_journals(SearchJournalsQuery(query=query, limit=limit)))

    return search_journals


def _search_taxes_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_taxes(
        query: Annotated[str, "Nombre parcial del impuesto, por ejemplo IVA 21"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search taxes in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_taxes(SearchTaxesQuery(query=query, limit=limit)))

    return search_taxes


def _search_picking_types_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_picking_types(
        query: Annotated[str, "Nombre o codigo parcial del tipo de picking"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search picking types in Odoo and return candidate IDs."""
        return await _dump_model(
            odoo.search_picking_types(SearchPickingTypesQuery(query=query, limit=limit))
        )

    return search_picking_types


def _search_locations_tool(odoo: OdooGateway) -> ToolCallable:
    async def search_locations(
        query: Annotated[str, "Nombre parcial de la ubicacion"],
        limit: Annotated[int, "Cantidad maxima de resultados"] = 10,
    ) -> dict[str, Any]:
        """Search stock locations in Odoo and return candidate IDs."""
        return await _dump_model(odoo.search_locations(SearchLocationsQuery(query=query, limit=limit)))

    return search_locations


def _validate_invoice_draft_tool(odoo: OdooGateway) -> ToolCallable:
    async def validate_invoice_draft(
        partner_id: Annotated[int | None, "ID del cliente"] = None,
        journal_id: Annotated[int | None, "ID del diario de ventas"] = None,
        move_type: Annotated[InvoiceMoveType, "Tipo de comprobante"] = "out_invoice",
        line_count: Annotated[int, "Cantidad de lineas de factura"] = 0,
    ) -> dict[str, Any]:
        """Validate invoice prerequisites before trying to create it."""
        return await _dump_model(
            odoo.validate_invoice_draft(
                ValidateInvoiceDraftQuery(
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
        emitter_vat: Annotated[str | None, "CUIT del emisor"] = None,
        emitter_taxpayer_type: Annotated[
            str | None,
            "Responsable inscripto, monotributo, exento, etc.",
        ] = None,
        point_of_sale: Annotated[int | None, "Punto de venta AFIP/ARCA"] = None,
        wsfe_service: Annotated[str, "Servicio fiscal esperado, normalmente wsfev1"] = "wsfev1",
        document_letter: Annotated[str | None, "Letra del comprobante: A, B o C"] = None,
        partner_name: Annotated[str | None, "Nombre del receptor"] = None,
        partner_vat: Annotated[str | None, "CUIT o identificacion fiscal del receptor"] = None,
        partner_doc_type: Annotated[str | None, "Tipo de documento del receptor"] = None,
        partner_taxpayer_type: Annotated[str | None, "Condicion fiscal del receptor"] = None,
        line_count: Annotated[int, "Cantidad de lineas de factura"] = 0,
        email_to: Annotated[str | None, "Email para envio del comprobante"] = None,
    ) -> dict[str, Any]:
        """Validate Argentine electronic invoice prerequisites before issuing a document."""
        return await _dump_model(
            odoo.validate_argentina_invoice_draft(
                ValidateArgentinaInvoiceDraftQuery(
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
        partner_id: Annotated[int | None, "ID del cliente"] = None,
        picking_type_id: Annotated[int | None, "ID del tipo de picking"] = None,
        location_id: Annotated[int | None, "ID de ubicacion origen"] = None,
        location_dest_id: Annotated[int | None, "ID de ubicacion destino"] = None,
        move_count: Annotated[int, "Cantidad de movimientos"] = 0,
    ) -> dict[str, Any]:
        """Validate delivery prerequisites before trying to create it."""
        return await _dump_model(
            odoo.validate_delivery_draft(
                ValidateDeliveryDraftQuery(
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
        name: Annotated[str, "Nombre comercial del producto"],
        default_code: Annotated[str | None, "Codigo interno o SKU"] = None,
        list_price: Annotated[float, "Precio de venta"] = 0.0,
        standard_price: Annotated[float | None, "Costo estandar"] = None,
        description_sale: Annotated[str | None, "Descripcion para ventas"] = None,
    ) -> dict[str, Any]:
        """Create a product in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_product(
                CreateProductCommand(
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
        partner_id: Annotated[int, "ID del partner o cliente en Odoo"],
        lines: Annotated[
            list[dict[str, Any]],
            "Lineas con product_id, quantity, price_unit y name opcional",
        ],
        move_type: Annotated[
            InvoiceMoveType,
            "Tipo de comprobante, por defecto out_invoice",
        ] = "out_invoice",
        invoice_date: Annotated[str | None, "Fecha ISO de factura"] = None,
        narration: Annotated[str | None, "Notas internas o leyenda"] = None,
    ) -> dict[str, Any]:
        """Create an invoice in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_invoice(
                CreateInvoiceCommand(
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
        partner_id: Annotated[int, "ID del partner o cliente en Odoo"],
        picking_type_id: Annotated[int, "Tipo de operacion de stock"],
        location_id: Annotated[int, "Ubicacion origen"],
        location_dest_id: Annotated[int, "Ubicacion destino"],
        moves: Annotated[
            list[dict[str, Any]],
            "Movimientos con product_id, quantity y name opcional",
        ],
        origin: Annotated[str | None, "Origen comercial del remito"] = None,
        scheduled_date: Annotated[str | None, "Fecha programada ISO"] = None,
    ) -> dict[str, Any]:
        """Create a delivery order in Odoo and return the resulting payload."""
        return await _dump_model(
            odoo.create_delivery(
                CreateDeliveryCommand(
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


def _tool_names(*, include_odoo: bool) -> list[str]:
    names = ["explain_capabilities"]
    if include_odoo:
        names.extend(spec.name for spec in _ODOO_TOOL_SPECS)
    return names


def build_agent_tools(*, odoo: OdooGateway | None) -> list[Any]:
    async def explain_capabilities() -> str:
        """Explain what this Sumampa Odoo agent can currently do."""
        names = ", ".join(_tool_names(include_odoo=odoo is not None))
        return (
            "Puedo explicar la POC y, si el backend Odoo esta habilitado, ejecutar estas tools: "
            f"{names}."
        )

    tools: list[Any] = [explain_capabilities]
    if odoo is None:
        return tools

    tools.extend(spec.build(odoo) for spec in _ODOO_TOOL_SPECS)
    return tools
