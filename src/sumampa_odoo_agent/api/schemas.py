"""Public API schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EvalTag = Annotated[str, Field(min_length=1, max_length=200)]


def _normalize_eval_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_tags = [value]
    elif isinstance(value, list):
        raw_tags = value
    else:
        raise ValueError("eval_tags must be a list of strings")

    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise ValueError("eval_tags must be a list of strings")
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)
    return tags


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
    eval_tags: list[EvalTag] = Field(default_factory=list)

    @field_validator("eval_tags", mode="before")
    @classmethod
    def normalize_eval_tags(cls, value: object) -> list[str]:
        return _normalize_eval_tags(value)


class ConversationTagsRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    eval_tags: list[EvalTag] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("eval_tags", mode="before")
    @classmethod
    def normalize_eval_tags(cls, value: object) -> list[str]:
        return _normalize_eval_tags(value)


class ConversationTagsResponse(BaseModel):
    conversation_id: str
    eval_tags: list[EvalTag] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str


class ConversationMessageResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(min_length=1)


class DemoSalesMessageRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    text: str = ""
    scenario_id: str = Field(min_length=1)
    scenario_params: dict[str, str] = Field(default_factory=dict)
    channel: str = Field(default="whatsapp", min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    eval_tags: list[EvalTag] = Field(default_factory=list)

    @field_validator("eval_tags", mode="before")
    @classmethod
    def normalize_eval_tags(cls, value: object) -> list[str]:
        return _normalize_eval_tags(value)


class DemoSalesMessageResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(min_length=1)
    scenario: dict[str, Any]
    state: dict[str, Any]
    recent_tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class DemoSalesConversationTagsRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    eval_tags: list[EvalTag] = Field(default_factory=list)
    scenario_id: str | None = None
    scenario_params: dict[str, str] = Field(default_factory=dict)
    channel: str = Field(default="whatsapp", min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("eval_tags", mode="before")
    @classmethod
    def normalize_eval_tags(cls, value: object) -> list[str]:
        return _normalize_eval_tags(value)


class DemoSalesScenariosResponse(BaseModel):
    catalog_version: str
    params: dict[str, Any]
    scenarios: list[dict[str, Any]]


class DemoSalesResetResponse(BaseModel):
    conversation_id: str
    reset: bool


class DemoSalesFeedbackRequest(BaseModel):
    user_id: str = Field(min_length=1)
    feedback_tags: list[EvalTag] = Field(default_factory=list)
    feedback_text: str = ""
    channel: str = Field(default="whatsapp", min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feedback_tags", mode="before")
    @classmethod
    def normalize_feedback_tags(cls, value: object) -> list[str]:
        return _normalize_eval_tags(value)


class DemoSalesFeedbackResponse(BaseModel):
    conversation_id: str
    feedback_tags: list[EvalTag] = Field(default_factory=list)
    feedback_count: int
