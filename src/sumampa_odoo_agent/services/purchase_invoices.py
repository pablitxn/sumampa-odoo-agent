"""Purchase invoice workflow service."""

from __future__ import annotations

from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.services.models.purchase_workflow import PurchaseResolutionDecision
from sumampa_odoo_agent.services.odoo import OdooService
from sumampa_odoo_agent.services.purchase_invoice_actions import (
    ConfirmPriceUpdatesInput,
    ConfirmPurchaseInvoiceInput,
    ConfirmStockReceiptInput,
    PurchaseInvoiceActionsUseCase,
)
from sumampa_odoo_agent.services.purchase_invoice_review import (
    ApplyPurchaseInvoiceHumanReviewInput,
    ApplyPurchaseInvoiceHumanReviewResult,
    PurchaseInvoiceHumanReviewUseCase,
)


class PurchaseInvoiceService:
    """Service focused on the purchase invoice workflow."""

    def __init__(self, odoo: OdooService) -> None:
        self._odoo = odoo
        self._actions = PurchaseInvoiceActionsUseCase(odoo.gateway)
        self._human_review = PurchaseInvoiceHumanReviewUseCase(self._actions)

    async def analyze(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult:
        return await self._odoo.analyze_purchase_invoice(command)

    async def apply(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._odoo.apply_purchase_invoice_proposal(command)

    async def confirm_invoice(
        self,
        request: ConfirmPurchaseInvoiceInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._actions.confirm_purchase_invoice(request)

    async def confirm_stock_receipt(
        self,
        request: ConfirmStockReceiptInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._actions.confirm_stock_receipt(request)

    async def confirm_price_updates(
        self,
        request: ConfirmPriceUpdatesInput,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._actions.confirm_price_updates(request)

    async def apply_human_review(
        self,
        *,
        proposal: PurchaseInvoiceProposalResult,
        resolution: PurchaseResolutionDecision,
    ) -> ApplyPurchaseInvoiceHumanReviewResult:
        return await self._human_review.apply(
            ApplyPurchaseInvoiceHumanReviewInput(
                proposal=proposal,
                resolution=resolution,
            )
        )
