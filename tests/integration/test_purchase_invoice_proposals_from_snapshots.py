"""Integration tests for downstream proposal building using saved extraction snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
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


def _load_snapshot(path: Path) -> ExtractedPurchaseInvoiceDocument:
    return ExtractedPurchaseInvoiceDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _build_catalog_from_snapshot(extracted: ExtractedPurchaseInvoiceDocument) -> list[dict[str, object]]:
    products: list[dict[str, object]] = []
    for index, line in enumerate(extracted.lines[: min(4, len(extracted.lines))], start=1):
        products.append(
            {
                "id": 1000 + index,
                "display_name": line.description,
                "default_code": f"SKU-{index}",
                "list_price": round(float(line.unit_price_gross) * 1.5, 2),
                "standard_price": round(float(line.unit_price_gross) * 0.7, 2),
            }
        )
    return products


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot_name",
    [
        "arcor_1.json",
        "arcor_2.json",
        "jambo_1.json",
        "jambo_2.json",
        "jambo_3.json",
        "molinos_1.json",
    ],
)
async def test_dry_run_builds_purchase_proposal_from_saved_snapshot(
    snapshot_name: str,
    purchase_invoice_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / snapshot_name)
    monkeypatch.setattr(DryRunOdooClient, "_products", _build_catalog_from_snapshot(extracted))
    monkeypatch.setattr(
        DryRunOdooClient,
        "_stock_by_product_id",
        {1001: 8.0, 1002: 3.0, 1003: 0.0, 1004: 11.0},
    )

    client = DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted))
    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename=snapshot_name.replace(".json", ".jpeg"),
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=35.0,
        )
    )

    assert proposal.mode == "dry-run"
    assert proposal.supplier_name == extracted.supplier_name
    assert proposal.invoice_number == extracted.invoice_number
    assert len(proposal.lines) == len(extracted.lines)
    assert proposal.markup_percentage == 35.0

    matched_lines = [line for line in proposal.lines if line.product_match.product_id is not None]
    assert matched_lines

    first_matched = matched_lines[0]
    expected_sale_price = round(first_matched.unit_price_net * 1.35 + 1e-9, 2)
    assert first_matched.suggested_sale_price == expected_sale_price

    if first_matched.product_match.current_stock is not None:
        expected_stock = round(
            first_matched.product_match.current_stock + first_matched.quantity + 1e-9,
            2,
        )
        assert first_matched.stock_after_update == expected_stock

    assert proposal.totals.total >= proposal.totals.untaxed
    assert proposal.totals.total >= proposal.totals.vat


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dry_run_apply_splits_bill_and_price_updates_from_snapshot(
    purchase_invoice_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / "jambo_1.json")
    monkeypatch.setattr(DryRunOdooClient, "_products", _build_catalog_from_snapshot(extracted))
    monkeypatch.setattr(
        DryRunOdooClient,
        "_stock_by_product_id",
        {1001: 5.0, 1002: 1.0, 1003: 0.0, 1004: 0.0},
    )
    client = DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted))

    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="jambo_1.jpeg",
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=30.0,
        )
    )

    bill_only = await client.apply_purchase_invoice_proposal(
        ApplyPurchaseInvoiceProposalCommand(
            supplier_id=102,
            journal_id=301,
            create_vendor_bill=True,
            update_products=False,
            proposal=proposal,
        )
    )
    assert bill_only.applied is True
    assert any(operation.model == "account.move" for operation in bill_only.operations)
    assert all(operation.model != "product.template" for operation in bill_only.operations)

    prices_only = await client.apply_purchase_invoice_proposal(
        ApplyPurchaseInvoiceProposalCommand(
            supplier_id=102,
            journal_id=301,
            create_vendor_bill=False,
            update_products=True,
            proposal=proposal,
        )
    )
    assert prices_only.applied is True
    assert any(operation.model == "product.template" for operation in prices_only.operations)
    assert all(operation.model != "account.move" for operation in prices_only.operations)
