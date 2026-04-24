"""Compatibility exports for Odoo gateway implementations."""

from __future__ import annotations

from sumampa_odoo_agent.integrations.odoo_dry_run import DryRunOdooClient
from sumampa_odoo_agent.integrations.odoo_jsonrpc import OdooJsonRpcClient

__all__ = ["DryRunOdooClient", "OdooJsonRpcClient"]
