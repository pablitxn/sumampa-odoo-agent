"""Unit tests for the conversation service."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.services.conversation import ConversationService, ConversationTurnInput
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment


class _FakeRuntime:
    def __init__(self) -> None:
        self.last_call: dict[str, object] | None = None

    async def run(
        self,
        *,
        prompt: str,
        context: dict[str, object],
        session_id: str | None = None,
    ) -> dict[str, object]:
        self.last_call = {
            "prompt": prompt,
            "context": context,
            "session_id": session_id,
        }
        return {
            "session_id": session_id,
            "text": "Seguimos con la factura.",
            "purchase_flow": {
                "stage": "awaiting_resolution",
                "proposal": None,
                "last_apply_result": None,
            },
        }


@pytest.mark.asyncio
async def test_conversation_service_builds_prompt_and_runtime_context() -> None:
    runtime = _FakeRuntime()
    service = ConversationService(runtime)

    result = await service.run_turn(
        ConversationTurnInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="5491112345678",
            text="",
            attachments=[
                InvoiceAttachment(
                    filename="factura.jpg",
                    content_type="image/jpeg",
                    content_bytes=b"fake-image",
                )
            ],
            context={"supplier_name": "Sumampa SRL"},
        )
    )

    assert result.conversation_id == "conv-1"
    assert result.assistant_text == "Seguimos con la factura."
    assert result.stage == "awaiting_resolution"
    assert runtime.last_call is not None
    assert runtime.last_call["prompt"] == "Analizá la factura adjunta y guiame con el siguiente paso."
    runtime_context = runtime.last_call["context"]
    assert isinstance(runtime_context, dict)
    assert runtime_context["transport"]["channel"] == "whatsapp"
    assert runtime_context["purchase_workflow"]["context"]["supplier_name"] == "Sumampa SRL"
    assert len(runtime_context["purchase_workflow"]["attachments"]) == 1
