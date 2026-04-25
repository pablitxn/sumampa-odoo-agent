"""Langfuse-backed observability provider."""

from __future__ import annotations

import logging
import os
from contextlib import AbstractContextManager, ExitStack
from types import TracebackType
from typing import Any, Literal, cast

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent.framework import _ensure_agent_framework_version
from sumampa_odoo_agent.services.errors import ConfigurationError
from sumampa_odoo_agent.services.observability import (
    NoOpObservation,
    ObservabilityProvider,
    Observation,
    ObservationLevel,
    ObservationType,
    to_observability_payload,
)

logger = logging.getLogger(__name__)


class LangfuseObservation:
    """Safe wrapper around a Langfuse observation handle."""

    def __init__(self, span: Any) -> None:
        self._span = span

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
        try:
            self._span.update(
                input=to_observability_payload(input),
                output=to_observability_payload(output),
                metadata=to_observability_payload(metadata),
                level=level,
                status_message=status_message,
                model=model,
            )
        except Exception:
            logger.warning("Langfuse observation update failed", exc_info=True)

    def score_trace(
        self,
        *,
        name: str,
        value: float | str | bool,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: Any | None = None,
    ) -> None:
        try:
            self._span.score_trace(
                name=name,
                value=_normalize_score_value(value),
                data_type=cast(Any, data_type),
                comment=comment,
                metadata=to_observability_payload(metadata),
            )
        except Exception:
            logger.warning("Langfuse trace score failed", exc_info=True)


class _LangfuseObservationContext(AbstractContextManager[Observation]):
    def __init__(
        self,
        *,
        client: Any,
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
    ) -> None:
        self._client = client
        self._name = name
        self._as_type = as_type
        self._input = input
        self._output = output
        self._metadata = metadata
        self._level = level
        self._status_message = status_message
        self._user_id = user_id
        self._session_id = session_id
        self._tags = tags
        self._version = version
        self._model = model
        self._stack = ExitStack()
        self._observation: Observation = NoOpObservation()

    def __enter__(self) -> Observation:
        try:
            if self._should_propagate_attributes():
                from langfuse import propagate_attributes

                self._stack.enter_context(
                    propagate_attributes(
                        user_id=self._user_id,
                        session_id=self._session_id,
                        metadata=_metadata_for_propagation(self._metadata),
                        version=self._version,
                        tags=self._tags,
                        trace_name=self._name,
                    )
                )

            span = self._stack.enter_context(
                self._client.start_as_current_observation(
                    name=self._name,
                    as_type=self._as_type,
                    input=to_observability_payload(self._input),
                    output=to_observability_payload(self._output),
                    metadata=to_observability_payload(self._metadata),
                    level=self._level,
                    status_message=self._status_message,
                    version=self._version,
                    model=self._model,
                )
            )
            self._observation = LangfuseObservation(span)
            return self._observation
        except Exception:
            logger.warning("Langfuse observation start failed", exc_info=True)
            self._stack.close()
            self._observation = NoOpObservation()
            return self._observation

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exc_value is not None:
            self._observation.update(
                level="ERROR",
                status_message=f"{exc_value.__class__.__name__}: {exc_value}",
            )
        try:
            self._stack.__exit__(exc_type, exc_value, traceback)
        except Exception:
            logger.warning("Langfuse observation close failed", exc_info=True)
        return False

    def _should_propagate_attributes(self) -> bool:
        return any(
            value is not None
            for value in (self._user_id, self._session_id, self._version, self._tags)
        )


class LangfuseObservabilityProvider(ObservabilityProvider):
    """Langfuse provider backed by the Langfuse Python SDK."""

    def __init__(
        self,
        *,
        client: Any,
        flush_on_shutdown: bool,
    ) -> None:
        self._client = client
        self._flush_on_shutdown = flush_on_shutdown

    @classmethod
    def from_settings(cls, settings: AppSettings) -> LangfuseObservabilityProvider:
        public_key = os.environ.get(settings.observability.public_key_env_var)
        secret_key = os.environ.get(settings.observability.secret_key_env_var)
        missing_env_vars = [
            env_var
            for env_var, value in (
                (settings.observability.public_key_env_var, public_key),
                (settings.observability.secret_key_env_var, secret_key),
            )
            if not value
        ]
        if missing_env_vars:
            raise ConfigurationError(
                "Langfuse observability is enabled but credentials are missing.",
                code="langfuse_credentials_missing",
                details={"missing_env_vars": missing_env_vars},
            )

        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=settings.observability.base_url,
            environment=settings.observability.environment,
            release=settings.service.version,
            sample_rate=settings.observability.sample_rate,
            tracing_enabled=True,
        )
        _enable_agent_framework_observability(
            enable_sensitive_data=settings.observability.capture_mode == "full",
        )
        return cls(
            client=client,
            flush_on_shutdown=settings.observability.flush_on_shutdown,
        )

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
        return _LangfuseObservationContext(
            client=self._client,
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
        try:
            self._client.create_score(
                name=name,
                value=_normalize_score_value(value),
                session_id=session_id,
                trace_id=trace_id,
                data_type=cast(Any, data_type),
                comment=comment,
                metadata=to_observability_payload(metadata),
            )
        except Exception:
            logger.warning("Langfuse score creation failed", exc_info=True)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.warning("Langfuse flush failed", exc_info=True)

    async def aclose(self) -> None:
        try:
            if self._flush_on_shutdown:
                self._client.flush()
            self._client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown failed", exc_info=True)


def _enable_agent_framework_observability(*, enable_sensitive_data: bool) -> None:
    try:
        import agent_framework

        _ensure_agent_framework_version(agent_framework)
        from agent_framework.observability import enable_instrumentation

        enable_instrumentation(enable_sensitive_data=enable_sensitive_data)
    except Exception:
        logger.warning("Could not enable Agent Framework OpenTelemetry", exc_info=True)


def _metadata_for_propagation(metadata: Any | None) -> dict[str, str] | None:
    if not isinstance(metadata, dict):
        return None
    propagated: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, dict | list | tuple | set):
            continue
        propagated[str(key)] = str(value)
    return propagated or None


def _normalize_score_value(value: float | str | bool) -> float | str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value
