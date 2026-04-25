"""Observability provider factory."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.observability.langfuse import LangfuseObservabilityProvider
from sumampa_odoo_agent.services.errors import ConfigurationError
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
)


def build_observability_provider(settings: AppSettings) -> ObservabilityProvider:
    """Build the configured observability provider."""

    if settings.observability.mode == "disabled":
        return NoOpObservabilityProvider()
    if settings.observability.mode == "langfuse":
        return LangfuseObservabilityProvider.from_settings(settings)
    raise ConfigurationError(
        f"Unsupported observability.mode: {settings.observability.mode}",
        code="unsupported_observability_mode",
    )
