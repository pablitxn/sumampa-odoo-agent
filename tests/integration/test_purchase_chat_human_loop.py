"""Integration tests for human-in-the-loop purchase chat behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
)
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient
from sumampa_odoo_agent.infrastructure.odoo.resolution_memory import (
    PurchaseResolutionMemoryStore,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import StubPurchaseChatAssistant
from sumampa_odoo_agent.infrastructure.purchase_chat.service import PurchaseChatService


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


def _catalog_for_chat(extracted: ExtractedPurchaseInvoiceDocument) -> list[dict[str, object]]:
    return [
        {
            "id": 2000 + index,
            "display_name": line.description,
            "default_code": f"CHAT-{index}",
            "list_price": round(float(line.unit_price_gross) * 1.4, 2),
            "standard_price": round(float(line.unit_price_gross) * 0.8, 2),
        }
        for index, line in enumerate(extracted.lines[:3], start=1)
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_keeps_user_in_loop_before_mutations_and_splits_stock_confirmation(
    purchase_invoice_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / "molinos_1.json")
    monkeypatch.setattr(DryRunOdooClient, "_products", _catalog_for_chat(extracted))
    monkeypatch.setattr(
        DryRunOdooClient,
        "_stock_by_product_id",
        {2001: 10.0, 2002: 2.0, 2003: 0.0},
    )

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    first = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            image_bytes=b"image-does-not-matter",
            filename="molinos_1.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                picking_type_id=502,
                location_id=603,
                location_dest_id=601,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )
    assert first.stage == "awaiting_resolution"
    assert first.last_apply_result is None
    assert first.proposal is not None

    resolved = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=first.session_id,
            message="proveedor 102",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                picking_type_id=502,
                location_id=603,
                location_dest_id=601,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )
    assert resolved.stage == "awaiting_invoice_confirmation"

    second = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=resolved.session_id,
            message="si, cargar factura",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                picking_type_id=502,
                location_id=603,
                location_dest_id=601,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )
    assert second.stage == "awaiting_stock_confirmation"
    assert second.last_apply_result is not None
    assert any(operation.model == "account.move" for operation in second.last_apply_result.operations)
    assert all(
        operation.model != "product.template" for operation in second.last_apply_result.operations
    )
    assert all(
        operation.model != "stock.picking" for operation in second.last_apply_result.operations
    )

    third = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=resolved.session_id,
            message="si, generar recepción",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                picking_type_id=502,
                location_id=603,
                location_dest_id=601,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )
    assert third.stage == "awaiting_price_confirmation"
    assert third.last_apply_result is not None
    assert any(operation.model == "stock.picking" for operation in third.last_apply_result.operations)

    fourth = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=resolved.session_id,
            message="si, actualizar precios",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )
    assert fourth.stage == "completed"
    assert fourth.last_apply_result is not None
    assert any(operation.model == "product.template" for operation in fourth.last_apply_result.operations)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_can_stop_after_bill_without_updating_prices(
    purchase_invoice_snapshots_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = _load_snapshot(purchase_invoice_snapshots_dir / "jambo_2.json")
    monkeypatch.setattr(DryRunOdooClient, "_products", _catalog_for_chat(extracted))
    monkeypatch.setattr(
        DryRunOdooClient,
        "_stock_by_product_id",
        {2001: 4.0, 2002: 4.0, 2003: 4.0},
    )

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="aca va",
            image_bytes=b"image-does-not-matter",
            filename="jambo_2.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=25.0,
            ),
        )
    )
    assert uploaded.stage == "awaiting_resolution"

    resolved = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="proveedor 102",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=25.0,
            ),
        )
    )
    assert resolved.stage == "awaiting_invoice_confirmation"

    billed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=resolved.session_id,
            message="si, cargar factura",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=25.0,
            ),
        )
    )

    done = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=resolved.session_id,
            message="no, por ahora no",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=25.0,
            ),
        )
    )

    assert billed.stage == "awaiting_price_confirmation"
    assert done.stage == "completed"
    assert done.last_apply_result is not None
    assert any(operation.model == "account.move" for operation in done.last_apply_result.operations)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_keeps_new_products_blocked_until_guided_creation_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M PALACIOS",
            "supplier_vat": "20179786151",
            "invoice_number": "0005-00000999",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PRODUCTO NUEVO SIN MATCH",
                    "quantity": 1,
                    "unit_price_gross": 1000.0,
                    "vat_rate": 21.0,
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
    monkeypatch.setattr(DryRunOdooClient, "_products", [])
    monkeypatch.setattr(DryRunOdooClient, "_stock_by_product_id", {})

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            image_bytes=b"image-does-not-matter",
            filename="nuevo.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert uploaded.stage == "awaiting_resolution"

    marked_new = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="linea 1 nuevo",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert marked_new.stage == "awaiting_resolution"
    assert marked_new.proposal is not None
    assert marked_new.proposal.lines[0].product_resolution.status == "new"

    confirmed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert confirmed.stage == "awaiting_resolution"
    assert "todavía quedan cosas por resolver" in confirmed.assistant_message.casefold()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_resolution_message_focuses_on_supplier_when_only_supplier_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "PROVEEDOR DUDOSO SA",
            "supplier_vat": None,
            "invoice_number": "0001-00000021",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "FIDEOS TIRABUZON 500G",
                    "quantity": 1,
                    "unit_price_gross": 1210.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    monkeypatch.setattr(DryRunOdooClient, "_partners", [])
    monkeypatch.setattr(
        DryRunOdooClient,
        "_products",
        [
            {
                "id": 501,
                "display_name": "FIDEOS TIRABUZON 500G",
                "default_code": "FIDEO-500",
                "list_price": 1800.0,
                "standard_price": 900.0,
            }
        ],
    )
    monkeypatch.setattr(DryRunOdooClient, "_stock_by_product_id", {501: 4.0})

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            image_bytes=b"image-does-not-matter",
            filename="supplier-only.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert uploaded.stage == "awaiting_resolution"
    assert "me falta resolver el proveedor" in uploaded.assistant_message.casefold()
    assert "líneas pendientes:" not in uploaded.assistant_message.casefold()
    assert "`proveedor 102`" in uploaded.assistant_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_resolution_message_focuses_on_lines_when_supplier_is_already_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M PALACIOS",
            "supplier_vat": "20179786151",
            "invoice_number": "0001-00000022",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PRODUCTO SIN MATCH LINEA",
                    "quantity": 1,
                    "unit_price_gross": 1210.0,
                    "vat_rate": 21.0,
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
    monkeypatch.setattr(DryRunOdooClient, "_products", [])
    monkeypatch.setattr(DryRunOdooClient, "_stock_by_product_id", {})

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            image_bytes=b"image-does-not-matter",
            filename="lines-only.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert uploaded.stage == "awaiting_resolution"
    assert "proveedor resuelto:" in uploaded.assistant_message.casefold()
    assert "me faltan estas líneas:" in uploaded.assistant_message.casefold()
    assert "me falta resolver el proveedor" not in uploaded.assistant_message.casefold()
    assert "`linea 1 producto 201`" in uploaded.assistant_message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_responses_are_snapshots_between_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "PALACIOS TOMATES",
            "supplier_vat": None,
            "invoice_number": "0005-00000078",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "TOMATE ARCOR LATA 520",
                    "quantity": 2,
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

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            image_bytes=b"image-does-not-matter",
            filename="snapshot-stability.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert uploaded.stage == "awaiting_resolution"
    assert uploaded.proposal is not None
    assert uploaded.proposal.supplier_resolution is not None
    original_supplier_status = uploaded.proposal.supplier_resolution.status
    original_product_status = uploaded.proposal.lines[0].product_resolution.status

    resolved = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="proveedor 900 linea 1 producto 901",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert resolved.stage == "awaiting_invoice_confirmation"
    assert uploaded.stage == "awaiting_resolution"
    assert uploaded.proposal.supplier_resolution.status == original_supplier_status
    assert uploaded.proposal.lines[0].product_resolution.status == original_product_status


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_can_create_new_supplier_and_product_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "PROVEEDOR NUEVO DEMO SA",
            "supplier_vat": "30712345678",
            "invoice_number": "0001-00000001",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PRODUCTO NUEVO DEMO CHAT",
                    "quantity": 2,
                    "unit_price_gross": 1210.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    monkeypatch.setattr(DryRunOdooClient, "_partners", [])
    monkeypatch.setattr(DryRunOdooClient, "_products", [])
    monkeypatch.setattr(DryRunOdooClient, "_stock_by_product_id", {})

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            image_bytes=b"image-does-not-matter",
            filename="nuevo-completo.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert uploaded.stage == "awaiting_resolution"

    marked_new = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="proveedor nuevo linea 1 nuevo",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert marked_new.stage == "awaiting_resolution"

    created = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="crear nuevos",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert created.stage == "awaiting_invoice_confirmation"
    assert "creé el proveedor" in created.assistant_message.casefold()
    assert created.proposal is not None
    assert created.proposal.supplier_resolution is not None
    assert created.proposal.supplier_resolution.selected_partner_id is not None
    assert created.proposal.lines[0].product_resolution.selected_product_id is not None

    billed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, cargar factura",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert billed.stage == "awaiting_price_confirmation"
    assert billed.last_apply_result is not None
    assert billed.last_apply_result.applied is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_learns_confirmed_resolution_for_next_invoice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "PALACIOS TOMATES",
            "supplier_vat": None,
            "invoice_number": "0005-00000077",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "TOMATE ARCOR LATA 520",
                    "quantity": 2,
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

    memory = PurchaseResolutionMemoryStore(tmp_path / "purchase-memory.json")
    service = PurchaseChatService(
        odoo=DryRunOdooClient(
            invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
            resolution_memory=memory,
        ),
        assistant=StubPurchaseChatAssistant(),
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            image_bytes=b"image-does-not-matter",
            filename="alias.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert uploaded.stage == "awaiting_resolution"

    resolved = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="proveedor 900 linea 1 producto 901",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert resolved.stage == "awaiting_invoice_confirmation"

    confirmed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, cargar factura",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert confirmed.stage == "awaiting_price_confirmation"

    replay = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso otra vez la misma",
            image_bytes=b"image-does-not-matter",
            filename="alias-2.jpeg",
            content_type="image/jpeg",
            context=PurchaseChatContext(
                supplier_id=900,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert replay.stage == "awaiting_invoice_confirmation"
    assert replay.proposal is not None
    assert replay.proposal.supplier_resolution is not None
    assert replay.proposal.supplier_resolution.status == "exact"
    assert replay.proposal.lines[0].product_resolution.status == "exact"
