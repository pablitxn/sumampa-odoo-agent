"""Invoice extraction builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.openai_extraction import OpenAIPurchaseInvoiceExtractor
from sumampa_odoo_agent.services.contracts import InvoiceExtractor


def build_invoice_extractor(settings: AppSettings) -> InvoiceExtractor:
    """Build the configured purchase invoice extractor."""

    if settings.invoice_extraction.mode == "openai":
        return OpenAIPurchaseInvoiceExtractor(
            model=settings.invoice_extraction.model,
            api_key_env_var=settings.invoice_extraction.api_key_env_var,
            base_url=settings.invoice_extraction.base_url,
            max_output_tokens=settings.invoice_extraction.max_output_tokens,
            prompt_spec=settings.invoice_extraction.prompt_spec,
        )
    raise RuntimeError(
        f"Unsupported invoice_extraction.mode: {settings.invoice_extraction.mode}"
    )
