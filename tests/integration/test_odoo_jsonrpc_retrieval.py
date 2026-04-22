"""Integration tests for retrieval/resolution against a local Odoo 19 stack."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from sumampa_odoo_agent.integrations.odoo_client import OdooJsonRpcClient
from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ExtractedPurchaseInvoiceDocument,
    SearchPartnersQuery,
    SearchProductsQuery,
)


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


def _client(
    *,
    env: dict[str, str],
    extracted: ExtractedPurchaseInvoiceDocument | None = None,
) -> OdooJsonRpcClient:
    return OdooJsonRpcClient(
        base_url=env["ORCHID_ODOO_BASE_URL"],
        database=env["ORCHID_ODOO_DATABASE"],
        username=env["ORCHID_ODOO_USERNAME"],
        password=env["ORCHID_ODOO_PASSWORD"],
        timeout_seconds=float(env["ORCHID_ODOO_TIMEOUT_SECONDS"]),
        invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)
        if extracted is not None
        else None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_search_partners_finds_seeded_supplier(odoo19_env: dict[str, str]) -> None:
    client = _client(env=odoo19_env)
    result = await client.search_partners(SearchPartnersQuery(query="palacios", limit=10))

    assert result.mode == "jsonrpc"
    assert any(hit.display_name == "JULIO M PALACIOS" for hit in result.hits)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_search_products_finds_seeded_alias_product(odoo19_env: dict[str, str]) -> None:
    client = _client(env=odoo19_env)
    result = await client.search_products(SearchProductsQuery(query="HAR-0008", limit=10))

    assert result.mode == "jsonrpc"
    assert any(hit.extra.get("default_code") == "HAR-0008" for hit in result.hits)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_analyze_purchase_invoice_resolves_supplier_with_punctuation_typos(
    odoo19_env: dict[str, str],
    purchase_invoice_snapshots_dir: Path,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / "arcor_1.json")
    client = _client(env=odoo19_env, extracted=extracted)

    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="arcor_1.jpeg",
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=30.0,
        )
    )

    assert proposal.mode == "jsonrpc"
    assert proposal.supplier_resolution is not None
    assert proposal.supplier_resolution.status == "exact"
    assert proposal.supplier_resolution.selected_display_name == "JULIO M PALACIOS"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_analyze_purchase_invoice_uses_supplierinfo_aliases(
    odoo19_env: dict[str, str],
    purchase_invoice_snapshots_dir: Path,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / "molinos_1.json")
    client = _client(env=odoo19_env, extracted=extracted)

    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="molinos_1.jpeg",
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=30.0,
        )
    )

    first_line = proposal.lines[0]
    assert proposal.mode == "jsonrpc"
    assert first_line.product_resolution.status == "exact"
    assert first_line.product_resolution.selected_default_code == "HAR-0008"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jsonrpc_apply_can_persist_new_supplierinfo_aliases(
    odoo19_env: dict[str, str],
) -> None:
    alias_description = f"PASTELGRAS BOLSA 20K {uuid4().hex[:8]}"
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JAMBO SA",
            "supplier_vat": "30644193078",
            "invoice_number": "0021-00055999",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": alias_description,
                    "quantity": 1,
                    "unit_price_gross": 123904.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    client = _client(env=odoo19_env, extracted=extracted)
    supplier = (await client.search_partners(SearchPartnersQuery(query="JAMBO", limit=10))).hits[0]
    product = (await client.search_products(SearchProductsQuery(query="PASTELGRAS-20", limit=10))).hits[0]

    proposal = await client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="jambo-alias.jpeg",
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=30.0,
        )
    )
    assert proposal.lines[0].product_resolution.status == "missing"

    proposal.lines[0].product_resolution.status = "manual"
    proposal.lines[0].product_resolution.selected_product_id = product.id
    proposal.lines[0].product_resolution.selected_display_name = product.display_name
    proposal.lines[0].product_resolution.selected_default_code = str(
        product.extra.get("default_code") or ""
    )
    proposal.lines[0].product_match.product_id = product.id
    proposal.lines[0].product_match.display_name = product.display_name
    proposal.lines[0].product_match.default_code = str(product.extra.get("default_code") or "")

    result = await client.apply_purchase_invoice_proposal(
        ApplyPurchaseInvoiceProposalCommand(
            supplier_id=supplier.id,
            create_vendor_bill=False,
            update_products=False,
            learn_resolutions=True,
            proposal=proposal,
        )
    )
    assert any(operation.model == "product.supplierinfo" for operation in result.operations)

    replay_client = _client(env=odoo19_env, extracted=extracted)
    replay = await replay_client.analyze_purchase_invoice(
        AnalyzePurchaseInvoiceCommand(
            filename="jambo-alias-replay.jpeg",
            content_type="image/jpeg",
            image_bytes=b"snapshot-backed-image",
            markup_percentage=30.0,
        )
    )
    assert replay.lines[0].product_resolution.status == "exact"
    assert replay.lines[0].product_resolution.selected_default_code == "PASTELGRAS-20"
