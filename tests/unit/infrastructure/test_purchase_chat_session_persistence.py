from __future__ import annotations

from pathlib import Path

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
    InvoiceAttachment,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
    PurchaseChatReplyRequest,
    PurchaseChatResolutionDecision,
    PurchaseChatSupplierResolutionDecision,
    PurchaseChatTurnDecision,
)
from sumampa_odoo_agent.infrastructure.db.session_store import InMemorySessionStore
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient
from sumampa_odoo_agent.infrastructure.purchase_chat.service import PurchaseChatService

SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "integration" / "fixtures" / "purchase_invoice_extractions"


class SnapshotPurchaseInvoiceExtractor:
    def __init__(self, extracted: ExtractedPurchaseInvoiceDocument) -> None:
        self._extracted = extracted

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        del command
        return self._extracted


class FakeAssistant:
    async def decide(
        self,
        *,
        stage: str,
        user_message: str,
        proposal,
        last_apply_result,
    ) -> PurchaseChatTurnDecision:
        del user_message, proposal, last_apply_result
        if stage == "awaiting_resolution":
            return PurchaseChatTurnDecision(
                action="review_resolution",
                resolution=PurchaseChatResolutionDecision(
                    supplier=PurchaseChatSupplierResolutionDecision(
                        action="select_candidate",
                        partner_id=102,
                    )
                ),
            )
        if stage == "awaiting_invoice_confirmation":
            return PurchaseChatTurnDecision(action="confirm_invoice")
        return PurchaseChatTurnDecision(action="await_invoice")

    async def reply(self, request: PurchaseChatReplyRequest) -> str:
        return f"event={request.event}"


def _load_snapshot(path: Path) -> ExtractedPurchaseInvoiceDocument:
    import json

    return ExtractedPurchaseInvoiceDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


@pytest.mark.asyncio
async def test_purchase_chat_service_restores_session_from_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = _load_snapshot(SNAPSHOTS_DIR / "molinos_1.json")
    monkeypatch.setattr(
        DryRunOdooClient,
        "_products",
        [
            {
                "id": 2001,
                "display_name": extracted.lines[0].description,
                "default_code": "PERSIST-1",
                "list_price": 150.0,
                "standard_price": 100.0,
            }
        ],
    )
    store = InMemorySessionStore()

    first_service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=FakeAssistant(),  # type: ignore[arg-type]
        session_store=store,
    )
    uploaded = await first_service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso una factura",
            attachments=[
                InvoiceAttachment(
                    filename="molinos_1.jpg",
                    content_type="image/jpeg",
                    content_bytes=b"test-image",
                )
            ],
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    second_service = PurchaseChatService(
        odoo=DryRunOdooClient(invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted)),
        assistant=FakeAssistant(),  # type: ignore[arg-type]
        session_store=store,
    )
    resolved = await second_service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="dejá proveedor 102",
            context=PurchaseChatContext(
                supplier_id=102,
                journal_id=301,
                markup_percentage=30.0,
            ),
        )
    )

    assert uploaded.stage == "awaiting_resolution"
    assert resolved.stage == "awaiting_invoice_confirmation"
    assert resolved.session_id == uploaded.session_id
