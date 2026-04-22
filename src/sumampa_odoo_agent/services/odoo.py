"""Explicit Odoo-facing service layer."""

from __future__ import annotations

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    OdooOperationResult,
    OdooSearchResult,
    OdooValidationResult,
    PurchaseInvoiceProposalResult,
    SearchJournalsQuery,
    SearchLocationsQuery,
    SearchPartnersQuery,
    SearchPickingTypesQuery,
    SearchProductsQuery,
    SearchTaxesQuery,
    ValidateArgentinaInvoiceDraftQuery,
    ValidateDeliveryDraftQuery,
    ValidateInvoiceDraftQuery,
)


class OdooService:
    """Thin service wrapper around the active Odoo integration."""

    def __init__(self, gateway: OdooGateway) -> None:
        self._gateway = gateway

    @property
    def gateway(self) -> OdooGateway:
        return self._gateway

    async def analyze_purchase_invoice(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult:
        return await self._gateway.analyze_purchase_invoice(command)

    async def apply_purchase_invoice_proposal(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        return await self._gateway.apply_purchase_invoice_proposal(command)

    async def search_partners(self, query: SearchPartnersQuery) -> OdooSearchResult:
        return await self._gateway.search_partners(query)

    async def search_products(self, query: SearchProductsQuery) -> OdooSearchResult:
        return await self._gateway.search_products(query)

    async def search_journals(self, query: SearchJournalsQuery) -> OdooSearchResult:
        return await self._gateway.search_journals(query)

    async def search_taxes(self, query: SearchTaxesQuery) -> OdooSearchResult:
        return await self._gateway.search_taxes(query)

    async def search_picking_types(self, query: SearchPickingTypesQuery) -> OdooSearchResult:
        return await self._gateway.search_picking_types(query)

    async def search_locations(self, query: SearchLocationsQuery) -> OdooSearchResult:
        return await self._gateway.search_locations(query)

    async def validate_invoice_draft(
        self,
        query: ValidateInvoiceDraftQuery,
    ) -> OdooValidationResult:
        return await self._gateway.validate_invoice_draft(query)

    async def validate_argentina_invoice_draft(
        self,
        query: ValidateArgentinaInvoiceDraftQuery,
    ) -> OdooValidationResult:
        return await self._gateway.validate_argentina_invoice_draft(query)

    async def validate_delivery_draft(
        self,
        query: ValidateDeliveryDraftQuery,
    ) -> OdooValidationResult:
        return await self._gateway.validate_delivery_draft(query)

    async def create_partner(self, command: CreatePartnerCommand) -> OdooOperationResult:
        return await self._gateway.create_partner(command)

    async def create_product(self, command: CreateProductCommand) -> OdooOperationResult:
        return await self._gateway.create_product(command)

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        return await self._gateway.create_invoice(command)

    async def create_delivery(self, command: CreateDeliveryCommand) -> OdooOperationResult:
        return await self._gateway.create_delivery(command)
