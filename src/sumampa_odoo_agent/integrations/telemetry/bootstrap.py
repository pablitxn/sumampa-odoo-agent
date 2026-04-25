"""Programmatic OpenTelemetry bootstrap."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter as GrpcOTLPLogExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcOTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcOTLPSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http._log_exporter import (
    OTLPLogExporter as HttpOTLPLogExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HttpOTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpOTLPSpanExporter,
)
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.telemetry.otel_provider import (
    OpenTelemetryObservabilityProvider,
)
from sumampa_odoo_agent.services.metrics import AppMetrics
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
)

logger = logging.getLogger(__name__)

_GLOBAL_INSTRUMENTATION_ENABLED = False
_GLOBAL_TELEMETRY_CONFIGURED = False
_MANAGED_OTEL_LOG_HANDLER_ATTR = "_sumampa_managed_otel_log_handler"
_OTLP_EXPORT_TIMEOUT_SECONDS = 5.0


class _DropOpenTelemetryInternalLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry.")


@dataclass(slots=True)
class TelemetryRuntime:
    """Telemetry pieces needed by FastAPI and the service graph."""

    observability: ObservabilityProvider
    metrics: AppMetrics
    enabled: bool

    async def aclose(self) -> None:
        self.observability.flush()


def bootstrap_telemetry(settings: AppSettings) -> TelemetryRuntime:
    """Initialize OpenTelemetry exporters and global instrumentation."""

    if not settings.telemetry.enabled:
        return TelemetryRuntime(
            observability=NoOpObservabilityProvider(),
            metrics=AppMetrics.disabled(settings),
            enabled=False,
        )

    resource = Resource.create(
        {
            "service.name": settings.telemetry.service_name,
            "service.version": settings.service.version,
            "deployment.environment": settings.telemetry.environment,
            "cluster": settings.telemetry.cluster,
        }
    )
    tracer_provider = _configure_traces(settings, resource)
    meter_provider = _configure_metrics(settings, resource)
    logger_provider = _configure_logs(settings, resource)
    _instrument_global_libraries(settings)

    tracer = trace.get_tracer("sumampa_odoo_agent.observability", settings.service.version)
    return TelemetryRuntime(
        observability=OpenTelemetryObservabilityProvider(
            tracer=tracer,
            capture_payloads=settings.telemetry.capture_payloads,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            logger_provider=logger_provider,
        ),
        metrics=AppMetrics.from_settings(settings)
        if settings.telemetry.metrics_enabled
        else AppMetrics.disabled(settings),
        enabled=True,
    )


def instrument_fastapi_app(app: FastAPI, settings: AppSettings) -> None:
    if not settings.telemetry.enabled or not settings.telemetry.traces_enabled:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="^/health$",
    )


def _configure_traces(settings: AppSettings, resource: Resource) -> TracerProvider | None:
    global _GLOBAL_TELEMETRY_CONFIGURED
    if not settings.telemetry.traces_enabled:
        return None
    if _GLOBAL_TELEMETRY_CONFIGURED:
        provider = trace.get_tracer_provider()
        return provider if isinstance(provider, TracerProvider) else None
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(settings.telemetry.sample_rate),
        shutdown_on_exit=False,
    )
    exporter = _span_exporter(settings)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _GLOBAL_TELEMETRY_CONFIGURED = True
    return provider


def _configure_metrics(settings: AppSettings, resource: Resource) -> MeterProvider | None:
    if not settings.telemetry.metrics_enabled:
        return None
    exporter = _metric_exporter(settings)
    provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(exporter)],
        shutdown_on_exit=False,
    )
    try:
        metrics.set_meter_provider(provider)
    except Exception:
        logger.debug("OpenTelemetry meter provider was already configured", exc_info=True)
        current_provider = metrics.get_meter_provider()
        return current_provider if isinstance(current_provider, MeterProvider) else None
    return provider


def _configure_logs(settings: AppSettings, resource: Resource) -> LoggerProvider | None:
    if not settings.telemetry.logs_enabled:
        return None
    provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
    provider.add_log_record_processor(BatchLogRecordProcessor(_log_exporter(settings)))
    try:
        set_logger_provider(provider)
    except Exception:
        logger.debug("OpenTelemetry logger provider was already configured", exc_info=True)
    LoggingInstrumentor().instrument(set_logging_format=False)
    root = logging.getLogger()
    root.handlers = [
        handler
        for handler in root.handlers
        if not getattr(handler, _MANAGED_OTEL_LOG_HANDLER_ATTR, False)
    ]
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    handler.addFilter(_DropOpenTelemetryInternalLogs())
    setattr(handler, _MANAGED_OTEL_LOG_HANDLER_ATTR, True)
    root.addHandler(handler)
    return provider


def _instrument_global_libraries(settings: AppSettings) -> None:
    global _GLOBAL_INSTRUMENTATION_ENABLED
    if _GLOBAL_INSTRUMENTATION_ENABLED or not settings.telemetry.traces_enabled:
        return
    for instrumentor in (
        HTTPXClientInstrumentor(),
        SQLAlchemyInstrumentor(),
        RedisInstrumentor(),
        cast(Any, BotocoreInstrumentor)(),
    ):
        try:
            instrumentor.instrument()
        except Exception:
            logger.warning(
                "OpenTelemetry instrumentation failed for %s",
                instrumentor.__class__.__name__,
                exc_info=True,
            )
    _GLOBAL_INSTRUMENTATION_ENABLED = True


def _span_exporter(settings: AppSettings) -> Any:
    if settings.telemetry.otlp_protocol == "http/protobuf":
        return HttpOTLPSpanExporter(
            endpoint=_http_signal_endpoint(settings, "traces"),
            timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
        )
    return GrpcOTLPSpanExporter(
        endpoint=settings.telemetry.otlp_endpoint,
        timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
    )


def _metric_exporter(settings: AppSettings) -> Any:
    if settings.telemetry.otlp_protocol == "http/protobuf":
        return HttpOTLPMetricExporter(
            endpoint=_http_signal_endpoint(settings, "metrics"),
            timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
        )
    return GrpcOTLPMetricExporter(
        endpoint=settings.telemetry.otlp_endpoint,
        timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
    )


def _log_exporter(settings: AppSettings) -> Any:
    if settings.telemetry.otlp_protocol == "http/protobuf":
        return HttpOTLPLogExporter(
            endpoint=_http_signal_endpoint(settings, "logs"),
            timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
        )
    return GrpcOTLPLogExporter(
        endpoint=settings.telemetry.otlp_endpoint,
        timeout=_OTLP_EXPORT_TIMEOUT_SECONDS,
    )


def _http_signal_endpoint(settings: AppSettings, signal: str) -> str:
    endpoint = settings.telemetry.otlp_endpoint.rstrip("/")
    if endpoint.endswith(f"/v1/{signal}"):
        return endpoint
    return f"{endpoint}/v1/{signal}"
