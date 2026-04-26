"""OpenTelemetry-backed implementation of the service observability contract."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from sumampa_odoo_agent.services.observability import (
    Observation,
    ObservationLevel,
    ObservationType,
    to_observability_payload,
)

logger = logging.getLogger(__name__)
_FORCE_FLUSH_TIMEOUT_MILLIS = 2_000
_JSON_MIME_TYPE = "application/json"
_OPENINFERENCE_KIND_BY_OBSERVATION_TYPE: dict[ObservationType, str] = {
    "agent": "AGENT",
    "chain": "CHAIN",
    "tool": "TOOL",
    "generation": "LLM",
    "embedding": "EMBEDDING",
    "retriever": "RETRIEVER",
    "evaluator": "EVALUATOR",
    "guardrail": "GUARDRAIL",
    "span": "CHAIN",
}


class OpenTelemetryObservation:
    """Mutable observation handle backed by one OpenTelemetry span."""

    def __init__(self, *, span: Span, capture_payloads: bool) -> None:
        self._span = span
        self._capture_payloads = capture_payloads

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
        if model is not None:
            self._span.set_attribute("gen_ai.request.model", model)
        if metadata is not None:
            _set_metadata_attributes(self._span, metadata)
        if self._capture_payloads:
            _set_input_output_attributes(self._span, input=input, output=output)
            _add_payload_event(self._span, "input", input)
            _add_payload_event(self._span, "output", output)
            _add_payload_event(self._span, "metadata", metadata)
        if level == "ERROR":
            self._span.set_status(Status(StatusCode.ERROR, status_message))
        elif status_message:
            self._span.set_attribute("sumampa.status_message", status_message)

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        attributes: dict[str, str | int | float | bool] = {
            "score.name": name,
            "score.value": value,
        }
        if data_type is not None:
            attributes["score.data_type"] = data_type
        if comment is not None:
            attributes["score.comment"] = comment
        if metadata is not None:
            attributes["score.metadata"] = _payload_json(metadata)
        self._span.add_event("trace.score", attributes=attributes)


class _OpenTelemetryObservationContext(AbstractContextManager[Observation]):
    def __init__(
        self,
        *,
        tracer: Tracer,
        name: str,
        as_type: ObservationType,
        input: Any | None,
        output: Any | None,
        metadata: Any | None,
        level: ObservationLevel | None,
        status_message: str | None,
        user_id: str | None,
        session_id: str | None,
        tags: list[str] | None,
        version: str | None,
        model: str | None,
        capture_payloads: bool,
    ) -> None:
        self._tracer = tracer
        self._name = name
        self._attributes = _span_attributes(
            as_type=as_type,
            metadata=metadata,
            level=level,
            status_message=status_message,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            version=version,
            model=model,
        )
        self._input = input
        self._output = output
        self._metadata = metadata
        self._capture_payloads = capture_payloads
        self._context_manager: AbstractContextManager[Span] | None = None
        self._observation: OpenTelemetryObservation | None = None

    def __enter__(self) -> Observation:
        self._context_manager = self._tracer.start_as_current_span(
            self._name,
            attributes=self._attributes,
        )
        span = self._context_manager.__enter__()
        self._observation = OpenTelemetryObservation(
            span=span,
            capture_payloads=self._capture_payloads,
        )
        if self._capture_payloads:
            _set_input_output_attributes(span, input=self._input, output=self._output)
            _add_payload_event(span, "input", self._input)
            _add_payload_event(span, "output", self._output)
            _add_payload_event(span, "metadata", self._metadata)
        return self._observation

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc_value is not None and self._observation is not None:
            self._observation.update(
                level="ERROR",
                status_message=f"{exc_value.__class__.__name__}: {exc_value}",
            )
            current_span = trace.get_current_span()
            current_span.record_exception(exc_value)
        if self._context_manager is not None:
            self._context_manager.__exit__(exc_type, exc_value, traceback)
        return False


class OpenTelemetryObservabilityProvider:
    """OpenTelemetry provider for Phoenix/OpenInference-compatible traces."""

    def __init__(
        self,
        *,
        tracer: Tracer,
        capture_payloads: bool,
        tracer_provider: Any | None = None,
        meter_provider: MeterProvider | None = None,
        logger_provider: LoggerProvider | None = None,
    ) -> None:
        self._tracer = tracer
        self._capture_payloads = capture_payloads
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._logger_provider = logger_provider

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
        return _OpenTelemetryObservationContext(
            tracer=self._tracer,
            name=name,
            as_type=as_type,
            input=input,
            output=output,
            metadata=metadata,
            level=level,
            status_message=status_message,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            version=version,
            model=model,
            capture_payloads=self._capture_payloads,
        )

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
        del session_id, trace_id
        with self._tracer.start_as_current_span("trace.score") as span:
            OpenTelemetryObservation(
                span=span,
                capture_payloads=self._capture_payloads,
            ).score_trace(
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
                metadata=metadata,
            )

    def flush(self) -> None:
        for provider in (self._tracer_provider, self._meter_provider, self._logger_provider):
            if provider is None:
                continue
            try:
                provider.force_flush(timeout_millis=_FORCE_FLUSH_TIMEOUT_MILLIS)
            except Exception:
                logger.warning("OpenTelemetry force_flush failed", exc_info=True)

    async def aclose(self) -> None:
        self.flush()


def _span_attributes(
    *,
    as_type: ObservationType,
    metadata: Any | None,
    level: ObservationLevel | None,
    status_message: str | None,
    user_id: str | None,
    session_id: str | None,
    tags: list[str] | None,
    version: str | None,
    model: str | None,
) -> dict[str, str | int | float | bool]:
    attributes: dict[str, str | int | float | bool] = {
        "openinference.span.kind": _OPENINFERENCE_KIND_BY_OBSERVATION_TYPE.get(as_type, "CHAIN"),
        "sumampa.observation.type": as_type,
    }
    if level is not None:
        attributes["sumampa.level"] = level
    if status_message is not None:
        attributes["sumampa.status_message"] = status_message
    if user_id is not None:
        attributes["user.id"] = user_id
        attributes["enduser.id"] = user_id
    if session_id is not None:
        attributes["session.id"] = session_id
    if tags:
        attributes["sumampa.tags"] = ",".join(tags)
        attributes["tag.tags"] = _payload_json(tags)
    if version is not None:
        attributes["service.version"] = version
    if model is not None:
        attributes["gen_ai.request.model"] = model
        attributes["llm.model_name"] = model
    if isinstance(metadata, Mapping):
        attributes["metadata"] = _payload_json(metadata)
    _set_metadata_attributes_dict(attributes, metadata)
    return attributes


def _set_metadata_attributes(span: Span, metadata: Any | None) -> None:
    attributes: dict[str, str | int | float | bool] = {}
    _set_metadata_attributes_dict(attributes, metadata)
    for key, value in attributes.items():
        span.set_attribute(key, value)


def _set_metadata_attributes_dict(
    attributes: dict[str, str | int | float | bool],
    metadata: Any | None,
) -> None:
    if not isinstance(metadata, Mapping):
        return
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool):
            attributes[f"sumampa.{key}"] = value


def _add_payload_event(span: Span, name: str, value: Any | None) -> None:
    if value is None:
        return
    span.add_event(
        f"sumampa.{name}",
        attributes={"payload": _payload_json(value)},
    )


def _set_input_output_attributes(
    span: Span,
    *,
    input: Any | None,
    output: Any | None,
) -> None:
    if input is not None:
        span.set_attribute("input.mime_type", _JSON_MIME_TYPE)
        span.set_attribute("input.value", _payload_json(input))
    if output is not None:
        span.set_attribute("output.mime_type", _JSON_MIME_TYPE)
        span.set_attribute("output.value", _payload_json(output))


def _payload_json(value: Any) -> str:
    return json.dumps(
        to_observability_payload(value),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
