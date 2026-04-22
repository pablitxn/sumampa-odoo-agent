"""Odoo gateway builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.odoo_client import DryRunOdooClient, OdooJsonRpcClient
from sumampa_odoo_agent.integrations.purchase_resolution_memory import PurchaseResolutionMemoryStore
from sumampa_odoo_agent.services.contracts import InvoiceExtractor, OdooGateway


def build_odoo_gateway(
    settings: AppSettings,
    invoice_extractor: InvoiceExtractor,
) -> OdooGateway:
    """Build the configured Odoo gateway."""

    resolution_memory = PurchaseResolutionMemoryStore.from_env()
    if settings.odoo.mode == "jsonrpc":
        return OdooJsonRpcClient(
            base_url=settings.odoo.base_url,
            database=settings.odoo.database,
            username=settings.odoo.username,
            password=settings.odoo.password,
            timeout_seconds=settings.odoo.timeout_seconds,
            invoice_extractor=invoice_extractor,
            resolution_memory=resolution_memory,
        )
    if settings.odoo.mode == "dry-run":
        return DryRunOdooClient(
            invoice_extractor=invoice_extractor,
            resolution_memory=resolution_memory,
        )
    raise RuntimeError(f"Unsupported odoo.mode: {settings.odoo.mode}")
