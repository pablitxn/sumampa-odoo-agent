"""Typed runtime contracts shared by conversation and agent integrations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sumampa_odoo_agent.services.models.attachments import (
    AttachmentRuntimeManifest,
    PreparedAttachmentArtifact,
)


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
    attachments: list[AttachmentRuntimeManifest] = Field(default_factory=list)

    def to_agent_context(self) -> dict[str, Any]:
        return self.model_dump(exclude_defaults=True)


class AgentRunInput(BaseModel):
    prompt: str
    context: ConversationRuntimeContext
    attachments: list[PreparedAttachmentArtifact] = Field(default_factory=list)
    session_id: str | None = None


class AgentRunResult(BaseModel):
    mode: str
    session_id: str
    text: str
