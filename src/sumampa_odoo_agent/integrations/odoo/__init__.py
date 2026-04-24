"""Odoo integration adapters."""

from sumampa_odoo_agent.integrations.odoo.dry_run import DryRunOdooClient
from sumampa_odoo_agent.integrations.odoo.factory import build_odoo_gateway
from sumampa_odoo_agent.integrations.odoo.jsonrpc import OdooJsonRpcClient
from sumampa_odoo_agent.integrations.odoo.payloads import (
    delivery_payload,
    invoice_payload,
)
from sumampa_odoo_agent.integrations.odoo.validation import (
    validate_argentina_invoice_draft,
    validate_delivery_draft,
    validate_invoice_draft,
)

__all__ = [
    "DryRunOdooClient",
    "OdooJsonRpcClient",
    "build_odoo_gateway",
    "delivery_payload",
    "invoice_payload",
    "validate_argentina_invoice_draft",
    "validate_delivery_draft",
    "validate_invoice_draft",
]
