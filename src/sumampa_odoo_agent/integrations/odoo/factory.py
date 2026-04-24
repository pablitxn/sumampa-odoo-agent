"""Odoo gateway builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.odoo.dry_run import DryRunOdooClient
from sumampa_odoo_agent.integrations.odoo.jsonrpc import OdooJsonRpcClient
from sumampa_odoo_agent.services.contracts import OdooGateway
from sumampa_odoo_agent.services.errors import ConfigurationError


def build_odoo_gateway(
    settings: AppSettings,
) -> OdooGateway:
    """Build the configured Odoo gateway."""

    if settings.odoo.mode == "jsonrpc":
        return OdooJsonRpcClient(
            base_url=settings.odoo.base_url,
            database=settings.odoo.database,
            username=settings.odoo.username,
            password=settings.odoo.password,
            timeout_seconds=settings.odoo.timeout_seconds,
        )
    if settings.odoo.mode == "dry-run":
        return DryRunOdooClient()
    raise ConfigurationError(
        f"Unsupported odoo.mode: {settings.odoo.mode}",
        code="unsupported_odoo_mode",
    )
