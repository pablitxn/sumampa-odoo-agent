"""Integration tests for purchase invoice extraction using the real OpenAI API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from sumampa_odoo_agent.application.requests.odoo import AnalyzePurchaseInvoiceCommand
from sumampa_odoo_agent.infrastructure.extraction.service import OpenAIPurchaseInvoiceExtractor


@dataclass(frozen=True, slots=True)
class PurchaseInvoiceFixtureCase:
    filename: str
    supplier_name_contains: str | None = None
    supplier_hint: str | None = None
    min_lines: int = 1


CASES = (
    PurchaseInvoiceFixtureCase(
        filename="arcor_1.jpeg",
        supplier_name_contains="Julio",
    ),
    PurchaseInvoiceFixtureCase(
        filename="arcor_2.jpeg",
        supplier_name_contains="Julio",
    ),
    PurchaseInvoiceFixtureCase(
        filename="jambo_1.jpeg",
        supplier_name_contains="Jambo",
        supplier_hint="Jambo",
    ),
    PurchaseInvoiceFixtureCase(
        filename="jambo_2.jpeg",
        supplier_name_contains="Jambo",
        supplier_hint="Jambo",
    ),
    PurchaseInvoiceFixtureCase(
        filename="jambo_3.jpeg",
        supplier_name_contains="Jambo",
        supplier_hint="Jambo",
    ),
    PurchaseInvoiceFixtureCase(
        filename="molinos_1.jpeg",
        supplier_name_contains="Molinos",
        supplier_hint="Molinos",
    ),
)


def _integration_model() -> str:
    return os.environ.get("ORCHID_INVOICE_EXTRACTION_MODEL", "gpt-5.4")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=case.filename.rsplit(".", 1)[0]) for case in CASES],
)
async def test_openai_extracts_real_purchase_invoice_fixtures(
    case: PurchaseInvoiceFixtureCase,
    openai_api_key: str,
    purchase_invoice_fixtures_dir: Path,
) -> None:
    del openai_api_key

    fixture_path = purchase_invoice_fixtures_dir / case.filename
    image_bytes = fixture_path.read_bytes()
    extractor = OpenAIPurchaseInvoiceExtractor(
        model=_integration_model(),
        api_key_env_var="OPENAI_API_KEY",
    )

    result = await extractor.extract(
        AnalyzePurchaseInvoiceCommand(
            filename=fixture_path.name,
            content_type="image/jpeg",
            image_bytes=image_bytes,
            supplier_name=case.supplier_hint,
        )
    )

    assert result.supplier_name is not None
    if case.supplier_name_contains is not None:
        assert case.supplier_name_contains.casefold() in result.supplier_name.casefold()
    assert len(result.lines) >= case.min_lines
    assert all(line.description.strip() for line in result.lines)
    assert all(line.quantity > 0 for line in result.lines)
    assert all(line.unit_price_gross >= 0 for line in result.lines)
    assert all(line.vat_rate >= 0 for line in result.lines)

    assert result.document_type is not None
    assert result.document_type.strip()
    assert result.currency == "ARS"
    assert result.invoice_number is not None

    if result.total_amount is not None:
        assert result.total_amount > 0

    if result.subtotal_untaxed is not None:
        assert result.subtotal_untaxed >= 0

    if result.total_vat is not None:
        assert result.total_vat >= 0
