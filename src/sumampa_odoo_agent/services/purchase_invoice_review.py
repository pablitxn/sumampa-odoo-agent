"""Human review use case for resolving purchase invoice ambiguities."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sumampa_odoo_agent.services.models.odoo import (
    PurchaseInvoiceProductCandidate,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.services.models.purchase_workflow import (
    PurchaseResolutionDecision,
)
from sumampa_odoo_agent.services.purchase_invoice_actions import (
    CreateMissingProductInput,
    CreateMissingSupplierInput,
    PurchaseInvoiceActionsUseCase,
)


@dataclass(slots=True)
class ApplyPurchaseInvoiceHumanReviewInput:
    proposal: PurchaseInvoiceProposalResult
    resolution: PurchaseResolutionDecision


@dataclass(slots=True)
class ApplyPurchaseInvoiceHumanReviewResult:
    proposal: PurchaseInvoiceProposalResult
    changed: bool = False
    created_summary: str | None = None
    error_message: str | None = None
    has_blockers: bool = False
    ready_for_confirmation: bool = False


class PurchaseInvoiceHumanReviewUseCase:
    """Apply structured human review decisions over supplier/product resolution."""

    def __init__(self, invoice_actions: PurchaseInvoiceActionsUseCase) -> None:
        self._invoice_actions = invoice_actions

    async def apply(
        self,
        request: ApplyPurchaseInvoiceHumanReviewInput,
    ) -> ApplyPurchaseInvoiceHumanReviewResult:
        proposal = request.proposal
        decision = request.resolution

        changed = apply_resolution_decision(proposal, decision)
        created_summary, creation_error = await self._apply_creation_decisions(proposal, decision)
        if creation_error is not None:
            return ApplyPurchaseInvoiceHumanReviewResult(
                proposal=proposal,
                changed=changed,
                created_summary=created_summary,
                error_message=creation_error,
                has_blockers=proposal_has_resolution_blockers(proposal),
            )

        has_blockers = proposal_has_resolution_blockers(proposal)
        ready_for_confirmation = False
        if decision.accept_current_resolution or changed or created_summary is not None:
            if not has_blockers:
                proposal.needs_user_resolution = False
                ready_for_confirmation = True

        return ApplyPurchaseInvoiceHumanReviewResult(
            proposal=proposal,
            changed=changed,
            created_summary=created_summary,
            has_blockers=has_blockers,
            ready_for_confirmation=ready_for_confirmation,
        )

    async def _apply_creation_decisions(
        self,
        proposal: PurchaseInvoiceProposalResult,
        decision: PurchaseResolutionDecision,
    ) -> tuple[str | None, str | None]:
        created_messages: list[str] = []

        if (
            proposal.supplier_resolution is not None
            and decision.supplier is not None
            and decision.supplier.action == "create_missing"
            and proposal.supplier_resolution.status not in {"exact", "manual"}
        ):
            resolution = proposal.supplier_resolution
            try:
                result = await self._invoice_actions.create_missing_supplier(
                    CreateMissingSupplierInput(
                        name=resolution.selected_display_name
                        or resolution.extracted_name
                        or "Proveedor sin nombre",
                        vat=resolution.selected_vat or resolution.extracted_vat,
                    )
                )
            except RuntimeError as exc:
                return None, (
                    "No pude crear el proveedor nuevo en Odoo todavía.\n"
                    f"{exc}"
                )
            resolution.status = "manual"
            resolution.selected_partner_id = int(result.record_id or 0) or None
            resolution.selected_display_name = str(
                result.payload.get("name") or resolution.selected_display_name
            )
            resolution.selected_vat = (
                str(result.payload.get("vat")) if result.payload.get("vat") else None
            )
            created_messages.append(
                f"proveedor:{resolution.selected_partner_id}"
            )

        for line_decision in decision.lines:
            if line_decision.action != "create_missing":
                continue
            line = proposal_line_by_number(proposal.lines, line_decision.line_number)
            if line is None or line.product_resolution.status in {"exact", "manual"}:
                continue
            try:
                result = await self._invoice_actions.create_missing_product(
                    CreateMissingProductInput(
                        name=line.description,
                        default_code=suggest_product_default_code(line),
                        list_price=line.suggested_sale_price,
                        standard_price=line.unit_price_net,
                        description_sale=line.description,
                    )
                )
            except RuntimeError as exc:
                return None, (
                    f"No pude crear el producto nuevo de la línea {line.line_number} en Odoo todavía.\n"
                    f"{exc}"
                )
            product_id = int(result.record_id or 0) or None
            line.product_resolution.status = "manual"
            line.product_resolution.selected_product_id = product_id
            line.product_resolution.selected_display_name = str(
                result.payload.get("name") or line.description
            )
            line.product_resolution.selected_default_code = (
                str(result.payload.get("default_code"))
                if result.payload.get("default_code")
                else None
            )
            line.product_match.product_id = product_id
            line.product_match.display_name = line.product_resolution.selected_display_name
            line.product_match.default_code = line.product_resolution.selected_default_code
            line.product_match.current_cost = float(
                result.payload.get("standard_price") or line.unit_price_net
            )
            line.product_match.current_sale_price = float(
                result.payload.get("list_price") or line.suggested_sale_price
            )
            line.product_match.current_stock = 0.0
            line.product_match.confidence = 1.0
            line.stock_after_update = line.quantity
            created_messages.append(f"line:{line.line_number}:product:{product_id}")

        proposal.needs_user_resolution = proposal_needs_manual_review(proposal)
        if not created_messages:
            return None, None
        return ", ".join(created_messages), None


def apply_resolution_decision(
    proposal: PurchaseInvoiceProposalResult,
    decision: PurchaseResolutionDecision,
) -> bool:
    changed = False

    supplier_decision = decision.supplier
    if supplier_decision is not None and proposal.supplier_resolution is not None:
        if supplier_decision.action == "select_candidate" and supplier_decision.partner_id is not None:
            partner_id = supplier_decision.partner_id
            candidate = next(
                (
                    item
                    for item in proposal.supplier_resolution.candidates
                    if item.partner_id == partner_id
                ),
                None,
            )
            proposal.supplier_resolution.status = "manual"
            proposal.supplier_resolution.selected_partner_id = partner_id
            proposal.supplier_resolution.selected_display_name = (
                candidate.display_name if candidate else f"Proveedor #{partner_id}"
            )
            proposal.supplier_resolution.selected_vat = candidate.vat if candidate else None
            changed = True
        elif supplier_decision.action == "mark_new":
            proposal.supplier_resolution.status = "new"
            proposal.supplier_resolution.selected_partner_id = None
            proposal.supplier_resolution.selected_display_name = (
                proposal.supplier_resolution.extracted_name or "Proveedor nuevo"
            )
            proposal.supplier_resolution.selected_vat = proposal.supplier_resolution.extracted_vat
            changed = True

    for line_decision in decision.lines:
        line = proposal_line_by_number(proposal.lines, line_decision.line_number)
        if line is None:
            continue

        if line_decision.action == "select_candidate" and line_decision.product_id is not None:
            product_id = line_decision.product_id
            product_candidate: PurchaseInvoiceProductCandidate | None = next(
                (
                    item
                    for item in line.product_resolution.candidates
                    if item.product_id == product_id
                ),
                None,
            )
            line.product_resolution.status = "manual"
            line.product_resolution.selected_product_id = product_id
            line.product_resolution.selected_display_name = (
                product_candidate.display_name if product_candidate else f"Producto #{product_id}"
            )
            line.product_resolution.selected_default_code = (
                product_candidate.default_code if product_candidate else None
            )
            line.product_match.product_id = product_id
            line.product_match.display_name = line.product_resolution.selected_display_name
            line.product_match.default_code = line.product_resolution.selected_default_code
            if product_candidate is not None:
                line.product_match.current_sale_price = product_candidate.current_sale_price
                line.product_match.current_cost = product_candidate.current_cost
                line.product_match.current_stock = product_candidate.current_stock
                line.product_match.confidence = product_candidate.confidence
            changed = True
        elif line_decision.action == "mark_new":
            line.product_resolution.status = "new"
            line.product_resolution.selected_product_id = None
            line.product_resolution.selected_display_name = line.description
            line.product_resolution.selected_default_code = None
            line.product_match.product_id = None
            line.product_match.display_name = None
            line.product_match.default_code = None
            line.product_match.current_sale_price = None
            line.product_match.current_cost = None
            line.product_match.current_stock = None
            line.product_match.confidence = 0.0
            line.stock_after_update = None
            changed = True

    proposal.needs_user_resolution = proposal_needs_manual_review(proposal)
    return changed


def proposal_has_resolution_blockers(proposal: PurchaseInvoiceProposalResult) -> bool:
    if proposal.supplier_resolution and proposal.supplier_resolution.status in {"missing", "new"}:
        return True
    return any(line.product_resolution.status in {"missing", "new"} for line in proposal.lines)


def proposal_needs_manual_review(proposal: PurchaseInvoiceProposalResult) -> bool:
    if proposal.supplier_resolution and proposal.supplier_resolution.status in {
        "candidate",
        "missing",
        "new",
    }:
        return True
    return any(
        line.product_resolution.status in {"candidate", "missing", "new"}
        for line in proposal.lines
    )


def proposal_line_by_number(
    lines: list[PurchaseInvoiceProposalLine],
    line_number: int,
) -> PurchaseInvoiceProposalLine | None:
    return next((line for line in lines if line.line_number == line_number), None)


def suggest_product_default_code(line: PurchaseInvoiceProposalLine) -> str | None:
    ascii_value = (
        unicodedata.normalize("NFKD", line.description).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^A-Z0-9]+", "-", ascii_value.upper()).strip("-")
    if not cleaned:
        return None
    if cleaned.isdigit() and len(cleaned) <= 20:
        return cleaned
    base = cleaned[:18]
    return f"AUTO-{base[:13]}" if base else None
