"""Persisted purchase workflow state for agent-driven invoice handling."""

from __future__ import annotations

import base64
from typing import Any, Literal

from pydantic import BaseModel, Field

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    InvoiceAttachment,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_workflow import PurchaseWorkflowContext
from sumampa_odoo_agent.domain.ports.session_store_port import SessionStorePort

PURCHASE_WORKFLOW_NAMESPACE = "purchase-workflow"


def default_purchase_context() -> PurchaseWorkflowContext:
    return PurchaseWorkflowContext(
        create_stock_receipt=False,
        markup_percentage=30.0,
    )


class SerializedInvoiceAttachment(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    content_base64: str = Field(min_length=1)

    def to_attachment(self) -> InvoiceAttachment:
        return InvoiceAttachment(
            filename=self.filename,
            content_type=self.content_type,
            content_bytes=base64.b64decode(self.content_base64),
        )

    def prompt_summary(self) -> dict[str, object]:
        content_size = len(base64.b64decode(self.content_base64))
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": content_size,
        }


class PurchaseWorkflowRunContext(BaseModel):
    context: PurchaseWorkflowContext = Field(default_factory=default_purchase_context)
    attachments: list[SerializedInvoiceAttachment] = Field(default_factory=list)

    @classmethod
    def from_agent_context(cls, raw_context: dict[str, Any]) -> PurchaseWorkflowRunContext:
        purchase_context = raw_context.get("purchase_workflow") or raw_context.get("purchase")
        if not isinstance(purchase_context, dict):
            return cls()

        return cls.model_validate(
            {
                "context": purchase_context.get("context") or {},
                "attachments": purchase_context.get("attachments") or [],
            }
        )

    def has_inputs(self) -> bool:
        return bool(self.attachments) or bool(
            self.context.model_dump(exclude_none=True, exclude_defaults=True)
        )

    def prompt_view(self) -> dict[str, object]:
        return {
            "context": self.context.model_dump(exclude_none=True, exclude_defaults=True),
            "attachments": [attachment.prompt_summary() for attachment in self.attachments],
        }

    def to_attachments(self) -> list[InvoiceAttachment]:
        return [attachment.to_attachment() for attachment in self.attachments]


class PurchaseWorkflowState(BaseModel):
    session_id: str
    context: PurchaseWorkflowContext = Field(default_factory=default_purchase_context)
    proposal: PurchaseInvoiceProposalResult | None = None
    bill_result: ApplyPurchaseInvoiceProposalResult | None = None
    stock_result: ApplyPurchaseInvoiceProposalResult | None = None
    price_result: ApplyPurchaseInvoiceProposalResult | None = None
    last_result: ApplyPurchaseInvoiceProposalResult | None = None

    def current_last_apply_result(self) -> ApplyPurchaseInvoiceProposalResult | None:
        return self.last_result or self.price_result or self.stock_result or self.bill_result

    def snapshot(self) -> dict[str, object]:
        return {
            "stage": derive_purchase_workflow_stage(self),
            "proposal": self.proposal.model_dump(mode="json") if self.proposal is not None else None,
            "last_apply_result": (
                self.current_last_apply_result().model_dump(mode="json")
                if self.current_last_apply_result() is not None
                else None
            ),
            "context": self.context.model_dump(mode="json"),
        }

    def agent_snapshot(
        self,
        *,
        detail: Literal["compact", "full"] = "compact",
    ) -> dict[str, object]:
        if detail == "full":
            return self.snapshot()

        return {
            "stage": derive_purchase_workflow_stage(self),
            "context": self.context.model_dump(mode="json", exclude_none=True),
            "proposal": _compact_purchase_proposal(self.proposal),
            "last_apply_result": _compact_apply_result(self.current_last_apply_result()),
        }


def merge_purchase_context(
    current: PurchaseWorkflowContext,
    incoming: PurchaseWorkflowContext,
) -> PurchaseWorkflowContext:
    merged = current.model_copy(deep=True)
    for field_name in (
        "supplier_id",
        "journal_id",
        "picking_type_id",
        "location_id",
        "location_dest_id",
    ):
        value = getattr(incoming, field_name)
        if value is not None:
            setattr(merged, field_name, value)

    if incoming.create_stock_receipt is not None:
        merged.create_stock_receipt = incoming.create_stock_receipt
    if incoming.markup_percentage is not None:
        merged.markup_percentage = incoming.markup_percentage

    if incoming.supplier_name and incoming.supplier_name.strip():
        merged.supplier_name = incoming.supplier_name.strip()
    if incoming.supplier_vat and incoming.supplier_vat.strip():
        merged.supplier_vat = incoming.supplier_vat.strip()

    return merged


