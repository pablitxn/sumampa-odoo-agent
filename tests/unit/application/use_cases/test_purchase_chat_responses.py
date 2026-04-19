"""Unit tests for purchase chat response helpers."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    PurchaseInvoiceProductCandidate,
    PurchaseInvoiceProductMatch,
    PurchaseInvoiceProductResolution,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalTotals,
    PurchaseInvoiceSupplierCandidate,
    PurchaseInvoiceSupplierResolution,
)
from sumampa_odoo_agent.application.use_cases.purchase_chat_responses import (
    response_after_invoice_analysis,
    response_after_resolution,
)
from sumampa_odoo_agent.application.use_cases.purchase_invoice_human_review import (
    ApplyPurchaseInvoiceHumanReviewResult,
)


def _sample_proposal() -> PurchaseInvoiceProposalResult:
    return PurchaseInvoiceProposalResult(
        mode="dry-run",
        supplier_name="Proveedor Demo",
        supplier_resolution=PurchaseInvoiceSupplierResolution(
            status="candidate",
            extracted_name="Proveedor Demo",
            candidates=[
                PurchaseInvoiceSupplierCandidate(
                    partner_id=102,
                    display_name="Proveedor Demo SA",
                    confidence=0.8,
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
                            confidence=0.8,
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


def test_state_machine_routes_analysis_to_resolution_when_needed() -> None:
    proposal = _sample_proposal()

    response = response_after_invoice_analysis(
        session_id="abc",
        proposal=proposal,
    )

    assert response.stage == "awaiting_resolution"
    assert "Antes de tocar Odoo me falta resolver" in response.assistant_message


def test_state_machine_routes_resolution_to_confirmation_when_ready() -> None:
    proposal = _sample_proposal()
    proposal.supplier_resolution.status = "manual"
    proposal.supplier_resolution.selected_partner_id = 102
    proposal.supplier_resolution.selected_display_name = "Proveedor Demo SA"
    proposal.lines[0].product_resolution.status = "manual"
    proposal.lines[0].product_resolution.selected_product_id = 201
    proposal.lines[0].product_match.product_id = 201
    proposal.needs_user_resolution = False
    resolution = ApplyPurchaseInvoiceHumanReviewResult(
        proposal=proposal,
        normalized_message="proveedor 102 linea 1 producto 201",
        changed=True,
        has_blockers=False,
        ready_for_confirmation=True,
    )

    response = response_after_resolution(
        session_id="abc",
        proposal=proposal,
        resolution=resolution,
    )

    assert response.stage == "awaiting_invoice_confirmation"
    assert "Registré esas resoluciones." in response.assistant_message


def test_state_machine_keeps_resolution_when_apply_still_blocked() -> None:
    proposal = _sample_proposal()
    resolution = ApplyPurchaseInvoiceHumanReviewResult(
        proposal=proposal,
        normalized_message="si",
        has_blockers=True,
    )

    response = response_after_resolution(
        session_id="abc",
        proposal=proposal,
        resolution=resolution,
    )

    assert response.stage == "awaiting_resolution"
    assert "Todavía quedan cosas por resolver" in response.assistant_message
