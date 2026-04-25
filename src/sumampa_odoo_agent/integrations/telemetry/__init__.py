"""OpenTelemetry bootstrap helpers."""

from sumampa_odoo_agent.integrations.telemetry.bootstrap import (
    TelemetryRuntime,
    bootstrap_telemetry,
    instrument_fastapi_app,
)
from sumampa_odoo_agent.integrations.telemetry.otel_provider import (
    OpenTelemetryObservabilityProvider,
)

__all__ = [
    "OpenTelemetryObservabilityProvider",
    "TelemetryRuntime",
    "bootstrap_telemetry",
    "instrument_fastapi_app",
]
