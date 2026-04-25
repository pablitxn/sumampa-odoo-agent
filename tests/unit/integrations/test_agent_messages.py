"""Unit tests for agent message serialization."""

from __future__ import annotations

from sumampa_odoo_agent.integrations.agent.messages import _build_agent_message


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
