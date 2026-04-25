"""Unit tests for agent message serialization."""

from __future__ import annotations

from sumampa_odoo_agent.integrations.agent.messages import _build_agent_message
from sumampa_odoo_agent.services.models.attachments import PreparedAttachmentArtifact


def test_build_agent_message_uses_context_only_when_prompt_is_empty() -> None:
    message = _build_agent_message(
        prompt="",
        context={"attachments": [{"filename": "attachment.jpg"}]},
    )

    assert message.startswith("JSON context:\n")
    assert "attachment.jpg" in message


def test_build_agent_message_includes_prompt_when_present() -> None:
    message = _build_agent_message(
        prompt="review the products",
        context={"transport": {"channel": "whatsapp"}},
    )

    assert message.startswith("review the products\n\nJSON context:\n")
    assert "whatsapp" in message


def test_build_agent_message_uses_native_framework_content_for_attachments() -> None:
    message = _build_agent_message(
        prompt="mirá esto",
        context={"attachments": [{"filename": "attachment.jpg"}]},
        attachments=[
            PreparedAttachmentArtifact(
                artifact_id="artifact-1",
                source_attachment_id="attachment-1",
                kind="image",
                filename="attachment.jpg",
                content_type="image/jpeg",
                content_bytes=b"fake-image",
            )
        ],
    )

    assert message.role == "user"
    assert message.contents[0].type == "text"
    assert message.contents[1].type == "data"
    assert message.contents[1].media_type == "image/jpeg"
