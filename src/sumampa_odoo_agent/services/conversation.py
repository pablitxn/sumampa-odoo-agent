"""Conversation service used by the WhatsApp-facing bridge API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.contracts import AgentRuntime
from sumampa_odoo_agent.services.models.attachments import AttachmentSource
from sumampa_odoo_agent.services.models.runtime import (
    AgentRunInput,
    ConversationRuntimeContext,
    TransportContext,
)


@dataclass(slots=True)
class ConversationTurnInput:
    conversation_id: str
    channel: str
    user_id: str
    text: str
    attachments: list[AttachmentSource]
    context: dict[str, Any]


@dataclass(slots=True)
class ConversationTurnResult:
    conversation_id: str
    assistant_text: str


class ConversationService:
    """Service that normalizes transport events before delegating to the agent runtime."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        attachment_ingestion: AttachmentIngestionService,
    ) -> None:
        self._runtime = runtime
        self._attachment_ingestion = attachment_ingestion

    async def run_turn(self, request: ConversationTurnInput) -> ConversationTurnResult:
        prepared_attachments = await self._attachment_ingestion.prepare_attachments(
            request.attachments,
            conversation_id=request.conversation_id,
            channel=request.channel,
            user_id=request.user_id,
        )
        context = ConversationRuntimeContext(
            transport=TransportContext(
                channel=request.channel,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
            ),
            context=request.context,
            attachments=[
                prepared_attachment.to_runtime_manifest()
                for prepared_attachment in prepared_attachments
            ],
        )

        result = await self._runtime.run(
            AgentRunInput(
                prompt=request.text.strip(),
                context=context,
                attachments=[
                    artifact
                    for prepared_attachment in prepared_attachments
                    for artifact in prepared_attachment.artifacts
                ],
                session_id=request.conversation_id,
            )
        )

        return ConversationTurnResult(
            conversation_id=result.session_id,
            assistant_text=result.text,
        )
