"""Request handlers for Odoo operations."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    OdooOperationResult,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.domain.ports.odoo_port import OdooPort


class AnalyzePurchaseInvoiceCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: AnalyzePurchaseInvoiceCommand) -> PurchaseInvoiceProposalResult:
        return await self._odoo.analyze_purchase_invoice(request)


class ApplyPurchaseInvoiceProposalCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(
        self,
        request: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._odoo.apply_purchase_invoice_proposal(request)


class CreatePartnerCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: CreatePartnerCommand) -> OdooOperationResult:
        return await self._odoo.create_partner(request)


class CreateProductCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: CreateProductCommand) -> OdooOperationResult:
        return await self._odoo.create_product(request)


class CreateInvoiceCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: CreateInvoiceCommand) -> OdooOperationResult:
        return await self._odoo.create_invoice(request)


class CreateDeliveryCommandHandler:
    def __init__(self, odoo: OdooPort) -> None:
        self._odoo = odoo

    async def handle(self, request: CreateDeliveryCommand) -> OdooOperationResult:
        return await self._odoo.create_delivery(request)
