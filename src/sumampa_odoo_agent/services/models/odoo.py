"""Service models for Odoo operations."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

OdooIntegrationMode: TypeAlias = Literal["dry-run", "jsonrpc"]
OdooModelName: TypeAlias = Literal[
    "res.partner",
    "product.template",
    "account.move",
    "account.journal",
    "account.tax",
    "stock.picking.type",
    "stock.location",
    "stock.picking",
]
InvoiceMoveType: TypeAlias = Literal["out_invoice", "out_refund", "in_invoice", "in_refund", "entry"]
OdooValidationOperation: TypeAlias = Literal["invoice", "argentina_invoice", "delivery"]


class PartnerInput(BaseModel):
    name: str = Field(min_length=1)
    vat: str | None = None
    email: str | None = None
    supplier_rank: int = Field(default=1, ge=0)


class ProductInput(BaseModel):
    name: str = Field(min_length=1)
    default_code: str | None = None
    list_price: float = Field(default=0.0, ge=0)
    standard_price: float | None = Field(default=None, ge=0)
    description_sale: str | None = None


class InvoiceLineInput(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    price_unit: float = Field(ge=0)
    name: str | None = None


class InvoiceInput(BaseModel):
    partner_id: int
    move_type: InvoiceMoveType = Field(default="out_invoice")
    invoice_date: str | None = None
    lines: list[InvoiceLineInput] = Field(min_length=1)
    narration: str | None = None


class DeliveryMoveInput(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    name: str = Field(min_length=1)


class DeliveryInput(BaseModel):
    partner_id: int
    picking_type_id: int
    location_id: int
    location_dest_id: int
    origin: str | None = None
    moves: list[DeliveryMoveInput] = Field(min_length=1)
    scheduled_date: str | None = None


class SearchInput(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class OdooSearchHit(BaseModel):
    id: int
    display_name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class OdooSearchResult(BaseModel):
    mode: OdooIntegrationMode
    model: OdooModelName
    hits: list[OdooSearchHit]


class InvoiceValidationInput(BaseModel):
    partner_id: int | None = None
    journal_id: int | None = None
    move_type: InvoiceMoveType = Field(default="out_invoice")
    line_count: int = Field(default=0, ge=0)


class DeliveryValidationInput(BaseModel):
    partner_id: int | None = None
    picking_type_id: int | None = None
    location_id: int | None = None
    location_dest_id: int | None = None
    move_count: int = Field(default=0, ge=0)


class ArgentinaInvoiceValidationInput(BaseModel):
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


class InvoiceAttachment(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    content_bytes: bytes = Field(min_length=1)


class OdooValidationIssue(BaseModel):
    code: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class OdooValidationResult(BaseModel):
    mode: OdooIntegrationMode
    operation: OdooValidationOperation
    ok: bool
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[OdooValidationIssue] = Field(default_factory=list)


class OdooOperationResult(BaseModel):
    mode: OdooIntegrationMode
    model: OdooModelName
    record_id: int | None = None
    payload: dict[str, Any]
