"""Integration builders and adapters."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sumampa_odoo_agent.integrations.agent import build_agent_runtime
    from sumampa_odoo_agent.integrations.odoo import build_odoo_gateway
    from sumampa_odoo_agent.integrations.sessions import build_session_store

__all__ = [
    "build_agent_runtime",
    "build_odoo_gateway",
    "build_session_store",
]

_EXPORTS = {
    "build_agent_runtime": (
        "sumampa_odoo_agent.integrations.agent",
        "build_agent_runtime",
    ),
    "build_odoo_gateway": (
        "sumampa_odoo_agent.integrations.odoo",
        "build_odoo_gateway",
    ),
    "build_session_store": (
        "sumampa_odoo_agent.integrations.sessions",
        "build_session_store",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    return getattr(module, attr_name)
