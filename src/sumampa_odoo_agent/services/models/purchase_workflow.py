"""Request and response models for the agent-driven purchase workflow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from sumampa_odoo_agent.services.models.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalResult,
)

PurchaseWorkflowStage = Literal[
    "awaiting_invoice",
    "awaiting_resolution",
    "awaiting_invoice_confirmation",
    "awaiting_stock_confirmation",
    "awaiting_price_confirmation",
    "completed",
]


class PurchaseWorkflowContext(BaseModel):
    supplier_id: int | None = None
    journal_id: int | None = None
    picking_type_id: int | None = None
    location_id: int | None = None
    location_dest_id: int | None = None
    create_stock_receipt: bool | None = None
    markup_percentage: float | None = Field(default=None, ge=0)
    supplier_name: str | None = None
    supplier_vat: str | None = None


class PurchaseWorkflowResponse(BaseModel):
    session_id: str
    stage: PurchaseWorkflowStage
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


class PurchaseSupplierResolutionDecision(BaseModel):
    action: Literal["select_candidate", "mark_new", "create_missing"]
    partner_id: int | None = None


class PurchaseLineResolutionDecision(BaseModel):
    line_number: int = Field(ge=1)
    action: Literal["select_candidate", "mark_new", "create_missing"]
    product_id: int | None = None


class PurchaseResolutionDecision(BaseModel):
    accept_current_resolution: bool = False
    supplier: PurchaseSupplierResolutionDecision | None = None
    lines: list[PurchaseLineResolutionDecision] = Field(default_factory=list)
