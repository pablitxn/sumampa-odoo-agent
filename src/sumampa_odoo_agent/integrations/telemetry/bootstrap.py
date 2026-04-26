"""Programmatic OpenTelemetry bootstrap."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
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
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent.framework import _ensure_agent_framework_version
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
_OPENINFERENCE_SPAN_KIND_ATTR = "openinference.span.kind"
_OPENINFERENCE_AUTO_KIND_PROCESSOR_ATTR = "_sumampa_openinference_auto_kind_processor"
_OTLP_EXPORT_TIMEOUT_SECONDS = 5.0
_FASTAPI_EXCLUDED_URLS = r"/health(?:\?.*)?$"
_HTTP_METHODS = frozenset({"CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"})
_CHAIN_SCOPE_PREFIXES = (
    "opentelemetry.instrumentation.asgi",
    "opentelemetry.instrumentation.fastapi",
)
_TOOL_SCOPE_PREFIXES = (
    "httpcore",
    "httpx",
    "opentelemetry.instrumentation.botocore",
    "opentelemetry.instrumentation.httpx",
    "opentelemetry.instrumentation.redis",
    "opentelemetry.instrumentation.sqlalchemy",
)


class _DropOpenTelemetryInternalLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry.")


class _OpenInferenceAutoKindSpanProcessor(SpanProcessor):
    """Tag auto-instrumented OTEL spans with Phoenix/OpenInference span kinds."""

    def on_start(self, span: Span, parent_context: Any | None = None) -> None:
        del parent_context
        _set_auto_openinference_span_kind(span)

    def on_end(self, span: ReadableSpan) -> None:
        del span


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

    traces_enabled = _traces_enabled(settings)
    metrics_enabled = settings.telemetry.enabled and settings.telemetry.metrics_enabled
    logs_enabled = settings.telemetry.enabled and settings.telemetry.logs_enabled

    if not traces_enabled and not metrics_enabled and not logs_enabled:
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
    meter_provider = _configure_metrics(settings, resource) if metrics_enabled else None
    logger_provider = _configure_logs(settings, resource) if logs_enabled else None
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
        metrics=AppMetrics.from_settings(settings) if metrics_enabled else AppMetrics.disabled(settings),
        enabled=True,
    )


def instrument_fastapi_app(app: FastAPI, settings: AppSettings) -> None:
    if not _traces_enabled(settings):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=_FASTAPI_EXCLUDED_URLS,
        server_request_hook=_set_fastapi_server_span_attributes,
        exclude_spans=["receive", "send"],
    )


def _set_fastapi_server_span_attributes(span: Any, scope: Mapping[str, Any]) -> None:
    span.set_attribute("openinference.span.kind", "CHAIN")
    span.set_attribute("sumampa.instrumentation", "fastapi")
    route = _fastapi_route(scope)
    if route is not None:
        span.set_attribute("sumampa.http.route", route)


def _fastapi_route(scope: Mapping[str, Any]) -> str | None:
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    path = scope.get("path")
    if isinstance(path, str):
        return path
    return None


def _configure_traces(settings: AppSettings, resource: Resource) -> Any | None:
    global _GLOBAL_TELEMETRY_CONFIGURED
    if not _traces_enabled(settings):
        return None
    if _GLOBAL_TELEMETRY_CONFIGURED:
        provider = trace.get_tracer_provider()
        _install_openinference_auto_kind_processor(provider)
        return provider
    if _phoenix_enabled(settings):
        provider = _configure_phoenix_traces(settings, resource)
        _install_openinference_auto_kind_processor(provider)
        _GLOBAL_TELEMETRY_CONFIGURED = True
        return provider
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(settings.telemetry.sample_rate),
        shutdown_on_exit=False,
    )
    _install_openinference_auto_kind_processor(provider)
    exporter = _span_exporter(settings)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _GLOBAL_TELEMETRY_CONFIGURED = True
    return provider


def _configure_metrics(settings: AppSettings, resource: Resource) -> MeterProvider | None:
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
    if _GLOBAL_INSTRUMENTATION_ENABLED or not _traces_enabled(settings):
        return
    _enable_agent_framework_observability(
        enable_sensitive_data=settings.observability.capture_mode == "full",
    )
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


def _configure_phoenix_traces(settings: AppSettings, resource: Resource) -> Any:
    from phoenix.otel import register

    api_key = os.environ.get(settings.observability.api_key_env_var)
    return register(
        endpoint=settings.observability.collector_endpoint,
        project_name=settings.observability.project_name,
        protocol="http/protobuf",
        batch=True,
        auto_instrument=False,
        api_key=api_key,
        resource=resource,
        sampler=TraceIdRatioBased(settings.observability.sample_rate),
    )


def _enable_agent_framework_observability(*, enable_sensitive_data: bool) -> None:
    try:
        import agent_framework

        _ensure_agent_framework_version(agent_framework)
        from agent_framework.observability import enable_instrumentation

        enable_instrumentation(enable_sensitive_data=enable_sensitive_data)
    except Exception:
        logger.warning("Could not enable Agent Framework OpenTelemetry", exc_info=True)


def _install_openinference_auto_kind_processor(provider: Any | None) -> None:
    if provider is None or getattr(provider, _OPENINFERENCE_AUTO_KIND_PROCESSOR_ATTR, False):
        return
    add_span_processor = getattr(provider, "add_span_processor", None)
    if not callable(add_span_processor):
        return
    add_span_processor(_OpenInferenceAutoKindSpanProcessor())
    setattr(provider, _OPENINFERENCE_AUTO_KIND_PROCESSOR_ATTR, True)


def _set_auto_openinference_span_kind(span: Any) -> None:
    attributes = getattr(span, "attributes", None) or {}
    current_kind = attributes.get(_OPENINFERENCE_SPAN_KIND_ATTR)
    if isinstance(current_kind, str) and current_kind.upper() != "UNKNOWN":
        return

    inferred_kind = _infer_openinference_span_kind(span)
    span.set_attribute(_OPENINFERENCE_SPAN_KIND_ATTR, inferred_kind)
    span.set_attribute("sumampa.openinference.kind.source", "otel-auto")

    otel_kind_name = _otel_span_kind_name(span)
    if otel_kind_name is not None:
        span.set_attribute("sumampa.otel.span_kind", otel_kind_name)


def _infer_openinference_span_kind(span: Any) -> str:
    span_kind = getattr(span, "kind", None)
    if span_kind == SpanKind.SERVER:
        return "CHAIN"
    if span_kind in {SpanKind.CLIENT, SpanKind.PRODUCER, SpanKind.CONSUMER}:
        return "TOOL"

    scope_name = _instrumentation_scope_name(span)
    if _matches_any_prefix(scope_name, _CHAIN_SCOPE_PREFIXES):
        return "CHAIN"
    if _matches_any_prefix(scope_name, _TOOL_SCOPE_PREFIXES):
        return "TOOL"
    if _looks_like_external_dependency_span(span):
        return "TOOL"
    return "CHAIN"


def _looks_like_external_dependency_span(span: Any) -> bool:
    span_name = str(getattr(span, "name", "") or "")
    first_token = span_name.split(" ", 1)[0].upper()
    if first_token in _HTTP_METHODS:
        return True
    if span_name.startswith("S3."):
        return True
    if span_name.lower() in {"connect", "dns", "tls"}:
        return True

    attributes = getattr(span, "attributes", None) or {}
    return any(
        key in attributes
        for key in (
            "aws.service",
            "db.system",
            "http.request.method",
            "rpc.method",
            "rpc.service",
            "server.address",
            "url.full",
        )
    )


def _instrumentation_scope_name(span: Any) -> str:
    scope = getattr(span, "instrumentation_scope", None) or getattr(
        span,
        "instrumentation_info",
        None,
    )
    name = getattr(scope, "name", "")
    return name if isinstance(name, str) else ""


def _matches_any_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)


def _otel_span_kind_name(span: Any) -> str | None:
    span_kind = getattr(span, "kind", None)
    name = getattr(span_kind, "name", None)
    return name if isinstance(name, str) else None


def _phoenix_enabled(settings: AppSettings) -> bool:
    return settings.observability.mode == "phoenix"


def _traces_enabled(settings: AppSettings) -> bool:
    return (_phoenix_enabled(settings) or settings.telemetry.enabled) and settings.telemetry.traces_enabled


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
