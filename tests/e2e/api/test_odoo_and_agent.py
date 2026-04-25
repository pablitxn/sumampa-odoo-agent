"""E2E smoke tests for agent-facing conversation flows."""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.services.observability import Observation, ObservationType


def _image_attachment(filename: str = "attachment.jpg") -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": "image/jpeg",
        "content_base64": base64.b64encode(b"fake-image").decode("ascii"),
    }


def _video_attachment(filename: str = "clip.mp4") -> dict[str, str]:
    return {
        "filename": filename,
        "mime_type": "video/mp4",
        "content_base64": base64.b64encode(b"fake-video").decode("ascii"),
    }


def _test_settings() -> AppSettings:
    return AppSettings.model_validate(
        {
            "service": {"name": "sumampa-test", "version": "0.1.0"},
            "agent": {"mode": "openai"},
            "session_store": {"mode": "memory"},
            "attachments": {"store_mode": "memory"},
        }
    )


@pytest.fixture(autouse=True)
def patch_runtime_for_api_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHID_AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_messages_endpoint_delegates_to_agent() -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        context = request.context.to_agent_context()
        assert request.prompt == "review the products"
        assert context["transport"]["channel"] == "whatsapp"
        assert context["transport"]["user_id"] == "5491112345678"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=request.session_id or "conversation-1",
            text="I found 2 pending products to review.",
        )

    app = create_app(settings=_test_settings())
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "conversation-1",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "text": "review the products",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == "conversation-1"
    assert payload["messages"][0]["text"] == "I found 2 pending products to review."


def test_messages_endpoint_serializes_attachments_for_agent() -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        context = request.context.to_agent_context()
        assert request.prompt == ""
        attachments = context["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "attachment.jpg"
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id="attachment-session",
            text="Send me the next confirmation.",
        )

    app = create_app(settings=_test_settings())
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/messages",
                json={
                    "conversation_id": "attachment-session",
                    "channel": "whatsapp",
                    "user_id": "5491112345678",
                    "attachments": [_image_attachment()],
                    "context": {"customer_name": "Sumampa SRL"},
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["text"] == "Send me the next confirmation."


def test_messages_endpoint_fails_before_agent_for_unsupported_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self, request
        raise AssertionError("agent runtime should not be called")

    app = create_app(settings=_test_settings())
    monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "conversation_id": "video-session",
                "channel": "whatsapp",
                "user_id": "5491112345678",
                "attachments": [_video_attachment()],
            },
        )

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_attachment_type"


def test_messages_endpoint_contract_is_unchanged_with_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=request.session_id or "observed-session",
            text="Observability kept the API shape intact.",
        )

    observability = _RecordingObservability()
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.app.build_observability_provider",
        lambda settings: observability,
    )
    monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "conversation_id": "observed-session",
                "channel": "whatsapp",
                "user_id": "5491112345678",
                "text": "hola",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "conversation_id": "observed-session",
        "messages": [
            {"role": "assistant", "text": "Observability kept the API shape intact."}
        ],
    }
    assert "conversation.turn" in observability.names


def test_messages_endpoint_records_operational_metrics_and_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        self: MicrosoftAgentFrameworkOpenAIService,
        request: AgentRunInput,
    ) -> AgentRunResult:
        del self
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=request.session_id or "metrics-session",
            text="Metrics recorded.",
        )

    observability = _RecordingObservability()
    metrics = _RecordingMetrics()
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.app.build_observability_provider",
        lambda settings: observability,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.api.main.bootstrap_telemetry",
        lambda settings: _FakeTelemetryRuntime(metrics),
    )
    monkeypatch.setattr(MicrosoftAgentFrameworkOpenAIService, "run", fake_run)
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/messages",
            json={
                "conversation_id": "metrics-session",
                "channel": "whatsapp",
                "user_id": "5491112345678",
                "text": "hola",
            },
        )

    assert response.status_code == 200
    assert "conversation.turn" in observability.names
    assert metrics.http_requests[0]["route"] == "/api/v1/messages"
    assert metrics.http_requests[0]["status"] == 200
    assert metrics.conversation_turns[0]["channel"] == "whatsapp"
    assert metrics.conversation_turns[0]["result"] == "success"


class _RecordingObservation:
    def update(self, **kwargs: Any) -> None:
        del kwargs

    def score_trace(self, **kwargs: Any) -> None:
        del kwargs


class _RecordingContext(AbstractContextManager[Observation]):
    def __enter__(self) -> Observation:
        return _RecordingObservation()

    def __exit__(self, *args: Any) -> Literal[False]:
        del args
        return False


class _RecordingObservability:
    def __init__(self) -> None:
        self.names: list[str] = []

    def start_observation(
        self,
        *,
        name: str,
        as_type: ObservationType = "span",
        **kwargs: Any,
    ) -> AbstractContextManager[Observation]:
        del as_type, kwargs
        self.names.append(name)
        return _RecordingContext()

    def create_score(self, **kwargs: Any) -> None:
        del kwargs

    def flush(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _RecordingMetrics:
    def __init__(self) -> None:
        self.http_requests: list[dict[str, Any]] = []
        self.conversation_turns: list[dict[str, Any]] = []

    def start_timer(self) -> Any:
        return lambda: 0.001

    def record_http_request(self, **kwargs: Any) -> None:
        self.http_requests.append(dict(kwargs))

    def record_conversation_turn(self, **kwargs: Any) -> None:
        self.conversation_turns.append(dict(kwargs))

    def record_odoo_operation(self, **kwargs: Any) -> None:
        del kwargs


class _FakeTelemetryRuntime:
    def __init__(self, metrics: _RecordingMetrics) -> None:
        self.observability = _RecordingObservability()
        self.metrics = metrics
        self.enabled = True

    async def aclose(self) -> None:
        return None
