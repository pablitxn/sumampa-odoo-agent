"""Odoo backends for dry-run and JSON-RPC modes."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from sumampa_odoo_agent.integrations.purchase_resolution_memory import (
    PurchaseResolutionMemoryStore,
)
from sumampa_odoo_agent.services.contracts import InvoiceExtractor
from sumampa_odoo_agent.services.message_specs import render_message
from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    DeliveryMoveInput,
    OdooMutationPlan,
    OdooOperationResult,
    OdooSearchHit,
    OdooSearchResult,
    OdooValidationResult,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
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
from sumampa_odoo_agent.services.use_cases import (
    ResolvePurchaseInvoiceEntitiesInput,
    ResolvePurchaseInvoiceEntitiesUseCase,
    normalize_invoice_date,
    normalize_partner_row,
    normalize_product_row,
    normalize_text,
    normalize_vat,
)

PURCHASE_INVOICE_RESOLUTION_USE_CASE = ResolvePurchaseInvoiceEntitiesUseCase()


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
    _stock_by_product_id: ClassVar[dict[int, float]] = {201: 40.0, 202: 8.0, 203: 15.0}
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

    def __init__(
        self,
        *,
        invoice_extractor: InvoiceExtractor | None = None,
        resolution_memory: PurchaseResolutionMemoryStore | None = None,
    ) -> None:
        if invoice_extractor is None:
            raise ValueError("DryRunOdooClient requires an explicit purchase invoice extractor.")
        self._invoice_extractor = invoice_extractor
        self._resolution_memory = resolution_memory
        self._partners = [dict(row) for row in type(self)._partners]  # type: ignore[misc]
        self._products = [dict(row) for row in type(self)._products]  # type: ignore[misc]
        self._stock_by_product_id = dict(type(self)._stock_by_product_id)  # type: ignore[misc]
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

    async def analyze_purchase_invoice(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult:
        extracted = await self._invoice_extractor.extract(command)
        partners = [dict(row) for row in self._partners]
        products = [dict(row) for row in self._products]
        if self._resolution_memory is not None:
            _apply_supplier_memory(
                partners=partners,
                hints=self._resolution_memory.supplier_hints(
                    supplier_name=extracted.supplier_name,
                    supplier_vat=command.supplier_vat or extracted.supplier_vat,
                ),
            )
            for raw_line in extracted.lines:
                _apply_product_memory(
                    products=products,
                    description=str(raw_line.description),
                    hints=self._resolution_memory.product_hints(
                        supplier_name=extracted.supplier_name,
                        supplier_vat=command.supplier_vat or extracted.supplier_vat,
                        description=str(raw_line.description),
                    ),
                )
        return _build_purchase_invoice_proposal(
            ResolvePurchaseInvoiceEntitiesInput(
                mode="dry-run",
                extracted=extracted,
                markup_percentage=command.markup_percentage,
                partners=partners,
                products=products,
                stock_by_product_id=self._stock_by_product_id,
                supplier_vat=command.supplier_vat,
            )
        )

    async def apply_purchase_invoice_proposal(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        blockers = _purchase_apply_blockers(command)
        warnings = _purchase_apply_warnings(command)
        operations = _purchase_apply_operations(command)
        if command.learn_resolutions and self._resolution_memory is not None:
            operations.extend(_memory_operations(self._resolution_memory.remember_proposal(command.proposal)))
        return ApplyPurchaseInvoiceProposalResult(
            mode="dry-run",
            applied=not blockers,
            operations=operations,
            warnings=warnings,
        )

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
            or needle in (str(row.get("default_code") or "").casefold())
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
            warnings.append(
                _odoo_validation_message("move_type_actual", move_type=query.move_type)
            )
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
        return OdooOperationResult(
            mode="dry-run",
            model="product.template",
            record_id=self._create_dry_run_product(payload),
            payload=payload,
        )

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        lines = [
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
        payload = command.model_dump(exclude_none=True, exclude={"lines"})
        payload["invoice_line_ids"] = lines
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

    def _create_dry_run_product(self, payload: dict[str, Any]) -> int:
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
        self._stock_by_product_id[record_id] = 0.0
        return record_id


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
        invoice_extractor: InvoiceExtractor | None = None,
        resolution_memory: PurchaseResolutionMemoryStore | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._uid: int | None = None
        if invoice_extractor is None:
            raise ValueError("OdooJsonRpcClient requires an explicit purchase invoice extractor.")
        self._invoice_extractor = invoice_extractor
        self._resolution_memory = resolution_memory

    async def analyze_purchase_invoice(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult:
        extracted = await self._invoice_extractor.extract(command)
        partner_rows = await self._purchase_partner_candidates(extracted, command)
        product_rows = await self._purchase_product_candidates(extracted)
        product_ids = [int(row["id"]) for row in product_rows if row.get("id") is not None]
        stock_rows = await self._execute_kw(
            "stock.quant",
            "search_read",
            [[("product_tmpl_id", "in", product_ids)]] if product_ids else [[]],
            {"fields": ["product_tmpl_id", "quantity"], "limit": 500},
        )
        stock_by_product_id: dict[int, float] = {}
        for row in stock_rows:
            product_value = _normalize_odoo_value(row.get("product_tmpl_id"))
            if isinstance(product_value, dict) and isinstance(product_value.get("id"), int):
                stock_by_product_id[int(product_value["id"])] = stock_by_product_id.get(
                    int(product_value["id"]), 0.0
                ) + float(row.get("quantity") or 0.0)

        return _build_purchase_invoice_proposal(
            ResolvePurchaseInvoiceEntitiesInput(
                mode="jsonrpc",
                extracted=extracted,
                markup_percentage=command.markup_percentage,
                partners=[normalize_partner_row(row) for row in partner_rows],
                products=[normalize_product_row(row) for row in product_rows],
                stock_by_product_id=stock_by_product_id,
                supplier_vat=command.supplier_vat,
            )
        )

    async def apply_purchase_invoice_proposal(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        blockers = _purchase_apply_blockers(command)
        warnings = _purchase_apply_warnings(command)
        operations: list[OdooMutationPlan] = []
        if not blockers and command.create_vendor_bill and command.supplier_id:
            duplicate_warning = await self._find_duplicate_vendor_bill(command)
            if duplicate_warning is not None:
                blockers.append(duplicate_warning)
                warnings.append(duplicate_warning)

        product_template_ids = sorted(
            {
                int(line.product_match.product_id)
                for line in command.proposal.lines
                if line.product_match.product_id is not None
            }
        )
        product_template_metadata = await self._product_template_metadata(product_template_ids)

        if blockers:
            return ApplyPurchaseInvoiceProposalResult(
                mode="jsonrpc",
                applied=False,
                operations=operations,
                warnings=warnings,
            )

        if command.update_products:
            for line in command.proposal.lines:
                product_id = line.product_match.product_id
                if not product_id:
                    continue
                payload = {
                    "standard_price": line.unit_price_net,
                    "list_price": line.suggested_sale_price,
                }
                await self._execute_kw("product.template", "write", [[product_id], payload])
                operations.append(
                    OdooMutationPlan(
                        action="write",
                        model="product.template",
                        record_id=product_id,
                        payload=payload,
                    )
                )

        if command.create_vendor_bill and command.supplier_id and command.journal_id:
            payload = _build_vendor_bill_payload(
                command,
                product_template_metadata=product_template_metadata,
            )
            record_id = await self._execute_kw("account.move", "create", [payload])
            operations.append(
                OdooMutationPlan(
                    action="create",
                    model="account.move",
                    record_id=int(record_id),
                    payload=payload,
                )
            )

        if (
            command.create_stock_receipt
            and command.picking_type_id
            and command.location_id
            and command.location_dest_id
        ):
            payload = _build_stock_receipt_payload(
                command,
                product_template_metadata=product_template_metadata,
            )
            record_id = await self._execute_kw("stock.picking", "create", [payload])
            operations.append(
                OdooMutationPlan(
                    action="create",
                    model="stock.picking",
                    record_id=int(record_id),
                    payload=payload,
                )
            )

        if command.learn_resolutions:
            if self._resolution_memory is not None:
                operations.extend(
                    _memory_operations(self._resolution_memory.remember_proposal(command.proposal))
                )
            if command.supplier_id is not None:
                supplierinfo_operations = await self._remember_supplierinfo_aliases(
                    proposal=command.proposal,
                    supplier_id=command.supplier_id,
                )
                operations.extend(supplierinfo_operations)

        return ApplyPurchaseInvoiceProposalResult(
            mode="jsonrpc",
            applied=not blockers,
            operations=operations,
            warnings=warnings,
        )

    async def _find_duplicate_vendor_bill(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> str | None:
        invoice_number = (command.proposal.invoice_number or "").strip()
        if not invoice_number:
            return None

        domain: list[tuple[str, str, Any]] = [
            ("move_type", "=", "in_invoice"),
            ("partner_id", "=", command.supplier_id),
            ("ref", "=", invoice_number),
        ]
        normalized_invoice_date = normalize_invoice_date(command.proposal.invoice_date)
        if normalized_invoice_date:
            domain.append(("invoice_date", "=", normalized_invoice_date))

        rows = await self._execute_kw(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": ["name", "ref", "invoice_date", "amount_total", "state"],
                "limit": 5,
            },
        )
        if not rows:
            return None

        expected_total = float(command.proposal.totals.total)
        for row in rows:
            amount_total = float(row.get("amount_total") or 0.0)
            if abs(amount_total - expected_total) <= 1.0:
                return _purchase_invoice_message(
                    "duplicate_vendor_bill_exact",
                    document_name=row.get("name") or row.get("ref") or "sin nombre",
                    invoice_date=row.get("invoice_date") or "sin fecha",
                    amount_total=f"{amount_total:.2f}",
                )

        first = rows[0]
        return _purchase_invoice_message(
            "duplicate_vendor_bill_by_reference",
            document_name=first.get("name") or first.get("ref") or "sin nombre",
        )

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
            {"fields": ["display_name", "default_code", "list_price", "standard_price"], "limit": query.limit},
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

    async def _purchase_partner_candidates(
        self,
        extracted: Any,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> list[dict[str, Any]]:
        candidate_rows: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        queries: list[str] = []
        for raw_query in (command.supplier_vat, extracted.supplier_vat):
            if not raw_query:
                continue
            queries.extend(_lookup_query_variants(str(raw_query), include_vat_normalized=True))
        for raw_query in (command.supplier_name, extracted.supplier_name):
            if not raw_query:
                continue
            queries.extend(_lookup_query_variants(str(raw_query)))

        for query in queries:
            if not query:
                continue
            rows = await self._execute_kw(
                "res.partner",
                "search_read",
                [
                    [
                        "|",
                        "|",
                        ("name", "ilike", query),
                        ("email", "ilike", query),
                        ("vat", "ilike", query),
                    ]
                ],
                {"fields": ["display_name", "vat", "email"], "limit": 5},
            )
            for row in rows:
                row_id = int(row["id"])
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                candidate_rows.append(row)

        if self._resolution_memory is not None:
            hints = self._resolution_memory.supplier_hints(
                supplier_name=extracted.supplier_name,
                supplier_vat=command.supplier_vat or extracted.supplier_vat,
            )
            missing_ids = [partner_id for partner_id in hints if partner_id not in seen_ids]
            if missing_ids:
                rows = await self._execute_kw(
                    "res.partner",
                    "search_read",
                    [[("id", "in", missing_ids)]],
                    {"fields": ["display_name", "vat", "email"], "limit": len(missing_ids)},
                )
                candidate_rows.extend(rows)
            _apply_supplier_memory(partners=candidate_rows, hints=hints)

        return candidate_rows

    async def _purchase_product_candidates(self, extracted: Any) -> list[dict[str, Any]]:
        candidate_rows: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        for raw_line in extracted.lines:
            for query in _lookup_query_variants(str(raw_line.description)):
                direct_rows = await self._execute_kw(
                    "product.template",
                    "search_read",
                    [
                        [
                            "|",
                            ("name", "ilike", query),
                            ("default_code", "ilike", query),
                        ]
                    ],
                    {
                        "fields": ["display_name", "default_code", "list_price", "standard_price"],
                        "limit": 10,
                    },
                )
                supplier_rows = await self._product_supplierinfo_candidates(query)
                for row in [*direct_rows, *supplier_rows]:
                    row_id = int(row["id"])
                    if row_id in seen_ids:
                        continue
                    seen_ids.add(row_id)
                    candidate_rows.append(row)

            if self._resolution_memory is None:
                continue
            hints = self._resolution_memory.product_hints(
                supplier_name=extracted.supplier_name,
                supplier_vat=extracted.supplier_vat,
                description=str(raw_line.description),
            )
            missing_ids = [product_id for product_id in hints if product_id not in seen_ids]
            if missing_ids:
                rows = await self._execute_kw(
                    "product.template",
                    "search_read",
                    [[("id", "in", missing_ids)]],
                    {"fields": ["display_name", "default_code", "list_price", "standard_price"], "limit": len(missing_ids)},
                )
                candidate_rows.extend(rows)
            _apply_product_memory(
                products=candidate_rows,
                description=str(raw_line.description),
                hints=hints,
            )

        return candidate_rows

    async def _product_supplierinfo_candidates(self, description: str) -> list[dict[str, Any]]:
        supplierinfo_rows = await self._execute_kw(
            "product.supplierinfo",
            "search_read",
            [
                [
                    "|",
                    ("product_name", "ilike", description),
                    ("product_code", "ilike", description),
                ]
            ],
            {
                "fields": ["product_tmpl_id", "product_name", "product_code"],
                "limit": 10,
            },
        )
        template_ids: list[int] = []
        aliases_by_template_id: dict[int, list[str]] = {}
        for row in supplierinfo_rows:
            product_tmpl_value = _normalize_odoo_value(row.get("product_tmpl_id"))
            if not isinstance(product_tmpl_value, dict):
                continue
            template_id = product_tmpl_value.get("id")
            if not isinstance(template_id, int):
                continue
            if template_id not in template_ids:
                template_ids.append(template_id)
            alias_parts = [
                str(row.get("product_name") or "").strip(),
                str(row.get("product_code") or "").strip(),
            ]
            aliases_by_template_id.setdefault(template_id, []).extend(
                [part for part in alias_parts if part]
            )

        if not template_ids:
            return []

        template_rows = await self._execute_kw(
            "product.template",
            "search_read",
            [[("id", "in", template_ids)]],
            {"fields": ["display_name", "default_code", "list_price", "standard_price"], "limit": len(template_ids)},
        )
        enriched_rows: list[dict[str, Any]] = []
        for row in template_rows:
            template_id = int(row["id"])
            enriched = dict(row)
            enriched["supplier_aliases"] = aliases_by_template_id.get(template_id, [])
            enriched_rows.append(enriched)
        return enriched_rows

    async def _remember_supplierinfo_aliases(
        self,
        *,
        proposal: PurchaseInvoiceProposalResult,
        supplier_id: int,
    ) -> list[OdooMutationPlan]:
        operations: list[OdooMutationPlan] = []
        for line in proposal.lines:
            product_id = line.product_resolution.selected_product_id
            if product_id is None:
                continue
            existing_ids = await self._execute_kw(
                "product.supplierinfo",
                "search",
                [
                    [
                        ("partner_id", "=", supplier_id),
                        ("product_tmpl_id", "=", product_id),
                        ("product_name", "=", line.description),
                    ]
                ],
                {"limit": 1},
            )
            if existing_ids:
                continue
            payload = {
                "partner_id": supplier_id,
                "product_tmpl_id": product_id,
                "product_name": line.description,
            }
            record_id = await self._execute_kw("product.supplierinfo", "create", [payload])
            operations.append(
                OdooMutationPlan(
                    action="create",
                    model="product.supplierinfo",
                    record_id=int(record_id),
                    payload=payload,
                )
            )
        return operations

    async def search_journals(self, query: SearchJournalsQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="account.journal",
            domain=[
                "|",
                ("name", "ilike", query.query),
                ("code", "ilike", query.query),
            ],
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
            domain=[
                "|",
                ("name", "ilike", query.query),
                ("code", "ilike", query.query),
            ],
            fields=["display_name", "code", "warehouse_id"],
            limit=query.limit,
        )

    async def search_locations(self, query: SearchLocationsQuery) -> OdooSearchResult:
        return await self._search_read_hits(
            model="stock.location",
            domain=[("name", "ilike", query.query)],
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
        return OdooValidationResult(
            mode="jsonrpc",
            operation="invoice",
            ok=not missing,
            missing_fields=missing,
            warnings=[],
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

        expected_letter = _expected_ar_document_letter(
            emitter_taxpayer_type=query.emitter_taxpayer_type,
            partner_taxpayer_type=query.partner_taxpayer_type,
        )
        warnings: list[str] = []
        if query.wsfe_service and query.wsfe_service.casefold() != "wsfev1":
            warnings.append(
                _odoo_validation_message(
                    "wsfe_service_actual",
                    wsfe_service=query.wsfe_service,
                )
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
        record_id = await self._execute_kw(
            "product.template",
            "create",
            [command.model_dump(exclude_none=True)],
        )
        return OdooOperationResult(
            mode="jsonrpc",
            model="product.template",
            record_id=int(record_id),
            payload=command.model_dump(exclude_none=True),
        )

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        product_template_ids = sorted({line.product_id for line in command.lines})
        metadata = await self._product_template_metadata(product_template_ids)
        payload = command.model_dump(exclude_none=True, exclude={"lines"})
        payload["invoice_line_ids"] = [
            (
                0,
                0,
                {
                    "product_id": (
                        metadata.get(line.product_id, {}).get("product_variant_id") or line.product_id
                    ),
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
        product_template_ids = sorted({move.product_id for move in command.moves})
        metadata = await self._product_template_metadata(product_template_ids)
        payload = command.model_dump(exclude_none=True)
        payload["move_ids"] = [
            (
                0,
                0,
                _delivery_move_payload(move=move, metadata=metadata.get(move.product_id, {})),
            )
            for move in command.moves
        ]
        payload.pop("moves", None)
        record_id = await self._execute_kw("stock.picking", "create", [payload])
        return OdooOperationResult(
            mode="jsonrpc",
            model="stock.picking",
            record_id=int(record_id),
            payload=payload,
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
            {
                "fields": ["product_variant_id", "uom_id"],
                "limit": len(template_ids),
            },
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


def _build_purchase_invoice_proposal(
    request: ResolvePurchaseInvoiceEntitiesInput,
) -> PurchaseInvoiceProposalResult:
    return PURCHASE_INVOICE_RESOLUTION_USE_CASE.run(request)


def _purchase_apply_blockers(command: ApplyPurchaseInvoiceProposalCommand) -> list[str]:
    blockers: list[str] = []
    if command.create_vendor_bill and not command.supplier_id:
        blockers.append(_purchase_invoice_message("blocker_missing_supplier_id"))
    if command.create_vendor_bill and not command.journal_id:
        blockers.append(_purchase_invoice_message("blocker_missing_journal_id"))
    if command.create_vendor_bill and any(
        line.product_match.product_id is None for line in command.proposal.lines
    ):
        blockers.append(_purchase_invoice_message("blocker_unresolved_lines_vendor_bill"))
    if command.create_stock_receipt and not (
        command.picking_type_id and command.location_id and command.location_dest_id
    ):
        blockers.append(_purchase_invoice_message("blocker_missing_stock_locations"))
    if command.create_stock_receipt and any(
        line.product_match.product_id is None for line in command.proposal.lines
    ):
        blockers.append(_purchase_invoice_message("blocker_unresolved_lines_stock_receipt"))
    return blockers


def _purchase_apply_warnings(command: ApplyPurchaseInvoiceProposalCommand) -> list[str]:
    warnings = list(command.proposal.warnings)
    warnings.extend(_purchase_apply_blockers(command))
    if command.update_products and any(
        line.product_match.product_id is None for line in command.proposal.lines
    ):
        warnings.append(_purchase_invoice_message("warning_unresolved_lines_product_updates"))
    if any(line.product_resolution.status == "new" for line in command.proposal.lines):
        warnings.append(
            _purchase_invoice_message("warning_new_products_require_guided_creation")
        )
    if (
        command.proposal.supplier_resolution is not None
        and command.proposal.supplier_resolution.status == "new"
    ):
        warnings.append(
            _purchase_invoice_message("warning_new_supplier_require_guided_creation")
        )
    return warnings


def _purchase_invoice_message(key: str, **context: object) -> str:
    return render_message("purchase_invoice.json", key, **context)


def _odoo_validation_message(key: str, **context: object) -> str:
    return render_message("odoo_validation.json", key, **context)


def _purchase_apply_operations(command: ApplyPurchaseInvoiceProposalCommand) -> list[OdooMutationPlan]:
    operations: list[OdooMutationPlan] = []
    if command.update_products:
        for line in command.proposal.lines:
            product_id = line.product_match.product_id
            if not product_id:
                continue
            operations.append(
                OdooMutationPlan(
                    action="write",
                    model="product.template",
                    record_id=product_id,
                    payload={
                        "standard_price": line.unit_price_net,
                        "list_price": line.suggested_sale_price,
                    },
                )
            )
    if command.create_vendor_bill:
        operations.append(
            OdooMutationPlan(
                action="create",
                model="account.move",
                payload=_build_vendor_bill_payload(command),
            )
        )
    if command.create_stock_receipt:
        operations.append(
            OdooMutationPlan(
                action="create",
                model="stock.picking",
                payload=_build_stock_receipt_payload(command),
            )
        )
    return operations


def _build_vendor_bill_payload(
    command: ApplyPurchaseInvoiceProposalCommand,
    *,
    product_template_metadata: dict[int, dict[str, int | None]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "move_type": "in_invoice",
        "partner_id": command.supplier_id,
        "journal_id": command.journal_id,
        "invoice_origin": command.proposal.invoice_number,
        "invoice_date": normalize_invoice_date(command.proposal.invoice_date),
        "ref": command.proposal.invoice_number,
        "invoice_line_ids": [],
    }
    for line in command.proposal.lines:
        template_id = line.product_match.product_id
        metadata = (
            product_template_metadata.get(template_id, {})
            if product_template_metadata is not None and template_id is not None
            else {}
        )
        product_variant_id = metadata.get("product_variant_id") or template_id
        payload["invoice_line_ids"].append(
            (
                0,
                0,
                {
                    "product_id": product_variant_id,
                    "name": line.description,
                    "quantity": line.quantity,
                    "price_unit": line.unit_price_gross,
                },
            )
        )
    return payload


def _build_stock_receipt_payload(
    command: ApplyPurchaseInvoiceProposalCommand,
    *,
    product_template_metadata: dict[int, dict[str, int | None]] | None = None,
) -> dict[str, Any]:
    return {
        "partner_id": command.supplier_id,
        "picking_type_id": command.picking_type_id,
        "location_id": command.location_id,
        "location_dest_id": command.location_dest_id,
        "origin": command.proposal.invoice_number,
        "move_ids": [
            (
                0,
                0,
                _stock_move_payload(
                    line=line,
                    product_template_metadata=product_template_metadata,
                ),
            )
            for line in command.proposal.lines
            if line.product_match.product_id is not None
        ],
    }


def _stock_move_payload(
    *,
    line: PurchaseInvoiceProposalLine,
    product_template_metadata: dict[int, dict[str, int | None]] | None = None,
) -> dict[str, Any]:
    template_id = line.product_match.product_id
    metadata = (
        product_template_metadata.get(template_id, {})
        if product_template_metadata is not None and template_id is not None
        else {}
    )
    product_variant_id = metadata.get("product_variant_id") or template_id
    payload: dict[str, Any] = {
        "product_id": product_variant_id,
        "product_uom_qty": line.quantity,
        "description_picking": line.description,
    }
    if metadata.get("uom_id") is not None:
        payload["product_uom"] = metadata["uom_id"]
    return payload


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


def _apply_supplier_memory(
    *,
    partners: list[dict[str, Any]],
    hints: dict[int, dict[str, list[str]]],
) -> None:
    for partner in partners:
        partner_id = int(partner["id"])
        hint = hints.get(partner_id)
        if hint is None:
            continue
        partner_aliases = list(partner.get("supplier_aliases") or [])
        partner_alias_vats = list(partner.get("supplier_alias_vats") or [])
        for alias in hint.get("names", []):
            if alias not in partner_aliases:
                partner_aliases.append(alias)
        for alias_vat in hint.get("vats", []):
            if alias_vat not in partner_alias_vats:
                partner_alias_vats.append(alias_vat)
        partner["supplier_aliases"] = partner_aliases
        partner["supplier_alias_vats"] = partner_alias_vats


def _apply_product_memory(
    *,
    products: list[dict[str, Any]],
    description: str,
    hints: dict[int, list[str]],
) -> None:
    for product in products:
        product_id = int(product["id"])
        aliases = list(product.get("supplier_aliases") or [])
        for alias in hints.get(product_id, []):
            if alias not in aliases:
                aliases.append(alias)
        if description not in aliases and product_id in hints:
            aliases.append(description)
        product["supplier_aliases"] = aliases


def _memory_operations(entries: list[dict[str, Any]]) -> list[OdooMutationPlan]:
    return [
        OdooMutationPlan(
            action=str(entry["action"]),
            model=str(entry["model"]),
            record_id=int(entry["record_id"]) if entry.get("record_id") is not None else None,
            payload=dict(entry.get("payload") or {}),
        )
        for entry in entries
    ]


def _lookup_query_variants(value: str, *, include_vat_normalized: bool = False) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in (
        value.strip(),
        normalize_text(value),
        normalize_vat(value) if include_vat_normalized else "",
    ):
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        variants.append(candidate)
    return variants



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
