"""Unit tests for the OpenAI purchase chat assistant."""

from __future__ import annotations

from types import SimpleNamespace

from sumampa_odoo_agent.application.requests.purchase_chat import PurchaseChatPlannerDecision
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    OpenAIPurchaseChatAssistant,
)


class _FakeResponses:
    def __init__(self, parsed: PurchaseChatPlannerDecision) -> None:
        self.kwargs: dict[str, object] | None = None
        self._parsed = parsed

    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(parsed=self._parsed)],
                )
            ]
        )


class _FakeClient:
    def __init__(self, parsed: PurchaseChatPlannerDecision) -> None:
        self.responses = _FakeResponses(parsed)


async def test_openai_purchase_chat_assistant_uses_structured_parse() -> None:
    parsed = PurchaseChatPlannerDecision(
        intent="greet",
        assistant_message="Todo bien. Subime la factura cuando quieras.",
    )
    fake_client = _FakeClient(parsed)
    assistant = OpenAIPurchaseChatAssistant(
        model="gpt-5.4",
        api_key_env_var="OPENAI_API_KEY",
        client=fake_client,  # type: ignore[arg-type]
    )

    result = await assistant.plan(
        stage="awaiting_invoice",
        proposal_summary=None,
        user_message="ey como va?",
    )

    assert result == parsed
    assert fake_client.responses.kwargs is not None
    assert fake_client.responses.kwargs["model"] == "gpt-5.4"
    assert fake_client.responses.kwargs["text_format"] is PurchaseChatPlannerDecision
