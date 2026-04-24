"""Small contracts kept only where multiple implementations exist."""

from __future__ import annotations

from typing import Any, Protocol

from sumampa_odoo_agent.services.models.odoo import (
    CreateDeliveryCommand,
    CreateInvoiceCommand,
    CreatePartnerCommand,
    CreateProductCommand,
    OdooOperationResult,
    OdooSearchResult,
    OdooValidationResult,
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
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult


class SessionStore(Protocol):
    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        """Load one persisted session payload."""

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        """Persist one session payload."""

    async def delete(self, *, namespace: str, session_id: str) -> None:
        """Delete one persisted session payload."""

    async def aclose(self) -> None:
        """Release store resources."""


class OdooGateway(Protocol):
    async def aclose(self) -> None:
        """Release gateway resources."""

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


class AgentRuntime(Protocol):
    async def run(self, request: AgentRunInput) -> AgentRunResult:
        """Run one agent turn and return a structured payload."""
