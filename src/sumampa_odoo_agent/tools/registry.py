"""Agent tool registry."""

from __future__ import annotations

from typing import Any

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.tools.odoo import build_odoo_tools, odoo_tool_names


def _tool_names(*, include_odoo: bool) -> list[str]:
    names = ["explain_capabilities"]
    if include_odoo:
        names.extend(odoo_tool_names())
    return names


def build_agent_tools(*, odoo: OdooGateway | None) -> list[Any]:
    async def explain_capabilities() -> str:
        """Explain what this Sumampa Odoo agent can currently do."""
        names = ", ".join(_tool_names(include_odoo=odoo is not None))
        return (
            "I can explain the POC and, when the Odoo backend is enabled, run these tools: "
            f"{names}."
        )

    tools: list[Any] = [explain_capabilities]
    if odoo is not None:
        tools.extend(build_odoo_tools(odoo))
    return tools
