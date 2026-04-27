from __future__ import annotations

import re
from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from opentelemetry.trace import SpanKind

from sumampa_odoo_agent.integrations.agent.framework import _ensure_agent_framework_version
from sumampa_odoo_agent.integrations.observability.odoo import ObservedOdooGateway
from sumampa_odoo_agent.integrations.odoo.dry_run import DryRunOdooClient
from sumampa_odoo_agent.integrations.telemetry import OpenTelemetryObservabilityProvider
from sumampa_odoo_agent.integrations.telemetry.bootstrap import (
    _FASTAPI_EXCLUDED_URLS,
    _enable_agent_framework_observability,
    _install_openinference_auto_kind_processor,
    _set_auto_openinference_span_kind,
    _set_fastapi_server_span_attributes,
)
from sumampa_odoo_agent.integrations.telemetry.otel_provider import (
    OpenTelemetryObservation,
    _set_input_output_attributes,
    _span_attributes,
)
from sumampa_odoo_agent.services.models.odoo import SearchInput
from sumampa_odoo_agent.services.observability import (
    CompositeObservabilityProvider,
    Observation,
    ObservationLevel,
    ObservationType,
    to_observability_payload,
)


class RecordingObservation:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    def update(
        self,
        *,
        input: Any | None = None,
        output: Any | None = None,
        metadata: Any | None = None,
        level: ObservationLevel | None = None,
        status_message: str | None = None,
        model: str | None = None,
    ) -> None:
        self.record["updates"].append(
            {
                "input": input,
                "output": output,
                "metadata": metadata,
                "level": level,
                "status_message": status_message,
                "model": model,
            }
        )

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        self.record["scores"].append(
            {
                "name": name,
                "value": value,
                "data_type": data_type,
                "comment": comment,
                "metadata": metadata,
            }
        )


class RecordingContext(AbstractContextManager[Observation]):
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def __enter__(self) -> Observation:
        return RecordingObservation(self._record)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> Literal[False]:
        del exc_type, exc_value, traceback
        return False


class RecordingObservabilityProvider:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def start_observation(
        self,
        *,
        name: str,
        as_type: ObservationType = "span",
        input: Any | None = None,
        output: Any | None = None,
        metadata: Any | None = None,
        level: ObservationLevel | None = None,
        status_message: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        version: str | None = None,
        model: str | None = None,
    ) -> AbstractContextManager[Observation]:
        record = {
            "name": name,
            "as_type": as_type,
            "input": input,
            "output": output,
            "metadata": metadata,
            "level": level,
            "status_message": status_message,
            "user_id": user_id,
            "session_id": session_id,
            "tags": tags,
            "version": version,
            "model": model,
            "updates": [],
            "scores": [],
        }
        self.records.append(record)
        return RecordingContext(record)

    def create_score(
        self,
        *,
        name: str,
        value: float | str | bool,
        session_id: str | None = None,
        trace_id: str | None = None,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        del name, value, session_id, trace_id, data_type, comment, metadata

    def flush(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class BrokenObservabilityProvider:
    def start_observation(self, **kwargs: Any) -> AbstractContextManager[Observation]:
        del kwargs
        raise RuntimeError("provider unavailable")

    def create_score(self, **kwargs: Any) -> None:
        del kwargs
        raise RuntimeError("provider unavailable")

    def flush(self) -> None:
        raise RuntimeError("provider unavailable")

    async def aclose(self) -> None:
        raise RuntimeError("provider unavailable")


class ForceFlushProvider:
    def __init__(self) -> None:
        self.timeout_millis: int | None = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.timeout_millis = timeout_millis
        return True


class SpanProcessorProvider:
    def __init__(self) -> None:
        self.span_processors: list[Any] = []

    def add_span_processor(self, span_processor: Any) -> None:
        self.span_processors.append(span_processor)


class PhoenixStyleSpanProcessorProvider:
    def __init__(self) -> None:
        self.span_processors: list[Any] = []
        self.replace_default_processor: bool | None = None

    def add_span_processor(
        self,
        span_processor: Any,
        *,
        replace_default_processor: bool = True,
    ) -> None:
        self.span_processors.append(span_processor)
        self.replace_default_processor = replace_default_processor


class FakeSpan:
    def __init__(
        self,
        *,
        name: str = "span",
        kind: SpanKind = SpanKind.INTERNAL,
        instrumentation_scope_name: str = "",
    ) -> None:
        self.name = name
        self.kind = kind
        self.instrumentation_scope = SimpleNamespace(name=instrumentation_scope_name)
        self.attributes: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "attributes": attributes or {}})

    def set_status(self, status: Any) -> None:
        self.attributes["status"] = status


def test_agent_framework_observability_handles_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_framework

    monkeypatch.delattr(agent_framework, "__version__", raising=False)
    _enable_agent_framework_observability(enable_sensitive_data=True)
    assert getattr(agent_framework, "__version__", None) is not None
    _ensure_agent_framework_version(agent_framework)


