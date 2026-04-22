"""Unit tests for purchase invoice human review use case."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.services.models.odoo import (
    OdooOperationResult,
    PurchaseInvoiceProductCandidate,
    PurchaseInvoiceProductMatch,
    PurchaseInvoiceProductResolution,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalTotals,
    PurchaseInvoiceSupplierCandidate,
    PurchaseInvoiceSupplierResolution,
)
from sumampa_odoo_agent.services.models.purchase_workflow import (
    PurchaseLineResolutionDecision,
    PurchaseResolutionDecision,
    PurchaseSupplierResolutionDecision,
)
from sumampa_odoo_agent.services.use_cases import (
    ApplyPurchaseInvoiceHumanReviewInput,
    PurchaseInvoiceHumanReviewUseCase,
)


class SpyPurchaseInvoiceActionsUseCase:
    def __init__(self) -> None:
        self.created_supplier = None
        self.created_product = None

    async def create_missing_supplier(self, request):
        self.created_supplier = request
        return OdooOperationResult(
            mode="dry-run",
            model="res.partner",
            record_id=999,
            payload={"name": request.name, "vat": request.vat, "supplier_rank": 1},
        )

    async def create_missing_product(self, request):
        self.created_product = request
        return OdooOperationResult(
            mode="dry-run",
            model="product.template",
            record_id=555,
            payload={
                "name": request.name,
                "default_code": request.default_code,
                "standard_price": request.standard_price,
                "list_price": request.list_price,
            },
        )


def _sample_proposal() -> PurchaseInvoiceProposalResult:
    return PurchaseInvoiceProposalResult(
        mode="dry-run",
        supplier_name="Proveedor Demo",
        supplier_resolution=PurchaseInvoiceSupplierResolution(
            status="candidate",
            extracted_name="Proveedor Demo",
            extracted_vat="30712345678",
            candidates=[
                PurchaseInvoiceSupplierCandidate(
                    partner_id=102,
                    display_name="Proveedor Demo SA",
                    vat="30712345678",
                    confidence=0.88,
                    reason="name_overlap",
                )
            ],
        ),
        invoice_number="A-1",
        invoice_date="2026-04-19",
        document_type="Factura A",
        markup_percentage=30.0,
        totals=PurchaseInvoiceProposalTotals(untaxed=100.0, vat=21.0, total=121.0),
        lines=[
            PurchaseInvoiceProposalLine(
                line_number=1,
                description="Producto Demo",
                quantity=2,
                unit_price_gross=121.0,
                vat_rate=21.0,
                unit_price_net=100.0,
                subtotal_net=200.0,
                subtotal_vat=42.0,
                subtotal_gross=242.0,
                product_match=PurchaseInvoiceProductMatch(),
                product_resolution=PurchaseInvoiceProductResolution(
                    status="candidate",
                    candidates=[
                        PurchaseInvoiceProductCandidate(
                            product_id=201,
                            display_name="Producto Demo SA",
                            default_code="PROD-DEMO",
                            current_sale_price=150.0,
                            current_cost=90.0,
                            current_stock=4.0,
                            confidence=0.8,
                            reason="name_overlap",
                        )
                    ],
                ),
                suggested_sale_price=130.0,
                suggested_markup_percentage=30.0,
                stock_after_update=None,
            )
        ],
        needs_user_resolution=True,
        warnings=[],
        assumptions=[],
    )


@pytest.mark.asyncio
async def test_purchase_invoice_human_review_accepts_manual_candidate_choices() -> None:
    invoice_actions = SpyPurchaseInvoiceActionsUseCase()
    use_case = PurchaseInvoiceHumanReviewUseCase(invoice_actions)  # type: ignore[arg-type]
    proposal = _sample_proposal()

    result = await use_case.apply(
        ApplyPurchaseInvoiceHumanReviewInput(
            proposal=proposal,
            resolution=PurchaseResolutionDecision(
                supplier=PurchaseSupplierResolutionDecision(
                    action="select_candidate",
                    partner_id=102,
                ),
                lines=[
                    PurchaseLineResolutionDecision(
                        line_number=1,
                        action="select_candidate",
                        product_id=201,
                    )
                ],
            ),
        )
    )

    assert result.changed is True
    assert result.ready_for_confirmation is True
    assert result.has_blockers is False
    assert proposal.supplier_resolution is not None
    assert proposal.supplier_resolution.selected_partner_id == 102
    assert proposal.lines[0].product_match.product_id == 201
    assert proposal.needs_user_resolution is False


@pytest.mark.asyncio
async def test_purchase_invoice_human_review_creates_new_entities() -> None:
    invoice_actions = SpyPurchaseInvoiceActionsUseCase()
    use_case = PurchaseInvoiceHumanReviewUseCase(invoice_actions)  # type: ignore[arg-type]
    proposal = _sample_proposal()
    assert proposal.supplier_resolution is not None
    proposal.supplier_resolution.status = "new"
    proposal.lines[0].product_resolution.status = "new"

    result = await use_case.apply(
        ApplyPurchaseInvoiceHumanReviewInput(
            proposal=proposal,
            resolution=PurchaseResolutionDecision(
                supplier=PurchaseSupplierResolutionDecision(action="create_missing"),
                lines=[
                    PurchaseLineResolutionDecision(
                        line_number=1,
                        action="create_missing",
                    )
                ],
            ),
        )
    )

    assert result.created_summary is not None
    assert result.ready_for_confirmation is True
    assert invoice_actions.created_supplier is not None
    assert invoice_actions.created_product is not None
    assert proposal.supplier_resolution.selected_partner_id == 999
    assert proposal.lines[0].product_match.product_id == 555


@pytest.mark.asyncio
async def test_purchase_invoice_human_review_keeps_blockers_when_user_only_confirms() -> None:
    invoice_actions = SpyPurchaseInvoiceActionsUseCase()
    use_case = PurchaseInvoiceHumanReviewUseCase(invoice_actions)  # type: ignore[arg-type]
    proposal = _sample_proposal()
    proposal.lines[0].product_resolution.status = "missing"
    proposal.lines[0].product_resolution.candidates = []

    result = await use_case.apply(
        ApplyPurchaseInvoiceHumanReviewInput(
            proposal=proposal,
            resolution=PurchaseResolutionDecision(accept_current_resolution=True),
        )
    )

    assert result.ready_for_confirmation is False
    assert result.has_blockers is True
    assert proposal.needs_user_resolution is True
