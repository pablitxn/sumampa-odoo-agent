"""Unit tests for agent tool registry behavior."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from sumampa_odoo_agent.integrations.agent_tools import build_agent_tools
from sumampa_odoo_agent.integrations.odoo_client import DryRunOdooClient

AgentTool = Callable[..., Awaitable[dict[str, Any]]]


def test_build_agent_tools_uses_registry_names() -> None:
    tools = build_agent_tools(odoo=DryRunOdooClient())
    names = {tool.__name__ for tool in tools}

    assert "explain_capabilities" in names
    assert "search_partners" in names
    assert "validate_argentina_invoice_draft" in names
    assert "create_delivery" in names


@pytest.mark.asyncio
async def test_registry_tool_delegates_to_odoo_gateway() -> None:
    tools = {tool.__name__: tool for tool in build_agent_tools(odoo=DryRunOdooClient())}
    create_product = cast(AgentTool, tools["create_product"])

    result = await create_product(name="Termo acero", default_code="TERMO-ACERO", list_price=45.0)

    assert result["mode"] == "dry-run"
    assert result["model"] == "product.template"
    assert result["payload"]["name"] == "Termo acero"
