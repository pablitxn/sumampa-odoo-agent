"""Request models for conversational purchase invoice flows."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    InvoiceAttachment,
    PurchaseInvoiceProposalResult,
)


class PurchaseChatContext(BaseModel):
    supplier_id: int | None = None
    journal_id: int | None = None
    picking_type_id: int | None = None
    location_id: int | None = None
    location_dest_id: int | None = None
    create_stock_receipt: bool | None = None
    markup_percentage: float | None = Field(default=None, ge=0)
    supplier_name: str | None = None
    supplier_vat: str | None = None


class PurchaseChatMessageCommand(BaseModel):
    session_id: str | None = None
    message: str = ""
    attachments: list[InvoiceAttachment] = Field(default_factory=list)
    context: PurchaseChatContext = Field(default_factory=PurchaseChatContext)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_single_attachment(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("attachments"):
            return data

        filename = data.get("filename")
        image_bytes = data.get("image_bytes")
        if not filename or image_bytes in (None, b""):
            return data

        upgraded = dict(data)
        upgraded["attachments"] = [
            {
                "filename": filename,
                "content_type": data.get("content_type"),
                "content_bytes": image_bytes,
            }
        ]
        return upgraded


class PurchaseChatResponse(BaseModel):
    session_id: str
    stage: Literal[
        "awaiting_invoice",
        "awaiting_resolution",
        "awaiting_invoice_confirmation",
        "awaiting_stock_confirmation",
        "awaiting_price_confirmation",
        "completed",
    ]
    assistant_message: str
    proposal: PurchaseInvoiceProposalResult | None = None
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None = None

    @model_validator(mode="before")
    @classmethod
    def _snapshot_nested_models(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        snapshot = dict(data)
        proposal = snapshot.get("proposal")
        if isinstance(proposal, PurchaseInvoiceProposalResult):
            snapshot["proposal"] = proposal.model_copy(deep=True)

        last_apply_result = snapshot.get("last_apply_result")
        if isinstance(last_apply_result, ApplyPurchaseInvoiceProposalResult):
            snapshot["last_apply_result"] = last_apply_result.model_copy(deep=True)

        return snapshot


class PurchaseChatSupplierResolutionDecision(BaseModel):
    action: Literal["select_candidate", "mark_new", "create_missing"]
    partner_id: int | None = None


class PurchaseChatLineResolutionDecision(BaseModel):
    line_number: int = Field(ge=1)
    action: Literal["select_candidate", "mark_new", "create_missing"]
    product_id: int | None = None


class PurchaseChatResolutionDecision(BaseModel):
    accept_current_resolution: bool = False
    supplier: PurchaseChatSupplierResolutionDecision | None = None
    lines: list[PurchaseChatLineResolutionDecision] = Field(default_factory=list)


class PurchaseChatTurnDecision(BaseModel):
    action: Literal[
        "await_invoice",
        "reply_only",
        "reset",
        "review_resolution",
        "confirm_invoice",
        "reject_invoice",
        "confirm_stock",
        "reject_stock",
        "confirm_prices",
        "reject_prices",
    ]
    resolution: PurchaseChatResolutionDecision | None = None


class PurchaseChatReplyRequest(BaseModel):
    stage: Literal[
        "awaiting_invoice",
        "awaiting_resolution",
        "awaiting_invoice_confirmation",
        "awaiting_stock_confirmation",
        "awaiting_price_confirmation",
        "completed",
    ]
    event: Literal[
        "awaiting_invoice",
        "missing_context",
        "analysis_requires_resolution",
        "analysis_ready_for_invoice_confirmation",
        "resolution_updated",
        "resolution_blocked",
        "resolution_ready_for_invoice_confirmation",
        "resolution_error",
        "resolution_reset",
        "awaiting_invoice_confirmation",
        "invoice_rejected",
        "invoice_runtime_error",
        "invoice_blocked",
        "invoice_applied",
        "awaiting_stock_confirmation",
        "stock_rejected",
        "stock_runtime_error",
        "stock_blocked",
        "stock_applied",
        "awaiting_price_confirmation",
        "price_rejected",
        "price_runtime_error",
        "price_blocked",
        "price_applied",
        "completed_existing_flow",
    ]
    user_message: str | None = None
    proposal: PurchaseInvoiceProposalResult | None = None
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PurchaseChatReply(BaseModel):
    assistant_message: str = Field(min_length=1)
