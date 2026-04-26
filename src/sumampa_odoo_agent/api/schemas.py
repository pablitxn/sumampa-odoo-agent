"""Public API schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EvalTag = Annotated[str, Field(min_length=1, max_length=200)]


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


class ConversationMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str


class ConversationMessageResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(min_length=1)
