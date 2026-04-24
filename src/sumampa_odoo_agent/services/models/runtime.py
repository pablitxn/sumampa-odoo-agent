"""Typed runtime contracts shared by conversation and agent integrations."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias, cast, get_args

from pydantic import BaseModel, Field

from sumampa_odoo_agent.services.models.odoo import OdooMutationPlan

WorkflowStage: TypeAlias = Literal[
    "idle",
    "awaiting_invoice_confirmation",
    "awaiting_price_confirmation",
    "awaiting_resolution",
]

DEFAULT_WORKFLOW_STAGE: WorkflowStage = "idle"
_WORKFLOW_STAGES = set(get_args(WorkflowStage))


class SerializedInvoiceAttachment(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    content_base64: str = Field(min_length=1)


class TransportContext(BaseModel):
    channel: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)


class ConversationRuntimeContext(BaseModel):
    transport: TransportContext
    context: dict[str, Any] = Field(default_factory=dict)
    attachments: list[SerializedInvoiceAttachment] = Field(default_factory=list)

    def to_agent_context(self) -> dict[str, Any]:
        return self.model_dump(exclude_defaults=True)


class AgentRunInput(BaseModel):
    prompt: str
    context: ConversationRuntimeContext
    session_id: str | None = None


class AgentRunResult(BaseModel):
    mode: str
    session_id: str
    text: str
    stage: WorkflowStage = DEFAULT_WORKFLOW_STAGE
    operations: list[OdooMutationPlan] | None = None


def normalize_workflow_stage(value: object) -> WorkflowStage:
    if isinstance(value, str) and value in _WORKFLOW_STAGES:
        return cast(WorkflowStage, value)
    return DEFAULT_WORKFLOW_STAGE
