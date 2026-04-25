"""E2E smoke tests for agent-facing conversation flows."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.integrations.agent import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult


def _image_attachment(filename: str = "attachment.jpg") -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": "image/jpeg",
        "content_base64": base64.b64encode(b"fake-image").decode("ascii"),
    }


@pytest.fixture(autouse=True)
def patch_runtime_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_messages_endpoint_delegates_to_agent() -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        context = request.context.to_agent_context()
        assert request.prompt == "review the products"
        assert context["transport"]["channel"] == "whatsapp"
        assert context["transport"]["user_id"] == "5491112345678"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=request.session_id or "conversation-1",
            text="I found 2 pending products to review.",
        )

    app = create_app()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "conversation-1",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "text": "review the products",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "conversation-1"
    assert payload["messages"][0]["text"] == "I found 2 pending products to review."


def test_messages_endpoint_serializes_attachments_for_agent() -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        context = request.context.to_agent_context()
        assert request.prompt == ""
        attachments = context["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "attachment.jpg"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id="attachment-session",
            text="Send me the next confirmation.",
        )

    app = create_app()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "attachment-session",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "attachments": [_image_attachment()],
                    "context": {"customer_name": "Sumampa SRL"},
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["text"] == "Send me the next confirmation."
