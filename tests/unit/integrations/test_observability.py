from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Literal, cast

import pytest

from sumampa_odoo_agent.config import AppSettings, AttachmentSettings
from sumampa_odoo_agent.integrations.agent.framework import _ensure_agent_framework_version
from sumampa_odoo_agent.integrations.observability.langfuse import (
    LangfuseObservabilityProvider,
    _enable_agent_framework_observability,
)
from sumampa_odoo_agent.integrations.observability.odoo import ObservedOdooGateway
from sumampa_odoo_agent.integrations.odoo.dry_run import DryRunOdooClient
from sumampa_odoo_agent.integrations.telemetry import OpenTelemetryObservabilityProvider
from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.conversation import ConversationService, ConversationTurnInput
from sumampa_odoo_agent.services.errors import ConfigurationError
from sumampa_odoo_agent.services.models.odoo import SearchInput
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.services.observability import (
    CompositeObservabilityProvider,
    Observation,
    ObservationLevel,
    ObservationType,
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


class FakeRuntime:
    async def run(self, request: AgentRunInput) -> AgentRunResult:
        return AgentRunResult(
            mode="fake",
            session_id=request.session_id or "generated",
            text="Listo.",
        )


class BrokenLangfuseClient:
    def start_as_current_observation(self, **kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("langfuse unavailable")

    def flush(self) -> None:
        raise RuntimeError("flush unavailable")

    def shutdown(self) -> None:
        raise RuntimeError("shutdown unavailable")


class FlushClient:
    def __init__(self) -> None:
        self.flushed = False
        self.shutdown_called = False

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.shutdown_called = True


class ForceFlushProvider:
    def __init__(self) -> None:
        self.timeout_millis: int | None = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.timeout_millis = timeout_millis
        return True


def test_langfuse_provider_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    settings = AppSettings.model_validate(
        {
            "service": {"name": "sumampa-test", "version": "0.1.0"},
            "observability": {"mode": "langfuse"},
        }
    )

    with pytest.raises(ConfigurationError) as exc_info:
        LangfuseObservabilityProvider.from_settings(settings)

    assert exc_info.value.code == "langfuse_credentials_missing"


def test_agent_framework_observability_handles_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_framework

    monkeypatch.delattr(agent_framework, "__version__", raising=False)
    _enable_agent_framework_observability(enable_sensitive_data=True)
    assert getattr(agent_framework, "__version__", None) is not None
    _ensure_agent_framework_version(agent_framework)


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


@pytest.mark.asyncio
async def test_langfuse_provider_flushes_on_shutdown() -> None:
    client = FlushClient()
    provider = LangfuseObservabilityProvider(client=client, flush_on_shutdown=True)

    await provider.aclose()

    assert client.flushed is True
    assert client.shutdown_called is True


@pytest.mark.asyncio
async def test_observability_failure_does_not_fail_conversation_turn() -> None:
    provider = LangfuseObservabilityProvider(
        client=BrokenLangfuseClient(),
        flush_on_shutdown=False,
    )
    service = ConversationService(
        FakeRuntime(),
        attachment_ingestion=AttachmentIngestionService(
            object_store=_NeverUsedObjectStore(),
            settings=AttachmentSettings(store_mode="memory"),
        ),
        observability=provider,
    )

    result = await service.run_turn(
        ConversationTurnInput(
            conversation_id="conv-1",
            channel="whatsapp",
            user_id="user-1",
            text="hola",
            attachments=[],
            context={},
        )
    )

    assert result.assistant_text == "Listo."


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


class _NeverUsedObjectStore:
    async def put_object(self, **kwargs: Any) -> Any:
        raise AssertionError("object store should not be used")

    async def aclose(self) -> None:
        return None
