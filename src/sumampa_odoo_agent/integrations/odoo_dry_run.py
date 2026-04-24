"""Dry-run Odoo gateway."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, ClassVar

from sumampa_odoo_agent.integrations.odoo_common import (
    delivery_payload,
    filter_hits,
    invoice_payload,
    validate_argentina_invoice_draft,
    validate_delivery_draft,
    validate_invoice_draft,
)
from sumampa_odoo_agent.services.models.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    OdooOperationResult,
    OdooSearchHit,
    OdooSearchResult,
    OdooValidationResult,
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


class DryRunOdooClient:
    """Safe default client that returns the payload it would send to Odoo."""

    _seed_partners: ClassVar[list[dict[str, Any]]] = [
        {"id": 101, "display_name": "Consumidor Final", "vat": None, "email": None},
        {
            "id": 102,
            "display_name": "Sumampa SRL",
            "vat": "30-12345678-9",
            "email": "admin@sumampa.test",
        },
        {
            "id": 103,
            "display_name": "Juan Perez",
            "vat": "20-33444555-6",
            "email": "juan@example.com",
        },
    ]
    _seed_products: ClassVar[list[dict[str, Any]]] = [
        {
            "id": 201,
            "display_name": "Bombilla inox",
            "default_code": "BOMB-INOX",
            "list_price": 12.5,
            "standard_price": 7.8,
        },
        {
            "id": 202,
            "display_name": "Mate camionero",
            "default_code": "MATE-CAM",
            "list_price": 22.0,
            "standard_price": 14.2,
        },
        {
            "id": 203,
            "display_name": "Yerba seleccion",
            "default_code": "YERBA-SEL",
            "list_price": 8.75,
            "standard_price": 5.6,
        },
    ]
    _journals: ClassVar[list[dict[str, Any]]] = [
        {"id": 301, "display_name": "Ventas AR", "code": "VTA", "type": "sale"},
        {"id": 302, "display_name": "Facturas Exportacion", "code": "EXP", "type": "sale"},
    ]
    _taxes: ClassVar[list[dict[str, Any]]] = [
        {"id": 401, "display_name": "IVA 21%", "amount": 21.0, "type_tax_use": "sale"},
        {"id": 402, "display_name": "IVA 10.5%", "amount": 10.5, "type_tax_use": "sale"},
    ]
    _picking_types: ClassVar[list[dict[str, Any]]] = [
        {"id": 501, "display_name": "Entregas", "code": "outgoing", "warehouse": "WH"},
        {"id": 502, "display_name": "Recepciones", "code": "incoming", "warehouse": "WH"},
    ]
    _locations: ClassVar[list[dict[str, Any]]] = [
        {"id": 601, "display_name": "WH/Stock", "usage": "internal"},
        {"id": 602, "display_name": "Clientes", "usage": "customer"},
        {"id": 603, "display_name": "WH/Output", "usage": "internal"},
    ]

    def __init__(self) -> None:
        self._partners = deepcopy(type(self)._seed_partners)
        self._products = deepcopy(type(self)._seed_products)
        self._next_partner_id = max((int(row["id"]) for row in self._partners), default=100) + 1
        self._next_product_id = max((int(row["id"]) for row in self._products), default=200) + 1

    async def aclose(self) -> None:
        return None

    async def search_partners(self, query: SearchPartnersQuery) -> OdooSearchResult:
        needle = query.query.casefold()
        hits = [
            OdooSearchHit(
                id=row["id"],
                display_name=row["display_name"],
                extra={"vat": row["vat"], "email": row["email"]},
            )
            for row in self._partners
            if needle in row["display_name"].casefold()
            or (row["email"] and needle in row["email"].casefold())
            or (row["vat"] and needle in row["vat"].casefold())
        ][: query.limit]
        return OdooSearchResult(mode="dry-run", model="res.partner", hits=hits)

    async def search_products(self, query: SearchProductsQuery) -> OdooSearchResult:
        needle = query.query.casefold()
        hits = [
            OdooSearchHit(
                id=row["id"],
                display_name=row["display_name"],
                extra={
                    "default_code": row.get("default_code"),
                    "list_price": row.get("list_price"),
                    "standard_price": row.get("standard_price"),
                },
            )
            for row in self._products
            if needle in row["display_name"].casefold()
            or needle in str(row.get("default_code") or "").casefold()
        ][: query.limit]
        return OdooSearchResult(mode="dry-run", model="product.template", hits=hits)

    async def search_journals(self, query: SearchJournalsQuery) -> OdooSearchResult:
        return OdooSearchResult(
            mode="dry-run",
            model="account.journal",
            hits=filter_hits(
                self._journals,
                query=query.query,
                limit=query.limit,
                extra_keys=("code", "type"),
            ),
        )

    async def search_taxes(self, query: SearchTaxesQuery) -> OdooSearchResult:
        return OdooSearchResult(
            mode="dry-run",
            model="account.tax",
            hits=filter_hits(
                self._taxes,
                query=query.query,
                limit=query.limit,
                extra_keys=("amount", "type_tax_use"),
            ),
        )

    async def search_picking_types(self, query: SearchPickingTypesQuery) -> OdooSearchResult:
        return OdooSearchResult(
            mode="dry-run",
            model="stock.picking.type",
            hits=filter_hits(
                self._picking_types,
                query=query.query,
                limit=query.limit,
                extra_keys=("code", "warehouse"),
            ),
        )

    async def search_locations(self, query: SearchLocationsQuery) -> OdooSearchResult:
        return OdooSearchResult(
            mode="dry-run",
            model="stock.location",
            hits=filter_hits(
                self._locations,
                query=query.query,
                limit=query.limit,
                extra_keys=("usage",),
            ),
        )

    async def validate_invoice_draft(
        self,
        query: ValidateInvoiceDraftQuery,
    ) -> OdooValidationResult:
        return validate_invoice_draft(mode="dry-run", query=query)

    async def validate_argentina_invoice_draft(
        self,
        query: ValidateArgentinaInvoiceDraftQuery,
    ) -> OdooValidationResult:
        return validate_argentina_invoice_draft(mode="dry-run", query=query)

    async def validate_delivery_draft(
        self,
        query: ValidateDeliveryDraftQuery,
    ) -> OdooValidationResult:
        return validate_delivery_draft(mode="dry-run", query=query)

    async def create_partner(self, command: CreatePartnerCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True)
        payload.setdefault("vat", None)
        payload.setdefault("email", None)
        record_id = self._next_partner_id
        self._next_partner_id += 1
        self._partners.append(
            {
                "id": record_id,
                "display_name": payload["name"],
                "vat": payload.get("vat"),
                "email": payload.get("email"),
                "supplier_rank": payload.get("supplier_rank", 1),
            }
        )
        return OdooOperationResult(
            mode="dry-run",
            model="res.partner",
            record_id=record_id,
            payload=payload,
        )

    async def create_product(self, command: CreateProductCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True)
        payload.setdefault("default_code", None)
        payload.setdefault("standard_price", 0.0)
        record_id = self._next_product_id
        self._next_product_id += 1
        self._products.append(
            {
                "id": record_id,
                "display_name": payload["name"],
                "default_code": payload.get("default_code"),
                "list_price": float(payload.get("list_price") or 0.0),
                "standard_price": float(payload.get("standard_price") or 0.0),
            }
        )
        return OdooOperationResult(
            mode="dry-run",
            model="product.template",
            record_id=record_id,
            payload=payload,
        )

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        payload = invoice_payload(command)
        return OdooOperationResult(
            mode="dry-run",
            model="account.move",
            record_id=9101,
            payload=payload,
        )

    async def create_delivery(self, command: CreateDeliveryCommand) -> OdooOperationResult:
        payload = delivery_payload(command)
        return OdooOperationResult(
            mode="dry-run",
            model="stock.picking",
            record_id=9201,
            payload=payload,
        )
