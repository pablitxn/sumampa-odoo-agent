"""Adapter layer exports."""

from sumampa_odoo_agent.adapters.api import app, create_app
from sumampa_odoo_agent.adapters.mcp import create_mcp_server, run_mcp_server

__all__ = ["app", "create_app", "create_mcp_server", "run_mcp_server"]
