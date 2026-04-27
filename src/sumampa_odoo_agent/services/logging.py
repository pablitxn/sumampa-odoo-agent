"""Logging setup for JSON stdout and trace correlation."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.services.observability import (
    redact_binary_payload_text,
    to_observability_payload,
)

_MANAGED_HANDLER_ATTR = "_sumampa_managed_handler"


class HealthCheckLogFilter(logging.Filter):
    """Drop noisy uvicorn access logs for the local readiness endpoint."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        return not _is_health_check_access_record(record)


class BinaryPayloadLogFilter(logging.Filter):
    """Redact inline binary payloads before stdout or OTEL log handlers see them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize_log_arg(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_sanitize_log_arg(arg) for arg in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {key: _sanitize_log_arg(value) for key, value in record.args.items()}
        elif record.args:
            record.args = _sanitize_log_arg(record.args)
        return True


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def __init__(
        self,
        *,
        service_name: str,
        deployment_environment: str,
        cluster: str,
    ) -> None:
        super().__init__()
        self._service_name = service_name
        self._deployment_environment = deployment_environment
        self._cluster = cluster

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _current_trace_ids()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity_text": record.levelname,
            "severity_number": record.levelno,
            "logger": record.name,
            "message": redact_binary_payload_text(record.getMessage()),
            "service_name": self._service_name,
            "deployment_environment": self._deployment_environment,
            "cluster": self._cluster,
            "trace_id": trace_id,
            "span_id": span_id,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = redact_binary_payload_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: AppSettings) -> None:
    """Install application logging without letting uvicorn replace it later."""

    root = logging.getLogger()
    root.setLevel(_logging_level(settings.logging.level))
    root.handlers = [
        handler
        for handler in root.handlers
        if not getattr(handler, _MANAGED_HANDLER_ATTR, False)
    ]
    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    handler.setLevel(_logging_level(settings.logging.level))
    handler.addFilter(HealthCheckLogFilter())
    handler.addFilter(BinaryPayloadLogFilter())
    if settings.logging.format == "json":
        handler.setFormatter(
            JsonLogFormatter(
                service_name=settings.telemetry.service_name,
                deployment_environment=settings.telemetry.environment,
                cluster=settings.telemetry.cluster,
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s"
            )
        )
    root.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(_logging_level(settings.logging.level))


def _logging_level(level: str) -> int:
    return logging._nameToLevel.get(level.upper(), logging.INFO)


def _is_health_check_access_record(record: logging.LogRecord) -> bool:
    if _contains_health_path(record.getMessage()):
        return True
    if not isinstance(record.args, tuple):
        return False
    return any(isinstance(arg, str) and _contains_health_path(arg) for arg in record.args)


def _contains_health_path(value: str) -> bool:
    return " /health " in value or " /health?" in value or value in {"/health", "/health/"}


def _sanitize_log_arg(value: Any) -> Any:
    if isinstance(value, str):
        return redact_binary_payload_text(value)
    if isinstance(value, bytes):
        return to_observability_payload(value)
    if isinstance(value, Mapping):
        return to_observability_payload(value)
    if isinstance(value, list | tuple):
        return to_observability_payload(value)
    return value


def _current_trace_ids() -> tuple[str | None, str | None]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"
