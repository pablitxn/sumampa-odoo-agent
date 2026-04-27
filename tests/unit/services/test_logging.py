from __future__ import annotations

import base64
import json
import logging

from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

from sumampa_odoo_agent.services.logging import (
    BinaryPayloadLogFilter,
    HealthCheckLogFilter,
    JsonLogFormatter,
)


def test_json_logging_includes_trace_and_span_ids() -> None:
    formatter = JsonLogFormatter(
        service_name="sumampa-odoo-agent",
        deployment_environment="test",
        cluster="local",
    )
    record = logging.LogRecord(
        name="sumampa.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    trace_id = 0x1234567890ABCDEF1234567890ABCDEF
    span_id = 0x1234567890ABCDEF
    span = NonRecordingSpan(
        SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
    )

    with trace.use_span(span):
        payload = json.loads(formatter.format(record))

    assert payload["service_name"] == "sumampa-odoo-agent"
    assert payload["deployment_environment"] == "test"
    assert payload["severity_text"] == "INFO"
    assert payload["message"] == "hello world"
    assert payload["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert payload["span_id"] == "1234567890abcdef"


def test_json_logging_redacts_base64_images_from_message_args() -> None:
    formatter = JsonLogFormatter(
        service_name="sumampa-odoo-agent",
        deployment_environment="test",
        cluster="local",
    )
    encoded_image = base64.b64encode(b"fake-image-payload" * 10).decode("ascii")
    record = logging.LogRecord(
        name="sumampa.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="payload=%s uri=%s",
        args=(
            {"content_base64": encoded_image, "filename": "factura.jpg"},
            f"data:image/jpeg;base64,{encoded_image}",
        ),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert encoded_image not in payload["message"]
    assert "[redacted base64 payload]" in payload["message"]
    assert "data:image/jpeg;base64,[redacted" in payload["message"]


def test_binary_payload_log_filter_redacts_before_handler_formatting() -> None:
    encoded_image = base64.b64encode(b"fake-image-payload" * 10).decode("ascii")
    record = logging.LogRecord(
        name="sumampa.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="payload=%(attachment)s",
        args=({"attachment": {"content_base64": encoded_image}},),
        exc_info=None,
    )

    assert BinaryPayloadLogFilter().filter(record)
    assert encoded_image not in record.getMessage()
    assert "'redacted': True" in record.getMessage()


def test_health_check_log_filter_drops_uvicorn_access_health_checks() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", "/health", "1.1", 200),
        exc_info=None,
    )

    assert not HealthCheckLogFilter().filter(record)


def test_health_check_log_filter_keeps_non_health_access_logs() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "POST", "/api/v1/messages", "1.1", 200),
        exc_info=None,
    )

    assert HealthCheckLogFilter().filter(record)
