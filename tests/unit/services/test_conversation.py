"""Unit tests for the conversation service."""

from __future__ import annotations

import base64

import pytest

from sumampa_odoo_agent.config import AttachmentSettings
from sumampa_odoo_agent.integrations.storage import InMemoryAttachmentObjectStore
from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.conversation import ConversationService, ConversationTurnInput
from sumampa_odoo_agent.services.models.attachments import AttachmentSource
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult


class _FakeRuntime:
    def __init__(self) -> None:
        self.last_call: dict[str, object] | None = None

    async def run(self, request: AgentRunInput) -> AgentRunResult:
        self.last_call = {
            "prompt": request.prompt,
            "context": request.context.to_agent_context(),
            "attachments": request.attachments,
            "session_id": request.session_id,
        }
        return AgentRunResult(
            mode="test",
            session_id=request.session_id or "generated-session",
            text="We are continuing with the request.",
        )


@pytest.mark.asyncio
async def test_conversation_service_passes_empty_text_and_runtime_context() -> None:
    runtime = _FakeRuntime()
    attachment_store = InMemoryAttachmentObjectStore()
    service = ConversationService(
        runtime,
        attachment_ingestion=AttachmentIngestionService(
            object_store=attachment_store,
            settings=AttachmentSettings(store_mode="memory"),
        ),
    )

    result = await service.run_turn(
        ConversationTurnInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="5491112345678",
            text="",
            attachments=[
                AttachmentSource(
                    filename="attachment.jpg",
                    content_type="image/jpeg",
                    content_base64=base64.b64encode(b"fake-image").decode("ascii"),
                )
            ],
            context={"customer_name": "Sumampa SRL"},
        )
    )

    assert result.conversation_id == "conv-1"
    assert result.assistant_text == "We are continuing with the request."
    assert runtime.last_call is not None
    assert runtime.last_call["prompt"] == ""
    runtime_context = runtime.last_call["context"]
    assert isinstance(runtime_context, dict)
    assert runtime_context["transport"]["channel"] == "whatsapp"
    assert runtime_context["context"]["customer_name"] == "Sumampa SRL"
    assert len(runtime_context["attachments"]) == 1
    assert runtime_context["attachments"][0]["storage_uri"].startswith("memory://")
    runtime_attachments = runtime.last_call["attachments"]
    assert isinstance(runtime_attachments, list)
    assert len(runtime_attachments) == 1
    assert runtime_attachments[0].kind == "image"
