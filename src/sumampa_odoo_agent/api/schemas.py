"""Public API schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from sumampa_odoo_agent.services.models.odoo import OdooMutationPlan
from sumampa_odoo_agent.services.models.runtime import WorkflowStage


class AttachmentInput(BaseModel):
    filename: str = Field(min_length=1)
    mime_type: str | None = None
    content_base64: str | None = None
    download_url: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> AttachmentInput:
        if bool(self.content_base64) == bool(self.download_url):
            raise ValueError("provide exactly one of content_base64 or download_url")
        return self


class ConversationMessageRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    text: str = ""
    attachments: list[AttachmentInput] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str


class WorkflowStateResponse(BaseModel):
    stage: WorkflowStage


class ConversationMessageResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(min_length=1)
    workflow_state: WorkflowStateResponse
    operations: list[OdooMutationPlan] | None = None
