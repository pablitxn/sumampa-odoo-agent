"""Integration builders and adapters."""

from sumampa_odoo_agent.integrations.agent_runtime import build_agent_runtime
from sumampa_odoo_agent.integrations.extraction import build_invoice_extractor
from sumampa_odoo_agent.integrations.odoo import build_odoo_gateway
from sumampa_odoo_agent.integrations.session_store import build_session_store

__all__ = [
    "build_agent_runtime",
    "build_invoice_extractor",
    "build_odoo_gateway",
    "build_session_store",
]
