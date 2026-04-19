"""Port for high-value Odoo write operations."""

from __future__ import annotations

from typing import Protocol

from sumampa_odoo_agent.application.requests.odoo import (
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


class OdooPort(Protocol):
    async def analyze_purchase_invoice(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> PurchaseInvoiceProposalResult:
        """Extract and price a purchase invoice from an uploaded image."""

    async def apply_purchase_invoice_proposal(
        self,
        command: ApplyPurchaseInvoiceProposalCommand,
    ) -> ApplyPurchaseInvoiceProposalResult:
        """Apply a purchase invoice proposal into Odoo-related operations."""

    async def search_partners(self, query: SearchPartnersQuery) -> OdooSearchResult:
        """Search partners in Odoo."""

    async def search_products(self, query: SearchProductsQuery) -> OdooSearchResult:
        """Search products in Odoo."""

    async def search_journals(self, query: SearchJournalsQuery) -> OdooSearchResult:
        """Search journals in Odoo."""

    async def search_taxes(self, query: SearchTaxesQuery) -> OdooSearchResult:
        """Search taxes in Odoo."""

    async def search_picking_types(self, query: SearchPickingTypesQuery) -> OdooSearchResult:
        """Search picking types in Odoo."""

    async def search_locations(self, query: SearchLocationsQuery) -> OdooSearchResult:
        """Search stock locations in Odoo."""

    async def validate_invoice_draft(
        self,
        query: ValidateInvoiceDraftQuery,
    ) -> OdooValidationResult:
        """Validate an invoice draft before creation."""

    async def validate_argentina_invoice_draft(
        self,
        query: ValidateArgentinaInvoiceDraftQuery,
    ) -> OdooValidationResult:
        """Validate an Argentina electronic invoice draft before creation."""

    async def validate_delivery_draft(
        self,
        query: ValidateDeliveryDraftQuery,
    ) -> OdooValidationResult:
        """Validate a delivery draft before creation."""

    async def create_partner(self, command: CreatePartnerCommand) -> OdooOperationResult:
        """Create a partner in Odoo."""

    async def create_product(self, command: CreateProductCommand) -> OdooOperationResult:
        """Create a product in Odoo."""

    async def create_invoice(self, command: CreateInvoiceCommand) -> OdooOperationResult:
        """Create an invoice in Odoo."""

    async def create_delivery(self, command: CreateDeliveryCommand) -> OdooOperationResult:
        """Create a delivery order in Odoo."""