def sync_purchase_context_from_proposal(state: PurchaseWorkflowState) -> None:
    proposal = state.proposal
    if proposal is None or proposal.supplier_resolution is None:
        return
    if (
        state.context.supplier_id is None
        and proposal.supplier_resolution.selected_partner_id is not None
    ):
        state.context.supplier_id = proposal.supplier_resolution.selected_partner_id


def derive_purchase_workflow_stage(state: PurchaseWorkflowState) -> str:
    proposal = state.proposal
    if proposal is None:
        return "awaiting_invoice"
    if proposal.needs_user_resolution:
        return "awaiting_resolution"
    if state.bill_result is None or not state.bill_result.applied:
        return "awaiting_invoice_confirmation"
    if bool(state.context.create_stock_receipt) and (
        state.stock_result is None or not state.stock_result.applied
    ):
        return "awaiting_stock_confirmation"
    if state.price_result is None or not state.price_result.applied:
        return "awaiting_price_confirmation"
    return "completed"


async def load_purchase_workflow_state(
    store: SessionStorePort,
    *,
    session_id: str,
) -> PurchaseWorkflowState:
    payload = await store.load(namespace=PURCHASE_WORKFLOW_NAMESPACE, session_id=session_id)
    if payload is None:
        return PurchaseWorkflowState(session_id=session_id)
    return PurchaseWorkflowState.model_validate(payload)


async def save_purchase_workflow_state(
    store: SessionStorePort,
    state: PurchaseWorkflowState,
) -> None:
    await store.save(
        namespace=PURCHASE_WORKFLOW_NAMESPACE,
        session_id=state.session_id,
        payload=state.model_dump(mode="json"),
    )


async def delete_purchase_workflow_state(
    store: SessionStorePort,
    *,
    session_id: str,
) -> None:
    await store.delete(namespace=PURCHASE_WORKFLOW_NAMESPACE, session_id=session_id)


def _compact_purchase_proposal(
    proposal: PurchaseInvoiceProposalResult | None,
) -> dict[str, object] | None:
    if proposal is None:
        return None

    unresolved_lines = [
        {
            "line_number": line.line_number,
            "description": line.description,
            "quantity": line.quantity,
            "unit_price_gross": line.unit_price_gross,
            "vat_rate": line.vat_rate,
            "resolution_status": line.product_resolution.status,
            "selected_product_id": line.product_resolution.selected_product_id,
            "selected_display_name": line.product_resolution.selected_display_name,
            "candidate_count": len(line.product_resolution.candidates),
            "candidates": [
                {
                    "product_id": candidate.product_id,
                    "display_name": candidate.display_name,
                    "default_code": candidate.default_code,
                    "confidence": candidate.confidence,
                    "reason": candidate.reason,
                }
                for candidate in line.product_resolution.candidates
            ],
        }
        for line in proposal.lines
        if line.product_resolution.status != "exact"
    ]

    supplier_resolution = proposal.supplier_resolution
    return {
        "supplier_name": proposal.supplier_name,
        "supplier_vat": proposal.supplier_vat,
        "supplier_resolution": (
            None
            if supplier_resolution is None
            else {
                "status": supplier_resolution.status,
                "selected_partner_id": supplier_resolution.selected_partner_id,
                "selected_display_name": supplier_resolution.selected_display_name,
                "selected_vat": supplier_resolution.selected_vat,
                "extracted_name": supplier_resolution.extracted_name,
                "extracted_vat": supplier_resolution.extracted_vat,
                "candidate_count": len(supplier_resolution.candidates),
                "candidates": [
                    {
                        "partner_id": candidate.partner_id,
                        "display_name": candidate.display_name,
                        "vat": candidate.vat,
                        "email": candidate.email,
                        "confidence": candidate.confidence,
                        "reason": candidate.reason,
                    }
                    for candidate in supplier_resolution.candidates
                ],
            }
        ),
        "invoice_number": proposal.invoice_number,
        "invoice_date": proposal.invoice_date,
        "document_type": proposal.document_type,
        "currency": proposal.currency,
        "markup_percentage": proposal.markup_percentage,
        "totals": proposal.totals.model_dump(mode="json"),
        "extracted_totals": (
            proposal.extracted_totals.model_dump(mode="json")
            if proposal.extracted_totals is not None
            else None
        ),
        "line_count": len(proposal.lines),
        "needs_user_resolution": proposal.needs_user_resolution,
        "resolved_line_count": len(proposal.lines) - len(unresolved_lines),
        "unresolved_lines": unresolved_lines,
        "warnings": proposal.warnings,
        "assumptions": proposal.assumptions,
    }


def _compact_apply_result(
    result: ApplyPurchaseInvoiceProposalResult | None,
) -> dict[str, object] | None:
    if result is None:
        return None

    return {
        "mode": result.mode,
        "applied": result.applied,
        "operation_count": len(result.operations),
        "operation_models": sorted({operation.model for operation in result.operations}),
        "warnings": result.warnings,
    }
