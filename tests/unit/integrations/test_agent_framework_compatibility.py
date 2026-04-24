from __future__ import annotations

from typing import Any, cast

import agent_framework
import pytest

from sumampa_odoo_agent.integrations.agent.framework import (
    _load_agent_session_type,
    _load_agent_type,
    _load_openai_chat_client,
)


def test_load_agent_session_type_patches_broken_top_level_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(agent_framework, "__version__", raising=False)
    monkeypatch.delattr(agent_framework, "AgentSession", raising=False)

    _load_openai_chat_client()
    _load_agent_type()
    AgentSession = _load_agent_session_type()

    assert cast(Any, agent_framework).AgentSession is AgentSession
    assert AgentSession(session_id="agent-compat").to_dict()["session_id"] == "agent-compat"
