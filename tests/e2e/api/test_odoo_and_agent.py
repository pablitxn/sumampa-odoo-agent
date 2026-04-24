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


def _image_attachment(filename: str = "adjunto.jpg") -> dict[str, str]:
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
        assert request.prompt == "revisá los productos"
        assert context["transport"]["channel"] == "whatsapp"
        assert context["transport"]["user_id"] == "5491112345678"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=request.session_id or "conversation-1",
            text="Te encontré 2 productos pendientes para revisar.",
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
                    "text": "revisá los productos",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "conversation-1"
    assert payload["messages"][0]["text"] == "Te encontré 2 productos pendientes para revisar."


def test_messages_endpoint_serializes_attachments_for_agent() -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        context = request.context.to_agent_context()
        assert request.prompt == "Hay un adjunto del usuario. Decime qué necesitás para seguir."
        attachments = context["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "adjunto.jpg"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id="attachment-session",
            text="Mandame la próxima confirmación.",
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
    assert payload["messages"][0]["text"] == "Mandame la próxima confirmación."
