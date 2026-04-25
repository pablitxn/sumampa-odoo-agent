"""Small contracts kept only where multiple implementations exist."""

from __future__ import annotations

from typing import Any, Protocol

from sumampa_odoo_agent.services.models.attachments import StoredObjectReference
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryValidationInput,
    InvoiceInput,
    InvoiceValidationInput,
    OdooOperationResult,
    OdooSearchResult,
    OdooValidationResult,
    PartnerInput,
    ProductInput,
    SearchInput,
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


class AttachmentObjectStore(Protocol):
    async def put_object(
        self,
        *,
        key: str,
        content_bytes: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> StoredObjectReference:
        """Persist one attachment object and return its storage reference."""

    async def aclose(self) -> None:
        """Release store resources."""


class OdooGateway(Protocol):
    async def aclose(self) -> None:
        """Release gateway resources."""

    async def search_partners(self, query: SearchInput) -> OdooSearchResult:
        """Search partners in Odoo."""

    async def search_products(self, query: SearchInput) -> OdooSearchResult:
        """Search products in Odoo."""

    async def search_journals(self, query: SearchInput) -> OdooSearchResult:
        """Search journals in Odoo."""

    async def search_taxes(self, query: SearchInput) -> OdooSearchResult:
        """Search taxes in Odoo."""

    async def search_picking_types(self, query: SearchInput) -> OdooSearchResult:
        """Search picking types in Odoo."""

    async def search_locations(self, query: SearchInput) -> OdooSearchResult:
        """Search stock locations in Odoo."""

    async def validate_invoice_draft(
        self,
        draft: InvoiceValidationInput,
    ) -> OdooValidationResult:
        """Validate an invoice draft before creation."""

    async def validate_argentina_invoice_draft(
        self,
        draft: ArgentinaInvoiceValidationInput,
    ) -> OdooValidationResult:
        """Validate an Argentina electronic invoice draft before creation."""

    async def validate_delivery_draft(
        self,
        draft: DeliveryValidationInput,
    ) -> OdooValidationResult:
        """Validate a delivery draft before creation."""

    async def create_partner(self, partner: PartnerInput) -> OdooOperationResult:
        """Create a partner in Odoo."""

    async def create_product(self, product: ProductInput) -> OdooOperationResult:
        """Create a product in Odoo."""

    async def create_invoice(self, invoice: InvoiceInput) -> OdooOperationResult:
        """Create an invoice in Odoo."""

    async def create_delivery(self, delivery: DeliveryInput) -> OdooOperationResult:
        """Create a delivery order in Odoo."""


class AgentRuntime(Protocol):
    async def run(self, request: AgentRunInput) -> AgentRunResult:
        """Run one agent turn and return a structured payload."""
