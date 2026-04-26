"""Service-level observability contracts and no-op implementation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, nullcontext
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
        """Attach an out-of-band score to observability-compatible entities."""

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


class CompositeObservation:
    """Observation facade that fans updates out to multiple providers."""

    def __init__(self, observations: Sequence[Observation]) -> None:
        self._observations = tuple(observations)

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
        for observation in self._observations:
            try:
                observation.update(
                    input=input,
                    output=output,
                    metadata=metadata,
                    level=level,
                    status_message=status_message,
                    model=model,
                )
            except Exception:
                continue

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        for observation in self._observations:
            try:
                observation.score_trace(
                    name=name,
                    value=value,
                    data_type=data_type,
                    comment=comment,
                    metadata=metadata,
                )
            except Exception:
                continue


class _CompositeObservationContext(AbstractContextManager[Observation]):
    def __init__(
        self,
        *,
        providers: Sequence[ObservabilityProvider],
        kwargs: dict[str, Any],
    ) -> None:
        self._providers = tuple(providers)
        self._kwargs = kwargs
        self._stack = ExitStack()

    def __enter__(self) -> Observation:
        observations: list[Observation] = []
        for provider in self._providers:
            try:
                context = provider.start_observation(**self._kwargs)
                observations.append(self._stack.enter_context(context))
            except Exception:
                continue
        return CompositeObservation(observations) if observations else NoOpObservation()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Literal[False]:
        self._stack.__exit__(exc_type, exc_value, traceback)
        return False


class CompositeObservabilityProvider:
    """Observability provider that fans out to each configured backend."""

    def __init__(self, providers: Sequence[ObservabilityProvider]) -> None:
        self._providers = tuple(providers)

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
        return _CompositeObservationContext(
            providers=self._providers,
            kwargs={
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
            },
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
        for provider in self._providers:
            try:
                provider.create_score(
                    name=name,
                    value=value,
                    session_id=session_id,
                    trace_id=trace_id,
                    data_type=data_type,
                    comment=comment,
                    metadata=metadata,
                )
            except Exception:
                continue

    def flush(self) -> None:
        for provider in self._providers:
            try:
                provider.flush()
            except Exception:
                continue

    async def aclose(self) -> None:
        for provider in reversed(self._providers):
            try:
                await provider.aclose()
            except Exception:
                continue


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
