"""Unit tests for agent service helpers."""

from sumampa_odoo_agent.infrastructure.agent.service import _load_openai_chat_client


def test_load_openai_chat_client_handles_upstream_version_gap() -> None:
    client_cls = _load_openai_chat_client()
    assert client_cls.__name__ == "OpenAIChatClient"
