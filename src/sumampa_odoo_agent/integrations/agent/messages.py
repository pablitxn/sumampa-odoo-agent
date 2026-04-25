"""Message formatting for agent runtime requests."""

from __future__ import annotations

import json
from typing import Any

from sumampa_odoo_agent.integrations.agent.framework import _ensure_agent_framework_version
from sumampa_odoo_agent.services.models.attachments import PreparedAttachmentArtifact


def _build_agent_message(
    *,
    prompt: str,
    context: dict[str, Any],
    attachments: list[PreparedAttachmentArtifact] | None = None,
) -> Any:
    text_message = _build_text_message(prompt=prompt, context=context)
    if not attachments:
        return text_message

    Content, Message = _load_agent_message_types()
    contents: list[Any] = []
    if text_message:
        contents.append(Content.from_text(text_message))
    for artifact in attachments:
        contents.append(_build_attachment_content(Content, artifact))
    return Message("user", contents)


def _build_text_message(
    *,
    prompt: str,
    context: dict[str, Any],
) -> str:
    if not context:
        return prompt
    context_message = (
        "JSON context:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )
    if not prompt:
        return context_message
    return (
        f"{prompt}\n\n"
        f"{context_message}"
    )


def _load_agent_message_types() -> tuple[type[Any], type[Any]]:
    import agent_framework

    _ensure_agent_framework_version(agent_framework)
    from agent_framework._types import Content, Message

    return Content, Message


def _build_attachment_content(Content: type[Any], artifact: PreparedAttachmentArtifact) -> Any:
    if artifact.kind == "text":
        return Content.from_text(
            f"Attachment text ({artifact.filename}):\n{artifact.text or ''}",
        )

    content_bytes = artifact.content_bytes
    if content_bytes is None:
        raise ValueError(f"attachment artifact {artifact.artifact_id} has no bytes")

    additional_properties = {"filename": artifact.filename}
    if artifact.kind == "image":
        additional_properties["detail"] = "auto"
    return Content.from_data(
        data=content_bytes,
        media_type=artifact.content_type,
        additional_properties=additional_properties,
    )
