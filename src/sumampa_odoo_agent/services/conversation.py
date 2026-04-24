"""Conversation service used by the WhatsApp-facing bridge API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sumampa_odoo_agent.services.attachments import serialize_invoice_attachments
from sumampa_odoo_agent.services.contracts import AgentRuntime
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment
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
    attachments: list[InvoiceAttachment]
    context: dict[str, Any]


@dataclass(slots=True)
class ConversationTurnResult:
    conversation_id: str
    assistant_text: str


class ConversationService:
    """Service that normalizes transport events before delegating to the agent runtime."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def run_turn(self, request: ConversationTurnInput) -> ConversationTurnResult:
        context = ConversationRuntimeContext(
            transport=TransportContext(
                channel=request.channel,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
            ),
            context=request.context,
            attachments=serialize_invoice_attachments(request.attachments),
        )

        result = await self._runtime.run(
            AgentRunInput(
                prompt=_conversation_prompt(
                    text=request.text,
                    has_attachments=bool(request.attachments),
                ),
                context=context,
                session_id=request.conversation_id,
            )
        )

        return ConversationTurnResult(
            conversation_id=result.session_id,
            assistant_text=result.text,
        )


def _conversation_prompt(*, text: str, has_attachments: bool) -> str:
    normalized = text.strip()
    if normalized:
        return normalized
    if has_attachments:
        return "Hay un adjunto del usuario. Decime qué necesitás para seguir."
    return "Seguimos con el contexto actual y pedí sólo la información mínima necesaria."
