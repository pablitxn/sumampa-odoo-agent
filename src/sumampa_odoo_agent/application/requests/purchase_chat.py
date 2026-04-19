"""Request models for conversational purchase invoice flows."""

from __future__ import annotations

from typing import Literal

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


class PurchaseChatPlannerDecision(BaseModel):
    intent: Literal[
        "greet",
        "await_invoice",
        "confirm_invoice",
        "reject_invoice",
        "confirm_stock",
        "reject_stock",
        "confirm_prices",
        "reject_prices",
        "reset",
        "other",
    ]
    assistant_message: str = Field(min_length=1)