def test_fastapi_health_exclusion_matches_full_url() -> None:
    assert re.search(_FASTAPI_EXCLUDED_URLS, "http://testserver/health")
    assert re.search(_FASTAPI_EXCLUDED_URLS, "http://testserver/health?ready=true")
    assert not re.search(_FASTAPI_EXCLUDED_URLS, "http://testserver/api/v1/messages")


def test_fastapi_server_span_hook_sets_openinference_kind() -> None:
    span = FakeSpan()

    _set_fastapi_server_span_attributes(
        cast(Any, span),
        {"method": "POST", "path": "/api/v1/messages", "route": SimpleNamespace(path="/api/v1/messages")},
    )

    assert span.attributes["openinference.span.kind"] == "CHAIN"
    assert span.attributes["sumampa.instrumentation"] == "fastapi"
    assert span.attributes["sumampa.http.route"] == "/api/v1/messages"


def test_auto_kind_processor_maps_server_spans_to_chain() -> None:
    span = FakeSpan(
        name="POST /api/v1/messages",
        kind=SpanKind.SERVER,
        instrumentation_scope_name="opentelemetry.instrumentation.fastapi",
    )

    _set_auto_openinference_span_kind(cast(Any, span))

    assert span.attributes["openinference.span.kind"] == "CHAIN"
    assert span.attributes["sumampa.openinference.kind.source"] == "otel-auto"
    assert span.attributes["sumampa.otel.span_kind"] == "SERVER"


def test_auto_kind_processor_maps_external_client_spans_to_tool() -> None:
    span = FakeSpan(
        name="S3.PutBucketLifecycleConfiguration",
        kind=SpanKind.CLIENT,
        instrumentation_scope_name="opentelemetry.instrumentation.botocore",
    )

    _set_auto_openinference_span_kind(cast(Any, span))

    assert span.attributes["openinference.span.kind"] == "TOOL"
    assert span.attributes["sumampa.otel.span_kind"] == "CLIENT"


def test_auto_kind_processor_maps_httpcore_connect_spans_to_tool() -> None:
    span = FakeSpan(
        name="connect",
        kind=SpanKind.INTERNAL,
        instrumentation_scope_name="httpcore",
    )

    _set_auto_openinference_span_kind(cast(Any, span))

    assert span.attributes["openinference.span.kind"] == "TOOL"


def test_auto_kind_processor_preserves_specific_openinference_kind() -> None:
    span = FakeSpan(name="agent.llm", kind=SpanKind.INTERNAL)
    span.attributes["openinference.span.kind"] = "LLM"

    _set_auto_openinference_span_kind(cast(Any, span))

    assert span.attributes == {"openinference.span.kind": "LLM"}


def test_auto_kind_processor_retags_unknown_openinference_kind() -> None:
    span = FakeSpan(name="GET https://odoo.example", kind=SpanKind.CLIENT)
    span.attributes["openinference.span.kind"] = "UNKNOWN"

    _set_auto_openinference_span_kind(cast(Any, span))

    assert span.attributes["openinference.span.kind"] == "TOOL"


def test_openinference_auto_kind_processor_installs_once() -> None:
    provider = SpanProcessorProvider()

    _install_openinference_auto_kind_processor(provider)
    _install_openinference_auto_kind_processor(provider)

    assert len(provider.span_processors) == 1


def test_openinference_auto_kind_processor_preserves_phoenix_default_processor() -> None:
    provider = PhoenixStyleSpanProcessorProvider()

    _install_openinference_auto_kind_processor(provider)

    assert len(provider.span_processors) == 1
    assert provider.replace_default_processor is False


def test_composite_observability_fans_out_to_all_healthy_providers() -> None:
    first = RecordingObservabilityProvider()
    second = RecordingObservabilityProvider()
    provider = CompositeObservabilityProvider([first, second])

    with provider.start_observation(name="conversation.turn") as observation:
        observation.update(output={"ok": True})
        observation.score_trace(name="error", value=0.0)

    assert [record["name"] for record in first.records] == ["conversation.turn"]
    assert [record["name"] for record in second.records] == ["conversation.turn"]
    assert first.records[0]["updates"][0]["output"] == {"ok": True}
    assert second.records[0]["scores"][0]["name"] == "error"


def test_composite_observability_ignores_broken_providers() -> None:
    healthy = RecordingObservabilityProvider()
    provider = CompositeObservabilityProvider([BrokenObservabilityProvider(), healthy])

    with provider.start_observation(name="conversation.turn") as observation:
        observation.update(output={"ok": True})
        observation.score_trace(name="error", value=0.0)

    provider.create_score(name="quality", value=1.0)
    provider.flush()

    assert [record["name"] for record in healthy.records] == ["conversation.turn"]


