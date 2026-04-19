"""Targeted matching tests for supplier/product resolution heuristics."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient


class SnapshotPurchaseInvoiceExtractor:
    def __init__(self, extracted: ExtractedPurchaseInvoiceDocument) -> None:
        self._extracted = extracted

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        del command
        return self._extracted


async def test_supplier_resolution_tolerates_punctuation_differences(monkeypatch) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M. PALACIOS",
            "supplier_vat": None,
            "invoice_number": "0005-00000001",
            "invoice_date": "2026-04-15",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PURE DE TOMATE ARCOR X 520 GR.",
                    "quantity": 1,
                    "unit_price_gross": 1000,
                    "vat_rate": 21,
                }
            ],
        }
    )
    monkeypatch.setattr(
        DryRunOdooClient,
        "_partners",
        [
            {
                "id": 900,
                "display_name": "JULIO M PALACIOS",
                "vat": "20179786151",
                "email": "julio@example.test",
            }
        ],
    )
    monkeypatch.setattr(
        DryRunOdooClient,
        "_products",
        [
            {
                "id": 901,
                "display_name": "PURE DE TOMATE ARCOR X 520 GR",
                "default_code": "ARCOR-520",
                "list_price": 1200.0,
                "standard_price": 900.0,
            }
        ],
    )
    monkeypatch.setattr(DryRunOdooClient, "_stock_by_product_id", {901: 5.0})

    client = DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted))
    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="arcor_1.jpeg",
            content_type="image/jpeg",
            image_bytes=b"fake-image",
            markup_percentage=30.0,
        )
    )

    assert proposal.supplier_resolution is not None
    assert proposal.supplier_resolution.status == "exact"
    assert proposal.supplier_resolution.selected_display_name == "JULIO M PALACIOS"
