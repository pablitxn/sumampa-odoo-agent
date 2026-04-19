"""Application request models for Odoo operations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PartnerInput(BaseModel):
    name: str = Field(min_length=1)
    vat: str | None = None
    email: str | None = None
    supplier_rank: int = Field(default=1, ge=0)


class CreatePartnerCommand(PartnerInput):
    pass


class ProductInput(BaseModel):
    name: str = Field(min_length=1)
    default_code: str | None = None
    list_price: float = Field(default=0.0, ge=0)
    standard_price: float | None = Field(default=None, ge=0)
    description_sale: str | None = None


class CreateProductCommand(ProductInput):
    pass


class InvoiceLineInput(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    price_unit: float = Field(ge=0)
    name: str | None = None


class CreateInvoiceCommand(BaseModel):
    partner_id: int
    move_type: str = Field(default="out_invoice")
    invoice_date: str | None = None
    lines: list[InvoiceLineInput] = Field(min_length=1)
    narration: str | None = None


class DeliveryMoveInput(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    name: str | None = None


class CreateDeliveryCommand(BaseModel):
    partner_id: int
    picking_type_id: int
    location_id: int
    location_dest_id: int
    origin: str | None = None
    moves: list[DeliveryMoveInput] = Field(min_length=1)
    scheduled_date: str | None = None


class SearchPartnersQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchProductsQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchJournalsQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchTaxesQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchPickingTypesQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class SearchLocationsQuery(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class OdooSearchHit(BaseModel):
    id: int
    display_name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class OdooSearchResult(BaseModel):
    mode: str
    model: str
    hits: list[OdooSearchHit]


class ValidateInvoiceDraftQuery(BaseModel):
    partner_id: int | None = None
    journal_id: int | None = None
    move_type: str = Field(default="out_invoice")
    line_count: int = Field(default=0, ge=0)


class ValidateDeliveryDraftQuery(BaseModel):
    partner_id: int | None = None
    picking_type_id: int | None = None
    location_id: int | None = None
    location_dest_id: int | None = None
    move_count: int = Field(default=0, ge=0)


class ValidateArgentinaInvoiceDraftQuery(BaseModel):
    emitter_vat: str | None = None
    emitter_taxpayer_type: str | None = None
    point_of_sale: int | None = None
    wsfe_service: str | None = "wsfev1"
    document_letter: str | None = None
    partner_name: str | None = None
    partner_vat: str | None = None
    partner_doc_type: str | None = None
    partner_taxpayer_type: str | None = None
    line_count: int = Field(default=0, ge=0)
    email_to: str | None = None


class AnalyzePurchaseInvoiceCommand(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    image_bytes: bytes = Field(min_length=1)
    supplier_name: str | None = None
    supplier_vat: str | None = None
    markup_percentage: float = Field(default=30.0, ge=0)


class ExtractedPurchaseInvoiceLine(BaseModel):
    description: str
    quantity: float = Field(gt=0)
    unit_price_gross: float = Field(ge=0)
    vat_rate: float = Field(ge=0)


class ExtractedPurchaseInvoiceDocument(BaseModel):
    supplier_name: str | None = None
    supplier_vat: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    document_type: str | None = None
    currency: str = "ARS"
    subtotal_untaxed: float | None = Field(default=None, ge=0)
    total_vat: float | None = Field(default=None, ge=0)
    total_amount: float | None = Field(default=None, ge=0)
    lines: list[ExtractedPurchaseInvoiceLine] = Field(default_factory=list, min_length=1)


class PurchaseInvoiceProductMatch(BaseModel):
    product_id: int | None = None
    display_name: str | None = None
    default_code: str | None = None
    current_sale_price: float | None = None
    current_cost: float | None = None
    current_stock: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PurchaseInvoiceSupplierCandidate(BaseModel):
    partner_id: int
    display_name: str
    vat: str | None = None
    email: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None


class PurchaseInvoiceSupplierResolution(BaseModel):
    status: Literal["exact", "candidate", "missing", "manual", "new"]
    selected_partner_id: int | None = None
    selected_display_name: str | None = None
    selected_vat: str | None = None
    extracted_name: str | None = None
    extracted_vat: str | None = None
    candidates: list[PurchaseInvoiceSupplierCandidate] = Field(default_factory=list)


class PurchaseInvoiceProductCandidate(BaseModel):
    product_id: int
    display_name: str
    default_code: str | None = None
    current_sale_price: float | None = None
    current_cost: float | None = None
    current_stock: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None


class PurchaseInvoiceProductResolution(BaseModel):
    status: Literal["exact", "candidate", "missing", "manual", "new"]
    selected_product_id: int | None = None
    selected_display_name: str | None = None
    selected_default_code: str | None = None
    candidates: list[PurchaseInvoiceProductCandidate] = Field(default_factory=list)


class PurchaseInvoiceProposalLine(BaseModel):
    line_number: int = Field(ge=1)
    description: str
    quantity: float = Field(gt=0)
    unit_price_gross: float = Field(ge=0)
    vat_rate: float = Field(ge=0)
    unit_price_net: float = Field(ge=0)
    subtotal_net: float = Field(ge=0)
    subtotal_vat: float = Field(ge=0)
    subtotal_gross: float = Field(ge=0)
    product_match: PurchaseInvoiceProductMatch = Field(default_factory=PurchaseInvoiceProductMatch)
    product_resolution: PurchaseInvoiceProductResolution = Field(
        default_factory=lambda: PurchaseInvoiceProductResolution(status="missing")
    )
    suggested_sale_price: float = Field(ge=0)
    suggested_markup_percentage: float = Field(ge=0)
    stock_after_update: float | None = None


class PurchaseInvoiceProposalTotals(BaseModel):
    untaxed: float = Field(ge=0)
    vat: float = Field(ge=0)
    total: float = Field(ge=0)


class PurchaseInvoiceProposalResult(BaseModel):
    mode: str
    supplier_name: str | None = None
    supplier_vat: str | None = None
    supplier_resolution: PurchaseInvoiceSupplierResolution | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    document_type: str | None = None
    currency: str = "ARS"
    extracted_totals: PurchaseInvoiceProposalTotals | None = None
    markup_percentage: float = Field(ge=0)
    lines: list[PurchaseInvoiceProposalLine] = Field(default_factory=list)
    totals: PurchaseInvoiceProposalTotals
    needs_user_resolution: bool = False
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class OdooMutationPlan(BaseModel):
    action: str
    model: str
    record_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplyPurchaseInvoiceProposalCommand(BaseModel):
    supplier_id: int | None = None
    journal_id: int | None = None
    create_vendor_bill: bool = True
    update_products: bool = True
    learn_resolutions: bool = False
    create_stock_receipt: bool = False
    picking_type_id: int | None = None
    location_id: int | None = None
    location_dest_id: int | None = None
    proposal: PurchaseInvoiceProposalResult


class ApplyPurchaseInvoiceProposalResult(BaseModel):
    mode: str
    applied: bool
    operations: list[OdooMutationPlan] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OdooValidationResult(BaseModel):
    mode: str
    operation: str
    ok: bool
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class OdooOperationResult(BaseModel):
    mode: str
    model: str
    record_id: int | None = None
    payload: dict[str, Any]