def test_otel_provider_flushes_traces_metrics_and_logs() -> None:
    tracer_provider = ForceFlushProvider()
    meter_provider = ForceFlushProvider()
    logger_provider = ForceFlushProvider()
    provider = OpenTelemetryObservabilityProvider(
        tracer=cast(Any, object()),
        capture_payloads=True,
        tracer_provider=cast(Any, tracer_provider),
        meter_provider=cast(Any, meter_provider),
        logger_provider=cast(Any, logger_provider),
    )

    provider.flush()

    assert tracer_provider.timeout_millis == 2000
    assert meter_provider.timeout_millis == 2000
    assert logger_provider.timeout_millis == 2000


def test_openinference_span_attributes_include_phoenix_fields() -> None:
    attributes = _span_attributes(
        as_type="tool",
        metadata={"transport.channel": "whatsapp", "nested": {"ignored": True}},
        level="WARNING",
        status_message="missing field",
        user_id="user-1",
        session_id="conversation-1",
        tags=["conversation", "eval:candidate"],
        version="0.1.0",
        model="gpt-test",
    )

    assert attributes["openinference.span.kind"] == "TOOL"
    assert attributes["session.id"] == "conversation-1"
    assert attributes["user.id"] == "user-1"
    assert attributes["tag.tags"] == '["conversation", "eval:candidate"]'
    assert attributes["gen_ai.request.model"] == "gpt-test"
    assert attributes["llm.model_name"] == "gpt-test"
    assert attributes["metadata"] == (
        '{"nested": {"ignored": true}, "transport.channel": "whatsapp"}'
    )
    assert attributes["sumampa.transport.channel"] == "whatsapp"


def test_openinference_input_output_redacts_bytes() -> None:
    span = FakeSpan()
    _set_input_output_attributes(
        cast(Any, span),
        input={"content": b"abc"},
        output={"ok": True},
    )

    input_value = span.attributes["input.value"]
    assert span.attributes["input.mime_type"] == "application/json"
    assert span.attributes["output.mime_type"] == "application/json"
    assert '"kind": "bytes"' in input_value
    assert '"size_bytes": 3' in input_value
    assert "abc" not in input_value


def test_observability_payload_redacts_base64_and_data_uri_strings() -> None:
    encoded_image = "ZmFrZS1pbWFnZS1wYXlsb2Fk" * 4
    payload = to_observability_payload(
        {
            "attachment": {
                "filename": "factura.jpg",
                "content_base64": encoded_image,
                "has_content_base64": True,
            },
            "message": {
                "uri": f"data:image/jpeg;base64,{encoded_image}",
            },
        }
    )

    assert payload["attachment"]["filename"] == "factura.jpg"
    assert payload["attachment"]["has_content_base64"] is True
    assert payload["attachment"]["content_base64"]["kind"] == "base64"
    assert payload["attachment"]["content_base64"]["redacted"] is True
    assert payload["message"]["uri"]["kind"] == "data_uri"
    assert payload["message"]["uri"]["media_type"] == "image/jpeg"
    assert encoded_image not in str(payload)


def test_openinference_input_output_redacts_base64_strings() -> None:
    span = FakeSpan()
    encoded_image = "ZmFrZS1pbWFnZS1wYXlsb2Fk" * 4
    _set_input_output_attributes(
        cast(Any, span),
        input={
            "content_base64": encoded_image,
            "uri": f"data:image/jpeg;base64,{encoded_image}",
        },
        output={"ok": True},
    )

    input_value = span.attributes["input.value"]
    assert encoded_image not in input_value
    assert '"kind": "base64"' in input_value
    assert '"kind": "data_uri"' in input_value


def test_openinference_observation_update_sets_payload_attributes() -> None:
    span = FakeSpan()
    observation = OpenTelemetryObservation(span=cast(Any, span), capture_payloads=True)

    observation.update(input={"text": "hola"}, output={"assistant_text": "Listo."})

    assert span.attributes["input.value"] == '{"text": "hola"}'
    assert span.attributes["output.value"] == '{"assistant_text": "Listo."}'
    assert [event["name"] for event in span.events] == ["sumampa.input", "sumampa.output"]


@pytest.mark.asyncio
async def test_odoo_wrapper_records_tool_span() -> None:
    observability = RecordingObservabilityProvider()
    gateway = ObservedOdooGateway(
        wrapped=DryRunOdooClient(),
        observability=observability,
        mode="dry-run",
    )

    result = await gateway.search_partners(SearchInput(query="Sumampa"))

    assert result.hits[0].display_name == "Sumampa SRL"
    assert observability.records[0]["name"] == "odoo.search_partners"
    assert observability.records[0]["as_type"] == "tool"
    assert observability.records[0]["updates"][0]["output"]["mode"] == "dry-run"
