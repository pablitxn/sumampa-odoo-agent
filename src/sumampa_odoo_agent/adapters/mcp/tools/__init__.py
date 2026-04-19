"""Dynamic MCP tool registry."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module

from sumampa_odoo_agent.adapters.mcp.tools.common import ToolSpec

TOOL_MODULES: dict[str, str] = {
    "agent": "sumampa_odoo_agent.adapters.mcp.tools.agent",
    "odoo": "sumampa_odoo_agent.adapters.mcp.tools.odoo",
}


def load_tool_specs(enabled_modules: Iterable[str]) -> list[ToolSpec]:
    """Load tool specs for enabled modules only."""
    specs: list[ToolSpec] = []
    for module_name in sorted(set(enabled_modules)):
        module_path = TOOL_MODULES.get(module_name)
        if module_path is None:
            continue
        module = import_module(module_path)
        module_specs: list[ToolSpec] = getattr(module, "get_tool_specs", lambda: [])()
        specs.extend(module_specs)
    return specs


__all__ = ["ToolSpec", "load_tool_specs"]
