"""Logging setup for JSON stdout and trace correlation."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from sumampa_odoo_agent.config import AppSettings

_MANAGED_HANDLER_ATTR = "_sumampa_managed_handler"


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
            "message": record.getMessage(),
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
            payload["exception"] = self.formatException(record.exc_info)
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


def _current_trace_ids() -> tuple[str | None, str | None]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"
