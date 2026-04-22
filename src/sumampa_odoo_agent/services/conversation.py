"""Conversation service used by the WhatsApp-facing bridge API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sumampa_odoo_agent.services.attachments import serialize_invoice_attachments
from sumampa_odoo_agent.services.contracts import AgentRuntime
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment, OdooMutationPlan


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
    stage: str
    operations: list[OdooMutationPlan] | None


class ConversationService:
    """Service that normalizes transport events before delegating to the agent runtime."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def run_turn(self, request: ConversationTurnInput) -> ConversationTurnResult:
        context: dict[str, Any] = {
            "transport": {
                "channel": request.channel,
                "user_id": request.user_id,
                "conversation_id": request.conversation_id,
            }
        }
        if request.context:
            context["context"] = request.context
        if request.attachments:
            context["attachments"] = serialize_invoice_attachments(request.attachments)

        result = await self._runtime.run(
            prompt=_conversation_prompt(
                text=request.text,
                has_attachments=bool(request.attachments),
            ),
            session_id=request.conversation_id,
            context=context,
        )

        raw_operations = result.get("operations")
        operations = None
        if isinstance(raw_operations, list):
            operations = [OdooMutationPlan.model_validate(item) for item in raw_operations]

        return ConversationTurnResult(
            conversation_id=str(result.get("session_id") or request.conversation_id),
            assistant_text=str(result.get("text") or ""),
            stage=str(result.get("stage") or "idle"),
            operations=operations,
        )


def _conversation_prompt(*, text: str, has_attachments: bool) -> str:
    normalized = text.strip()
    if normalized:
        return normalized
    if has_attachments:
        return "Hay un adjunto del usuario. Decime qué necesitás para seguir."
    return "Seguimos con el contexto actual y pedí sólo la información mínima necesaria."
