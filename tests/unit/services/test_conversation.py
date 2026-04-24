"""Unit tests for the conversation service."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.services.conversation import ConversationService, ConversationTurnInput
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult


class _FakeRuntime:
    def __init__(self) -> None:
        self.last_call: dict[str, object] | None = None

    async def run(self, request: AgentRunInput) -> AgentRunResult:
        self.last_call = {
            "prompt": request.prompt,
            "context": request.context.to_agent_context(),
            "session_id": request.session_id,
        }
        return AgentRunResult(
            mode="test",
            session_id=request.session_id or "generated-session",
            text="Seguimos con el pedido.",
        )


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
                    filename="adjunto.jpg",
                    content_type="image/jpeg",
                    content_bytes=b"fake-image",
                )
            ],
            context={"customer_name": "Sumampa SRL"},
        )
    )

    assert result.conversation_id == "conv-1"
    assert result.assistant_text == "Seguimos con el pedido."
    assert runtime.last_call is not None
    assert runtime.last_call["prompt"] == "Hay un adjunto del usuario. Decime qué necesitás para seguir."
    runtime_context = runtime.last_call["context"]
    assert isinstance(runtime_context, dict)
    assert runtime_context["transport"]["channel"] == "whatsapp"
    assert runtime_context["context"]["customer_name"] == "Sumampa SRL"
    assert len(runtime_context["attachments"]) == 1
