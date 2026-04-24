from __future__ import annotations

from typing import Any, cast

import pytest

from sumampa_odoo_agent.integrations.agent_service import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.integrations.session_store_backends import InMemorySessionStore
from sumampa_odoo_agent.services.models.runtime import (
    AgentRunInput,
    ConversationRuntimeContext,
    TransportContext,
)


class FakeSession:
    def __init__(self, *, session_id: str | None = None) -> None:
        self._session_id = session_id or "generated-session"
        self.state: dict[str, object] = {}

    @property
    def session_id(self) -> str:
        return self._session_id

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self._session_id,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> FakeSession:
        session = cls(session_id=str(payload["session_id"]))
        session.state = cast(dict[str, Any], payload.get("state", {}))
        return session


class FakeAgent:
    def create_session(self, *, session_id: str | None = None) -> FakeSession:
        return FakeSession(session_id=session_id)

    async def run(self, message: str, *, session: FakeSession) -> object:
        history = list(cast(list[str], session.state.get("history", [])))
        history.append(message)
        session.state["history"] = history
        return type("Response", (), {"text": f"history={len(history)}"})()


class FakeChatClient:
    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        del model, api_key, base_url

    def as_agent(self, **kwargs: object) -> FakeAgent:
        del kwargs
        return FakeAgent()


def _agent_request(prompt: str, *, session_id: str) -> AgentRunInput:
    return AgentRunInput(
        prompt=prompt,
        session_id=session_id,
        context=ConversationRuntimeContext(
            transport=TransportContext(
                channel="test",
                user_id="user-1",
                conversation_id=session_id,
            )
        ),
    )


@pytest.mark.asyncio
async def test_agent_service_restores_framework_session_from_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sumampa_odoo_agent.integrations.agent_service._load_openai_chat_client",
        lambda: FakeChatClient,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.integrations.agent_service._load_agent_type",
        lambda: FakeAgent,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.integrations.agent_service._load_agent_session_type",
        lambda: FakeSession,
    )

    store = InMemorySessionStore()
    first_service = MicrosoftAgentFrameworkOpenAIService(
        model="gpt-5.4-mini",
        system_prompt="test",
        api_key_env_var="OPENAI_API_KEY",
        session_store=store,
    )
    first = await first_service.run(_agent_request("hola", session_id="agent-1"))

    second_service = MicrosoftAgentFrameworkOpenAIService(
        model="gpt-5.4-mini",
        system_prompt="test",
        api_key_env_var="OPENAI_API_KEY",
        session_store=store,
    )
    second = await second_service.run(_agent_request("seguimos", session_id="agent-1"))

    assert first.session_id == "agent-1"
    assert second.session_id == "agent-1"
    assert second.text == "history=2"
