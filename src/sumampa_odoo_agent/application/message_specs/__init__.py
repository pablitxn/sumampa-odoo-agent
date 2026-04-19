"""Versioned non-LLM message catalogs for domain copy."""

from sumampa_odoo_agent.application.message_specs.loader import (
    load_message_catalog,
    render_message,
    resolve_message_catalog_path,
)

__all__ = ["load_message_catalog", "render_message", "resolve_message_catalog_path"]
