"""Unit tests for purchase invoice entity resolution."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    ExtractedPurchaseInvoiceDocument,
)
from sumampa_odoo_agent.application.use_cases import (
    ResolvePurchaseInvoiceEntitiesInput,
    ResolvePurchaseInvoiceEntitiesUseCase,
    normalize_invoice_date,
)


def test_resolve_purchase_invoice_entities_builds_exact_matches() -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M. PALACIOS",
            "supplier_vat": "20-17978615-1",
            "invoice_number": "0001-00001234",
            "invoice_date": "13/4/2026",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PURE DE TOMATE ARCOR X 520 GR.",
                    "quantity": 2,
                    "unit_price_gross": 770.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    use_case = ResolvePurchaseInvoiceEntitiesUseCase()

    proposal = use_case.run(
        ResolvePurchaseInvoiceEntitiesInput(
            mode="jsonrpc",
            extracted=extracted,
            markup_percentage=30.0,
            partners=[
                {
                    "id": 10,
                    "display_name": "JULIO M. PALACIOS",
                    "vat": "20179786151",
                    "email": "julio@example.test",
                }
            ],
            products=[
                {
                    "id": 20,
                    "display_name": "PURE DE TOMATE ARCOR X 520 GR.",
                    "default_code": "ARCOR-520",
                    "list_price": 1000.0,
                    "standard_price": 600.0,
                    "supplier_aliases": [],
                }
            ],
            stock_by_product_id={20: 5.0},
            supplier_vat=extracted.supplier_vat,
        )
    )

    assert proposal.supplier_resolution.status == "exact"
    assert proposal.supplier_resolution.selected_partner_id == 10
    assert proposal.invoice_date == "2026-04-13"
    assert proposal.lines[0].product_resolution.status == "exact"
    assert proposal.lines[0].product_match.product_id == 20
    assert proposal.lines[0].stock_after_update == 7.0
    assert proposal.needs_user_resolution is False


def test_resolve_purchase_invoice_entities_marks_candidates_and_total_warnings() -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "PALACIOS TOMATES",
            "supplier_vat": None,
            "invoice_number": "0001-00009999",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "subtotal_untaxed": 100.0,
            "total_vat": 21.0,
            "total_amount": 121.0,
            "lines": [
                {
                    "description": "TOMATE ARCOR LATA 520",
                    "quantity": 2,
                    "unit_price_gross": 1000.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    use_case = ResolvePurchaseInvoiceEntitiesUseCase()

    proposal = use_case.run(
        ResolvePurchaseInvoiceEntitiesInput(
            mode="dry-run",
            extracted=extracted,
            markup_percentage=25.0,
            partners=[
                {
                    "id": 10,
                    "display_name": "JULIO M PALACIOS",
                    "vat": "20179786151",
                    "email": "julio@example.test",
                    "supplier_aliases": ["PALACIOS MAYORISTA"],
                    "supplier_alias_vats": [],
                }
            ],
                products=[
                    {
                        "id": 20,
                        "display_name": "PURE TOMATE ARCOR 520",
                        "default_code": "ARCOR-520",
                        "list_price": 1000.0,
                        "standard_price": 600.0,
                        "supplier_aliases": ["TOMATE 520"],
                    }
                ],
            stock_by_product_id={20: 1.0},
            supplier_vat=None,
        )
    )

    assert proposal.supplier_resolution.status == "candidate"
    assert proposal.lines[0].product_resolution.status == "candidate"
    assert proposal.needs_user_resolution is True
    assert any("requiere confirmacion humana" in warning for warning in proposal.warnings)
    assert any("no coincide" in warning for warning in proposal.warnings)


def test_normalize_invoice_date_keeps_supported_formats() -> None:
    assert normalize_invoice_date("13/4/2026") == "2026-04-13"
    assert normalize_invoice_date("2026-04-18") == "2026-04-18"
