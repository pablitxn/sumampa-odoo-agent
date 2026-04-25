"""Observability provider assembly."""

from __future__ import annotations

from sumampa_odoo_agent.integrations.observability.factory import build_observability_provider
from sumampa_odoo_agent.integrations.observability.odoo import ObservedOdooGateway
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    NoOpObservation,
    ObservabilityProvider,
    Observation,
)

__all__ = [
    "NoOpObservabilityProvider",
    "NoOpObservation",
    "ObservabilityProvider",
    "Observation",
    "ObservedOdooGateway",
    "build_observability_provider",
]
