"""Conversation service used by the WhatsApp-facing bridge API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from sumampa_odoo_agent.services.attachments import serialize_invoice_attachments
from sumampa_odoo_agent.services.contracts import AgentRuntime
from sumampa_odoo_agent.services.models.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    InvoiceAttachment,
    PurchaseInvoiceProposalResult,
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
    stage: str
    proposal: PurchaseInvoiceProposalResult | None
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None


class ConversationService:
    """Service that normalizes transport events before delegating to the agent runtime."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def run_turn(self, request: ConversationTurnInput) -> ConversationTurnResult:
        result = await self._runtime.run(
            prompt=_conversation_prompt(
                text=request.text,
                has_attachments=bool(request.attachments),
            ),
            session_id=request.conversation_id,
            context={
                "transport": {
                    "channel": request.channel,
                    "user_id": request.user_id,
                    "conversation_id": request.conversation_id,
                },
                "purchase_workflow": {
                    "context": request.context,
                    "attachments": serialize_invoice_attachments(request.attachments),
                },
            },
        )

        purchase_flow = result.get("purchase_flow")
        if not isinstance(purchase_flow, dict):
            purchase_flow = {
                "stage": "awaiting_invoice",
                "proposal": None,
                "last_apply_result": None,
            }

        return ConversationTurnResult(
            conversation_id=str(result.get("session_id") or request.conversation_id),
            assistant_text=str(result.get("text") or ""),
            stage=str(purchase_flow.get("stage") or "awaiting_invoice"),
            proposal=_as_model(PurchaseInvoiceProposalResult, purchase_flow.get("proposal")),
            last_apply_result=_as_model(
                ApplyPurchaseInvoiceProposalResult,
                purchase_flow.get("last_apply_result"),
            ),
        )


def _conversation_prompt(*, text: str, has_attachments: bool) -> str:
    normalized = text.strip()
    if normalized:
        return normalized
    if has_attachments:
        return "Analizá la factura adjunta y guiame con el siguiente paso."
    return (
        "Seguimos con la factura activa si existe una. "
        "Si no hay una activa, pedí la factura y sólo el contexto mínimo necesario."
    )


ModelT = TypeVar("ModelT", bound=BaseModel)


def _as_model(model_type: type[ModelT], payload: object) -> ModelT | None:
    if payload is None:
        return None
    if isinstance(payload, model_type):
        return payload
    return model_type.model_validate(payload)
