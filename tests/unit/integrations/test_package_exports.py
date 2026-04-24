"""Unit tests for canonical integration package exports."""

from __future__ import annotations

from sumampa_odoo_agent.integrations import (
    build_agent_runtime,
    build_odoo_gateway,
    build_session_store,
)
from sumampa_odoo_agent.integrations.agent import MicrosoftAgentFrameworkOpenAIService
from sumampa_odoo_agent.integrations.agent.llm_specs import load_llm_spec
from sumampa_odoo_agent.integrations.odoo import DryRunOdooClient, OdooJsonRpcClient
from sumampa_odoo_agent.integrations.sessions import InMemorySessionStore


def test_top_level_builders_resolve_from_canonical_packages() -> None:
    assert build_agent_runtime.__module__ == "sumampa_odoo_agent.integrations.agent.runtime"
    assert build_odoo_gateway.__module__ == "sumampa_odoo_agent.integrations.odoo.factory"
    assert build_session_store.__module__ == "sumampa_odoo_agent.integrations.sessions.factory"


def test_canonical_package_exports_are_available() -> None:
    assert MicrosoftAgentFrameworkOpenAIService.__name__ == "MicrosoftAgentFrameworkOpenAIService"
    assert DryRunOdooClient.__name__ == "DryRunOdooClient"
    assert OdooJsonRpcClient.__name__ == "OdooJsonRpcClient"
    assert InMemorySessionStore.__name__ == "InMemorySessionStore"


def test_default_agent_prompt_still_loads_after_package_move() -> None:
    prompt = load_llm_spec("agent/system.md")

    assert "Sos el asistente operativo de Sumampa para Odoo." in prompt
