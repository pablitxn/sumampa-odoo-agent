"""Integration tests for human-in-the-loop purchase chat behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
    InvoiceAttachment,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatLineResolutionDecision,
    PurchaseChatMessageCommand,
    PurchaseChatReplyRequest,
    PurchaseChatResolutionDecision,
    PurchaseChatSupplierResolutionDecision,
    PurchaseChatTurnDecision,
)
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient
from sumampa_odoo_agent.infrastructure.odoo.resolution_memory import (
    PurchaseResolutionMemoryStore,
)
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


class ScriptedAssistant:
    def __init__(self, decisions: list[PurchaseChatTurnDecision] | None = None) -> None:
        self._decisions = list(decisions or [])
        self.reply_requests: list[PurchaseChatReplyRequest] = []

    async def decide(
        self,
        *,
        stage: str,
        user_message: str,
        proposal,
        last_apply_result,
    ) -> PurchaseChatTurnDecision:
        del stage, user_message, proposal, last_apply_result
        if self._decisions:
            return self._decisions.pop(0)
        return PurchaseChatTurnDecision(action="reply_only")

    async def reply(self, request: PurchaseChatReplyRequest) -> str:
        self.reply_requests.append(request)
        supplier_pending = bool(
            request.proposal
            and request.proposal.supplier_resolution is not None
            and request.proposal.supplier_resolution.status not in {"exact", "manual"}
        )
        pending_lines = (
            [
                line.line_number
                for line in request.proposal.lines
                if line.product_resolution.status not in {"exact", "manual"}
            ]
            if request.proposal is not None
            else []
        )
        return (
            f"event={request.event};stage={request.stage};"
            f"supplier_pending={supplier_pending};pending_lines={pending_lines};"
            f"details={json.dumps(request.details, sort_keys=True, default=str)}"
        )


def _test_assistant(
    decisions: list[PurchaseChatTurnDecision] | None = None,
) -> ScriptedAssistant:
    return ScriptedAssistant(decisions)


def _review_decision(
    *,
    supplier: PurchaseChatSupplierResolutionDecision | None = None,
    lines: list[PurchaseChatLineResolutionDecision] | None = None,
    accept_current_resolution: bool = False,
) -> PurchaseChatTurnDecision:
    return PurchaseChatTurnDecision(
        action="review_resolution",
        resolution=PurchaseChatResolutionDecision(
            supplier=supplier,
            lines=lines or [],
            accept_current_resolution=accept_current_resolution,
        ),
    )


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
    assistant = _test_assistant(
        [
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(
                    action="select_candidate",
                    partner_id=102,
                )
            ),
            PurchaseChatTurnDecision(action="confirm_invoice"),
            PurchaseChatTurnDecision(action="confirm_stock"),
            PurchaseChatTurnDecision(action="confirm_prices"),
        ]
    )

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    first = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="molinos_1.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
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
    assert assistant.reply_requests[-1].event == "price_applied"


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
    assistant = _test_assistant(
        [
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(
                    action="select_candidate",
                    partner_id=102,
                )
            ),
            PurchaseChatTurnDecision(action="confirm_invoice"),
            PurchaseChatTurnDecision(action="reject_prices"),
        ]
    )

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="aca va",
            attachments=[
                InvoiceAttachment(
                    filename="jambo_2.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
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
    assert assistant.reply_requests[-1].event == "price_rejected"


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
    assistant = _test_assistant(
        [
            _review_decision(
                lines=[
                    PurchaseChatLineResolutionDecision(
                        line_number=1,
                        action="mark_new",
                    )
                ]
            ),
            _review_decision(accept_current_resolution=True),
        ]
    )

    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            attachments=[
                InvoiceAttachment(
                    filename="nuevo.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
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
    assert assistant.reply_requests[-1].event == "resolution_blocked"


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

    assistant = _test_assistant()
    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="supplier-only.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert uploaded.stage == "awaiting_resolution"
    assert assistant.reply_requests[-1].event == "analysis_requires_resolution"
    assert assistant.reply_requests[-1].proposal is not None
    assert assistant.reply_requests[-1].proposal.supplier_resolution is not None
    assert assistant.reply_requests[-1].proposal.supplier_resolution.status == "missing"
    assert all(
        line.product_resolution.status in {"exact", "manual"}
        for line in assistant.reply_requests[-1].proposal.lines
    )


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

    assistant = _test_assistant()
    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="lines-only.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert uploaded.stage == "awaiting_resolution"
    assert assistant.reply_requests[-1].event == "analysis_requires_resolution"
    assert assistant.reply_requests[-1].proposal is not None
    assert assistant.reply_requests[-1].proposal.supplier_resolution is not None
    assert assistant.reply_requests[-1].proposal.supplier_resolution.status == "exact"
    assert assistant.reply_requests[-1].proposal.lines[0].product_resolution.status == "missing"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_snapshots_are_stable_between_turns(
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

    assistant = _test_assistant(
        [
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(
                    action="select_candidate",
                    partner_id=900,
                ),
                lines=[
                    PurchaseChatLineResolutionDecision(
                        line_number=1,
                        action="select_candidate",
                        product_id=901,
                    )
                ],
            )
        ]
    )
    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
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
            message="dejá proveedor 900 y línea 1 con 901",
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

    assistant = _test_assistant(
        [
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(action="mark_new"),
                lines=[
                    PurchaseChatLineResolutionDecision(
                        line_number=1,
                        action="mark_new",
                    )
                ],
            ),
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(action="create_missing"),
                lines=[
                    PurchaseChatLineResolutionDecision(
                        line_number=1,
                        action="create_missing",
                    )
                ],
            ),
            PurchaseChatTurnDecision(action="confirm_invoice"),
        ]
    )
    service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="nuevo-completo.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
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
            message="marcá proveedor y producto como nuevos",
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
            message="crealos en odoo",
            context=PurchaseChatContext(
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )
    assert created.stage == "awaiting_invoice_confirmation"
    assert assistant.reply_requests[-1].event == "resolution_ready_for_invoice_confirmation"
    assert assistant.reply_requests[-1].details["created_summary"] is not None
    assert created.proposal is not None
    assert created.proposal.supplier_resolution is not None
    assert created.proposal.supplier_resolution.selected_partner_id is not None
    assert created.proposal.lines[0].product_resolution.selected_product_id is not None

    billed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="cargala",
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
    assistant = _test_assistant(
        [
            _review_decision(
                supplier=PurchaseChatSupplierResolutionDecision(
                    action="select_candidate",
                    partner_id=900,
                ),
                lines=[
                    PurchaseChatLineResolutionDecision(
                        line_number=1,
                        action="select_candidate",
                        product_id=901,
                    )
                ],
            ),
            PurchaseChatTurnDecision(action="confirm_invoice"),
        ]
    )
    service = PurchaseChatService(
        odoo=DryRunOdooClient(
            invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
            resolution_memory=memory,
        ),
        assistant=assistant,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            attachments=[
                InvoiceAttachment(
                    filename="alias.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"image-does-not-matter",
                )
            ],
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
            message="tomá proveedor 900 y producto 901",
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
            message="cargala",
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
