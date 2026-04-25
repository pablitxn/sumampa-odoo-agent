"""Service-level observability contracts and no-op implementation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Literal, Protocol

from pydantic import BaseModel

ObservationLevel = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]
ObservationType = Literal[
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
    "generation",
    "embedding",
]


class Observation(Protocol):
    """Mutable observation handle returned by an observability provider."""

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
        """Update the current observation."""

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        """Attach a score to the current trace."""


class ObservabilityProvider(Protocol):
    """Provider-neutral tracing surface for service orchestration."""

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
        """Start an observation and make it current inside the returned context."""

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
        """Attach an out-of-band score to Langfuse-compatible entities."""

    def flush(self) -> None:
        """Flush any pending telemetry."""

    async def aclose(self) -> None:
        """Release provider resources."""


class NoOpObservation:
    """Observation that intentionally discards all updates."""

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
        del input, output, metadata, level, status_message, model

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        del name, value, data_type, comment, metadata


class NoOpObservabilityProvider:
    """No-op provider used when observability is disabled or tests do not need traces."""

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
        del (
            name,
            as_type,
            input,
            output,
            metadata,
            level,
            status_message,
            user_id,
            session_id,
            tags,
            version,
            model,
        )
        return nullcontext(NoOpObservation())

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


def to_observability_payload(value: Any) -> Any:
    """Convert app values to JSON-friendly trace payloads without raw binary blobs."""

    if isinstance(value, BaseModel):
        return to_observability_payload(value.model_dump(mode="json"))
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, str) or value is None or isinstance(value, int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): to_observability_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [to_observability_payload(item) for item in value]
    return str(value)
