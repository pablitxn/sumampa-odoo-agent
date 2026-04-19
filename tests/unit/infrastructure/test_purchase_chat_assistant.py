"""Unit tests for the OpenAI purchase chat assistant."""

from __future__ import annotations

from types import SimpleNamespace

from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatReply,
    PurchaseChatReplyRequest,
    PurchaseChatTurnDecision,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    OpenAIPurchaseChatAssistant,
)


class _FakeResponses:
    def __init__(self, parsed_decision: PurchaseChatTurnDecision, parsed_reply: PurchaseChatReply) -> None:
        self.calls: list[dict[str, object]] = []
        self._parsed_decision = parsed_decision
        self._parsed_reply = parsed_reply

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        text_format = kwargs["text_format"]
        parsed = self._parsed_decision if text_format is PurchaseChatTurnDecision else self._parsed_reply
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(parsed=parsed)],
                )
            ]
        )


class _FakeClient:
    def __init__(self, parsed_decision: PurchaseChatTurnDecision, parsed_reply: PurchaseChatReply) -> None:
        self.responses = _FakeResponses(parsed_decision, parsed_reply)


async def test_openai_purchase_chat_assistant_interprets_and_renders_structured_turns() -> None:
    parsed_decision = PurchaseChatTurnDecision(action="await_invoice")
    parsed_reply = PurchaseChatReply(assistant_message="Subime la factura cuando quieras.")
    fake_client = _FakeClient(parsed_decision, parsed_reply)
    assistant = OpenAIPurchaseChatAssistant(
        model="gpt-5.4",
        api_key_env_var="OPENAI_API_KEY",
        client=fake_client,  # type: ignore[arg-type]
    )

    decision = await assistant.decide(
        stage="awaiting_invoice",
        user_message="ey como va?",
        proposal=None,
        last_apply_result=None,
    )
    reply = await assistant.reply(
        PurchaseChatReplyRequest(
            stage="awaiting_invoice",
            event="awaiting_invoice",
            user_message="ey como va?",
        )
    )

    assert decision == parsed_decision
    assert reply == "Subime la factura cuando quieras."
    assert fake_client.responses.calls[0]["model"] == "gpt-5.4"
    assert fake_client.responses.calls[0]["text_format"] is PurchaseChatTurnDecision
    assert fake_client.responses.calls[1]["text_format"] is PurchaseChatReply
