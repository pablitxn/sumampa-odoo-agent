"""Port for purchase invoice extraction from uploaded artifacts."""

from __future__ import annotations

from typing import Protocol

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)


class PurchaseInvoiceExtractorPort(Protocol):
    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        """Extract normalized purchase invoice data from an uploaded artifact."""
