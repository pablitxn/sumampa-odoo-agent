"""Observability provider factory."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.services.errors import ConfigurationError
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
)


def build_observability_provider(settings: AppSettings) -> ObservabilityProvider:
    """Build the configured observability provider."""

    if settings.observability.mode in {"disabled", "phoenix"}:
        return NoOpObservabilityProvider()
    raise ConfigurationError(
        f"Unsupported observability.mode: {settings.observability.mode}",
        code="unsupported_observability_mode",
    )
