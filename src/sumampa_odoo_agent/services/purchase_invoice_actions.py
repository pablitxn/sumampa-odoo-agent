"""Deterministic business actions for the purchase invoice flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreatePartnerCommand,
    CreateProductCommand,
    InvoiceAttachment,
    OdooOperationResult,
    PurchaseInvoiceProposalResult,
)


class PurchaseInvoiceActionsGateway(Protocol):
    async def analyze_purchase_invoice(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult: ...

    async def apply_purchase_invoice_proposal(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult: ...

    async def create_partner(self, command: CreatePartnerCommand) -> OdooOperationResult: ...

    async def create_product(self, command: CreateProductCommand) -> OdooOperationResult: ...


@dataclass(slots=True)
class AnalyzePurchaseInvoiceInput:
    attachments: list[InvoiceAttachment]
    supplier_name: str | None
    supplier_vat: str | None
    markup_percentage: float


@dataclass(slots=True)
class ConfirmPurchaseInvoiceInput:
    supplier_id: int | None
    journal_id: int | None
    proposal: PurchaseInvoiceProposalResult


@dataclass(slots=True)
class ConfirmStockReceiptInput:
    supplier_id: int | None
    journal_id: int | None
    proposal: PurchaseInvoiceProposalResult
    picking_type_id: int | None
    location_id: int | None
    location_dest_id: int | None


@dataclass(slots=True)
class ConfirmPriceUpdatesInput:
    supplier_id: int | None
    journal_id: int | None
    proposal: PurchaseInvoiceProposalResult


@dataclass(slots=True)
class CreateMissingSupplierInput:
    name: str
    vat: str | None


@dataclass(slots=True)
class CreateMissingProductInput:
    name: str
    default_code: str | None
    list_price: float
    standard_price: float | None
    description_sale: str | None


class PurchaseInvoiceActionsUseCase:
    """Deterministic business actions behind the conversational invoice flow."""

    def __init__(self, odoo: PurchaseInvoiceActionsGateway) -> None:
        self._odoo = odoo

    async def analyze_purchase_invoice(
        self,
        request: AnalyzePurchaseInvoiceInput,
    ) -> PurchaseInvoiceProposalResult:
        return await self._odoo.analyze_purchase_invoice(
            AnalyzePurchaseInvoiceCommand(
                attachments=request.attachments,
                supplier_name=request.supplier_name,
                supplier_vat=request.supplier_vat,
                markup_percentage=request.markup_percentage,
            )
        )

    async def confirm_purchase_invoice(
        self,
        request: ConfirmPurchaseInvoiceInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._apply_purchase_invoice_proposal(
            supplier_id=request.supplier_id,
            journal_id=request.journal_id,
            proposal=request.proposal,
            create_vendor_bill=True,
            update_products=False,
            learn_resolutions=True,
            create_stock_receipt=False,
            picking_type_id=None,
            location_id=None,
            location_dest_id=None,
        )

    async def confirm_stock_receipt(
        self,
        request: ConfirmStockReceiptInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._apply_purchase_invoice_proposal(
            supplier_id=request.supplier_id,
            journal_id=request.journal_id,
            proposal=request.proposal,
            create_vendor_bill=False,
            update_products=False,
            learn_resolutions=False,
            create_stock_receipt=True,
            picking_type_id=request.picking_type_id,
            location_id=request.location_id,
            location_dest_id=request.location_dest_id,
        )

    async def confirm_price_updates(
        self,
        request: ConfirmPriceUpdatesInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._apply_purchase_invoice_proposal(
            supplier_id=request.supplier_id,
            journal_id=request.journal_id,
            proposal=request.proposal,
            create_vendor_bill=False,
            update_products=True,
            learn_resolutions=False,
            create_stock_receipt=False,
            picking_type_id=None,
            location_id=None,
            location_dest_id=None,
        )

    async def create_missing_supplier(
        self,
        request: CreateMissingSupplierInput,
    ) -> OdooOperationResult:
        return await self._odoo.create_partner(
            CreatePartnerCommand(
                name=request.name,
                vat=request.vat,
                supplier_rank=1,
            )
        )

    async def create_missing_product(
        self,
        request: CreateMissingProductInput,
    ) -> OdooOperationResult:
        return await self._odoo.create_product(
            CreateProductCommand(
                name=request.name,
                default_code=request.default_code,
                list_price=request.list_price,
                standard_price=request.standard_price,
                description_sale=request.description_sale,
            )
        )

    async def _apply_purchase_invoice_proposal(
        self,
        *,
        supplier_id: int | None,
        journal_id: int | None,
        proposal: PurchaseInvoiceProposalResult,
        create_vendor_bill: bool,
        update_products: bool,
        learn_resolutions: bool,
        create_stock_receipt: bool,
        picking_type_id: int | None,
        location_id: int | None,
        location_dest_id: int | None,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._odoo.apply_purchase_invoice_proposal(
            ApplyPurchaseInvoiceProposalCommand(
                supplier_id=supplier_id,
                journal_id=journal_id,
                create_vendor_bill=create_vendor_bill,
                update_products=update_products,
                learn_resolutions=learn_resolutions,
                create_stock_receipt=create_stock_receipt,
                picking_type_id=picking_type_id,
                location_id=location_id,
                location_dest_id=location_dest_id,
                proposal=proposal,
            )
        )
