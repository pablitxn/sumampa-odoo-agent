"""Agent tool registry."""

from __future__ import annotations

from typing import Any

from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.tools.odoo import build_odoo_tools


def build_agent_tools(*, odoo: OdooGateway | None) -> list[Any]:
    if odoo is None:
        return []
    return build_odoo_tools(odoo)
