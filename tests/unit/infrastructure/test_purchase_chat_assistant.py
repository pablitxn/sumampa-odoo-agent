"""Unit tests for purchase chat assistant backends."""

from __future__ import annotations

from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    StubPurchaseChatAssistant,
)


async def test_stub_purchase_chat_assistant_handles_greeting() -> None:
    assistant = StubPurchaseChatAssistant()

    decision = await assistant.plan(
        stage="awaiting_invoice",
        proposal_summary=None,
        user_message="ey como va?",
    )

    assert decision.intent == "greet"
    assert "factura" in decision.assistant_message.lower()
