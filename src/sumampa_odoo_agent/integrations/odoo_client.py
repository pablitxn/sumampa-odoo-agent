"""Odoo backends for dry-run and JSON-RPC modes."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from sumampa_odoo_agent.services.message_specs import render_message
from sumampa_odoo_agent.services.models.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    DeliveryMoveInput,
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

    _partners: ClassVar[list[dict[str, Any]]] = [
        {"id": 101, "display_name": "Consumidor Final", "vat": None, "email": None},
        {"id": 102, "display_name": "Sumampa SRL", "vat": "30-12345678-9", "email": "admin@sumampa.test"},
        {"id": 103, "display_name": "Juan Perez", "vat": "20-33444555-6", "email": "juan@example.com"},
    ]
    _products: ClassVar[list[dict[str, Any]]] = [
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
        self._partners = [dict(row) for row in type(self)._partners]  # type: ignore[misc]
        self._products = [dict(row) for row in type(self)._products]  # type: ignore[misc]
        self._next_partner_id = max((int(row["id"]) for row in self._partners), default=100) + 1
        self._next_product_id = max((int(row["id"]) for row in self._products), default=200) + 1

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
            hits=_filter_hits(
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
            hits=_filter_hits(
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
            hits=_filter_hits(
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
            hits=_filter_hits(
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
        missing = []
        if not query.partner_id:
            missing.append("partner_id")
        if not query.journal_id:
            missing.append("journal_id")
        if query.line_count <= 0:
            missing.append("lines")
        warnings = []
        if query.move_type != "out_invoice":
            warnings.append(_odoo_validation_message("move_type_actual", move_type=query.move_type))
        return OdooValidationResult(
            mode="dry-run",
            operation="invoice",
            ok=not missing,
            missing_fields=missing,
            warnings=warnings,
            suggested_actions=_invoice_actions(missing),
        )

    async def validate_argentina_invoice_draft(
        self,
        query: ValidateArgentinaInvoiceDraftQuery,
    ) -> OdooValidationResult:
        missing = []
        if not query.emitter_vat:
            missing.append("emitter_vat")
        if not query.emitter_taxpayer_type:
            missing.append("emitter_taxpayer_type")
        if not query.point_of_sale:
            missing.append("point_of_sale")
        if not query.partner_name:
            missing.append("partner_name")
        if query.line_count <= 0:
            missing.append("lines")

        warnings: list[str] = []
        if query.wsfe_service and query.wsfe_service.casefold() != "wsfev1":
            warnings.append(
                _odoo_validation_message(
                    "wsfe_service_actual",
                    wsfe_service=query.wsfe_service,
                )
            )

        expected_letter = _expected_ar_document_letter(
            emitter_taxpayer_type=query.emitter_taxpayer_type,
            partner_taxpayer_type=query.partner_taxpayer_type,
        )
        if expected_letter and query.document_letter and query.document_letter.upper() != expected_letter:
            warnings.append(
                _odoo_validation_message(
                    "document_letter_mismatch",
                    expected_letter=expected_letter,
                    document_letter=query.document_letter.upper(),
                )
            )
        if expected_letter and not query.document_letter:
            warnings.append(
                _odoo_validation_message(
                    "document_letter_missing",
                    expected_letter=expected_letter,
                )
            )
        if not query.partner_vat and not query.partner_doc_type:
            warnings.append(_odoo_validation_message("partner_tax_id_or_doc_type_missing"))
        if not query.email_to:
            warnings.append(_odoo_validation_message("email_to_missing"))

        return OdooValidationResult(
            mode="dry-run",
            operation="argentina_invoice",
            ok=not missing,
            missing_fields=missing,
            warnings=warnings,
            suggested_actions=_argentina_invoice_actions(missing, expected_letter),
        )

    async def validate_delivery_draft(
        self,
        query: ValidateDeliveryDraftQuery,
    ) -> OdooValidationResult:
        missing = []
        if not query.partner_id:
            missing.append("partner_id")
        if not query.picking_type_id:
            missing.append("picking_type_id")
        if not query.location_id:
            missing.append("location_id")
        if not query.location_dest_id:
            missing.append("location_dest_id")
        if query.move_count <= 0:
            missing.append("moves")
        return OdooValidationResult(
            mode="dry-run",
            operation="delivery",
            ok=not missing,
            missing_fields=missing,
            warnings=[],
            suggested_actions=_delivery_actions(missing),
        )

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
        payload = command.model_dump(exclude_none=True, exclude={"lines"})
        payload["invoice_line_ids"] = [
            (
                0,
                0,
                {
                    "product_id": line.product_id,
                    "quantity": line.quantity,
                    "price_unit": line.price_unit,
                    "name": line.name,
                },
            )
            for line in command.lines
        ]
        return OdooOperationResult(
            mode="dry-run",
            model="account.move",
            record_id=9101,
            payload=payload,
        )

    async def create_delivery(self, command: CreateDeliveryCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True)
        payload["move_ids"] = [
            {
                "product_id": move.product_id,
                "product_uom_qty": move.quantity,
                "name": move.name,
            }
            for move in command.moves
        ]
        payload.pop("moves", None)
        return OdooOperationResult(
            mode="dry-run",
            model="stock.picking",
            record_id=9201,
            payload=payload,
        )


class OdooJsonRpcClient:
    """Minimal JSON-RPC client for direct Odoo writes."""

    def __init__(
        self,
        *,
        base_url: str,
        database: str,
        username: str,
        password: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._uid: int | None = None

    async def search_partners(self, query: SearchPartnersQuery) -> OdooSearchResult:
        rows = await self._execute_kw(
            "res.partner",
            "search_read",
            [
                [
                    "|",
                    "|",
                    ("name", "ilike", query.query),
                    ("email", "ilike", query.query),
                    ("vat", "ilike", query.query),
                ]
            ],
            {"fields": ["display_name", "vat", "email"], "limit": query.limit},
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model="res.partner",
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row["display_name"]),
                    extra={"vat": row.get("vat"), "email": row.get("email")},
                )
                for row in rows
            ],
        )

    async def search_products(self, query: SearchProductsQuery) -> OdooSearchResult:
        rows = await self._execute_kw(
            "product.template",
            "search_read",
            [
                [
                    "|",
                    ("name", "ilike", query.query),
                    ("default_code", "ilike", query.query),
                ]
            ],
            {
                "fields": ["display_name", "default_code", "list_price", "standard_price"],
                "limit": query.limit,
            },
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model="product.template",
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row["display_name"]),
                    extra={
                        "default_code": row.get("default_code"),
                        "list_price": row.get("list_price"),
                        "standard_price": row.get("standard_price"),
                    },
                )
                for row in rows
            ],
        )

    async def search_journals(self, query: SearchJournalsQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="account.journal",
            domain=["|", ("name", "ilike", query.query), ("code", "ilike", query.query)],
            fields=["display_name", "code", "type"],
            limit=query.limit,
        )

    async def search_taxes(self, query: SearchTaxesQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="account.tax",
            domain=[("name", "ilike", query.query)],
            fields=["display_name", "amount", "type_tax_use"],
            limit=query.limit,
        )

    async def search_picking_types(self, query: SearchPickingTypesQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="stock.picking.type",
            domain=["|", ("name", "ilike", query.query), ("code", "ilike", query.query)],
            fields=["display_name", "code", "warehouse_id"],
            limit=query.limit,
        )

    async def search_locations(self, query: SearchLocationsQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="stock.location",
            domain=[("complete_name", "ilike", query.query)],
            fields=["display_name", "usage"],
            limit=query.limit,
        )

    async def validate_invoice_draft(
        self,
        query: ValidateInvoiceDraftQuery,
    ) -> OdooValidationResult:
        missing = []
        if not query.partner_id:
            missing.append("partner_id")
        if not query.journal_id:
            missing.append("journal_id")
        if query.line_count <= 0:
            missing.append("lines")
        warnings = []
        if query.move_type != "out_invoice":
            warnings.append(_odoo_validation_message("move_type_actual", move_type=query.move_type))
        return OdooValidationResult(
            mode="jsonrpc",
            operation="invoice",
            ok=not missing,
            missing_fields=missing,
            warnings=warnings,
            suggested_actions=_invoice_actions(missing),
        )

    async def validate_argentina_invoice_draft(
        self,
        query: ValidateArgentinaInvoiceDraftQuery,
    ) -> OdooValidationResult:
        missing = []
        if not query.emitter_vat:
            missing.append("emitter_vat")
        if not query.emitter_taxpayer_type:
            missing.append("emitter_taxpayer_type")
        if not query.point_of_sale:
            missing.append("point_of_sale")
        if not query.partner_name:
            missing.append("partner_name")
        if query.line_count <= 0:
            missing.append("lines")

        warnings: list[str] = []
        if query.wsfe_service and query.wsfe_service.casefold() != "wsfev1":
            warnings.append(
                _odoo_validation_message(
                    "wsfe_service_actual",
                    wsfe_service=query.wsfe_service,
                )
            )

        expected_letter = _expected_ar_document_letter(
            emitter_taxpayer_type=query.emitter_taxpayer_type,
            partner_taxpayer_type=query.partner_taxpayer_type,
        )
        if expected_letter and query.document_letter and query.document_letter.upper() != expected_letter:
            warnings.append(
                _odoo_validation_message(
                    "document_letter_mismatch",
                    expected_letter=expected_letter,
                    document_letter=query.document_letter.upper(),
                )
            )
        if expected_letter and not query.document_letter:
            warnings.append(
                _odoo_validation_message(
                    "document_letter_missing",
                    expected_letter=expected_letter,
                )
            )
        if not query.partner_vat and not query.partner_doc_type:
            warnings.append(_odoo_validation_message("partner_tax_id_or_doc_type_missing"))
        if not query.email_to:
            warnings.append(_odoo_validation_message("email_to_missing"))

        return OdooValidationResult(
            mode="jsonrpc",
            operation="argentina_invoice",
            ok=not missing,
            missing_fields=missing,
            warnings=warnings,
            suggested_actions=_argentina_invoice_actions(missing, expected_letter),
        )

    async def validate_delivery_draft(
        self,
        query: ValidateDeliveryDraftQuery,
    ) -> OdooValidationResult:
        missing = []
        if not query.partner_id:
            missing.append("partner_id")
        if not query.picking_type_id:
            missing.append("picking_type_id")
        if not query.location_id:
            missing.append("location_id")
        if not query.location_dest_id:
            missing.append("location_dest_id")
        if query.move_count <= 0:
            missing.append("moves")
        return OdooValidationResult(
            mode="jsonrpc",
            operation="delivery",
            ok=not missing,
            missing_fields=missing,
            warnings=[],
            suggested_actions=_delivery_actions(missing),
        )

    async def create_partner(self, command: CreatePartnerCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True)
        record_id = await self._execute_kw("res.partner", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="res.partner",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_product(self, command: CreateProductCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True)
        record_id = await self._execute_kw("product.template", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="product.template",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        payload = command.model_dump(exclude_none=True, exclude={"lines"})
        payload["invoice_line_ids"] = [
            (
                0,
                0,
                {
                    "product_id": line.product_id,
                    "quantity": line.quantity,
                    "price_unit": line.price_unit,
                    "name": line.name,
                },
            )
            for line in command.lines
        ]
        record_id = await self._execute_kw("account.move", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="account.move",
            record_id=int(record_id),
            payload=payload,
        )

    async def create_delivery(self, command: CreateDeliveryCommand) -> OdooOperationResult:
        metadata = await self._product_template_metadata([move.product_id for move in command.moves])
        payload = command.model_dump(exclude_none=True, exclude={"moves"})
        payload["move_ids"] = [
            (0, 0, _delivery_move_payload(move=move, metadata=metadata.get(move.product_id, {})))
            for move in command.moves
        ]
        record_id = await self._execute_kw("stock.picking", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="stock.picking",
            record_id=int(record_id),
            payload=payload,
        )

    async def _authenticate(self) -> int:
        if self._uid is not None:
            return self._uid

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "login",
                "args": [self._database, self._username, self._password],
            },
            "id": 1,
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(f"{self._base_url}/jsonrpc", json=payload)
            response.raise_for_status()
            body = response.json()
        uid = body.get("result")
        if not isinstance(uid, int) or uid <= 0:
            raise RuntimeError("Failed to authenticate against Odoo JSON-RPC")
        self._uid = uid
        return uid

    async def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = await self._authenticate()
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self._database,
                    uid,
                    self._password,
                    model,
                    method,
                    args,
                    kwargs or {},
                ],
            },
            "id": 1,
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(f"{self._base_url}/jsonrpc", json=payload)
            response.raise_for_status()
            body = response.json()
        if "error" in body:
            raise RuntimeError(str(body["error"]))
        return body["result"]

    async def _search_read_hits(
        self,
        *,
        model: str,
        domain: list[Any],
        fields: list[str],
        limit: int,
    ) -> OdooSearchResult:
        rows = await self._execute_kw(
            model,
            "search_read",
            [domain],
            {"fields": fields, "limit": limit},
        )
        return OdooSearchResult(
            mode="jsonrpc",
            model=model,
            hits=[
                OdooSearchHit(
                    id=int(row["id"]),
                    display_name=str(row.get("display_name") or row.get("name") or row["id"]),
                    extra={key: _normalize_odoo_value(row.get(key)) for key in fields if key != "display_name"},
                )
                for row in rows
            ],
        )

    async def _product_template_metadata(
        self,
        template_ids: list[int],
    ) -> dict[int, dict[str, int | None]]:
        if not template_ids:
            return {}
        rows = await self._execute_kw(
            "product.template",
            "search_read",
            [[("id", "in", template_ids)]],
            {"fields": ["product_variant_id", "uom_id"], "limit": len(template_ids)},
        )
        metadata: dict[int, dict[str, int | None]] = {}
        for row in rows:
            template_id = int(row["id"])
            product_variant = _normalize_odoo_value(row.get("product_variant_id"))
            uom = _normalize_odoo_value(row.get("uom_id"))
            metadata[template_id] = {
                "product_variant_id": (
                    int(product_variant["id"])
                    if isinstance(product_variant, dict) and isinstance(product_variant.get("id"), int)
                    else None
                ),
                "uom_id": (
                    int(uom["id"])
                    if isinstance(uom, dict) and isinstance(uom.get("id"), int)
                    else None
                ),
            }
        return metadata


def _filter_hits(
    rows: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    extra_keys: tuple[str, ...],
) -> list[OdooSearchHit]:
    needle = query.casefold()
    hits: list[OdooSearchHit] = []
    for row in rows:
        searchable = [str(row.get("display_name", "")), *[str(row.get(key, "")) for key in extra_keys]]
        if not any(needle in value.casefold() for value in searchable):
            continue
        hits.append(
            OdooSearchHit(
                id=int(row["id"]),
                display_name=str(row["display_name"]),
                extra={key: row.get(key) for key in extra_keys},
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _delivery_move_payload(
    *,
    move: DeliveryMoveInput,
    metadata: dict[str, int | None],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": metadata.get("product_variant_id") or move.product_id,
        "product_uom_qty": move.quantity,
        "name": move.name or f"Move {move.product_id}",
    }
    if metadata.get("uom_id") is not None:
        payload["product_uom"] = metadata["uom_id"]
    return payload


def _normalize_odoo_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
        return {"id": value[0], "name": value[1]}
    return value


def _odoo_validation_message(key: str, **context: object) -> str:
    return render_message("odoo_validation.json", key, **context)


def _invoice_actions(missing: list[str]) -> list[str]:
    actions = []
    if "partner_id" in missing:
        actions.append("Buscar el partner con search_partners antes de facturar.")
    if "journal_id" in missing:
        actions.append("Resolver el diario con search_journals antes de facturar.")
    if "lines" in missing:
        actions.append("Agregar al menos una linea de factura valida.")
    return actions


def _delivery_actions(missing: list[str]) -> list[str]:
    actions = []
    if "partner_id" in missing:
        actions.append("Buscar el cliente con search_partners.")
    if "picking_type_id" in missing:
        actions.append("Resolver el tipo de picking con search_picking_types.")
    if "location_id" in missing or "location_dest_id" in missing:
        actions.append("Resolver ubicaciones con search_locations antes de crear el remito.")
    if "moves" in missing:
        actions.append("Agregar al menos un movimiento de stock.")
    return actions


def _argentina_invoice_actions(missing: list[str], expected_letter: str | None) -> list[str]:
    actions = []
    if "emitter_vat" in missing:
        actions.append("Completar el CUIT del emisor en la company.")
    if "emitter_taxpayer_type" in missing:
        actions.append("Definir la responsabilidad fiscal ARCA/AFIP del emisor.")
    if "point_of_sale" in missing:
        actions.append("Definir un punto de venta exclusivo para WSFE.")
    if "partner_name" in missing:
        actions.append("Completar nombre o razon social del receptor.")
    if "lines" in missing:
        actions.append("Agregar al menos una linea de factura.")
    if expected_letter:
        actions.append(f"Usar letra de comprobante {expected_letter} salvo excepcion fiscal real.")
    actions.append("Verificar que el web service habilitado sea wsfev1.")
    return actions


def _expected_ar_document_letter(
    *,
    emitter_taxpayer_type: str | None,
    partner_taxpayer_type: str | None,
) -> str | None:
    emitter = (emitter_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    partner = (partner_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    if not emitter:
        return None
    if "monotrib" in emitter:
        return "C"
    if "responsable inscripto" in emitter or emitter == "ri":
        if "responsable inscripto" in partner or partner == "ri":
            return "A"
        if partner:
            return "B"
        return None
    return None
