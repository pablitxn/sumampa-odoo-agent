"""E2E route tests for the stateful sales demo API."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Literal

from fastapi.testclient import TestClient

from sumampa_odoo_agent.api.main import create_app
from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent.sales import MicrosoftSalesDemoAgentRuntime
from sumampa_odoo_agent.services.contracts import SalesBridgePort
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.services.observability import Observation, ObservationType


def _test_settings() -> AppSettings:
    return AppSettings.model_validate(
        {
            "service": {"name": "sumampa-test", "version": "0.1.0"},
            "session_store": {"mode": "memory"},
            "attachments": {"store_mode": "memory"},
        }
    )


def test_demo_scenarios_endpoint_returns_dropdown_options() -> None:
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        response = client.get("/demo/api/scenarios")

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"] == "sales-demo-v1"
    assert "commercial_state" in payload["params"]
    assert payload["scenarios"][0]["scenario_id"] == "new-lead-empty"
    assert {scenario["scenario_id"] for scenario in payload["scenarios"]} >= {
        "new-lead-empty",
        "interested-lead",
        "activation-link-missing",
        "follow-up-due",
    }
    assert payload["params"]["commercial_state"]["options"][0] == {
        "value": "unset",
        "label": "Unset",
    }


def test_demo_messages_run_agent_against_mutable_mock(
    monkeypatch: Any,
) -> None:
    async def fake_run(
        self: MicrosoftSalesDemoAgentRuntime,
        request: AgentRunInput,
        *,
        bridge: SalesBridgePort,
    ) -> AgentRunResult:
        del self
        await bridge.read_lead_state()
        await bridge.execute_sales_tool("set_interest_tags", {"tags": ["rice"]})
        await bridge.send_public_message("Te paso el link de activacion y te acompano.")
        return AgentRunResult(
            mode="fake-sales-agent",
            session_id=request.session_id or "sales-conversation-1",
            text="handled",
        )

    monkeypatch.setattr(MicrosoftSalesDemoAgentRuntime, "run", fake_run)
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        response = client.post(
            "/demo/api/messages",
            json={
                "conversation_id": "sales-conversation-1",
                "user_id": "demo-user-001",
                "scenario_id": "interested-lead",
                "scenario_params": {"commercial_state": "interested"},
                "text": "Me interesa comprar por mayor.",
                "eval_tags": ["eval:candidate"],
            },
        )
        reset = client.post("/demo/api/conversations/sales-conversation-1/reset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["text"] == "Te paso el link de activacion y te acompano."
    assert "rice" in payload["state"]["lead"]["interest_tags"]
    assert [call["tool"] for call in payload["recent_tool_calls"]] == [
        "read_lead_state",
        "execute_sales_tool",
        "send_public_message",
    ]
    assert reset.json() == {"conversation_id": "sales-conversation-1", "reset": True}


def test_demo_conversation_exports_turns_as_jsonl(monkeypatch: Any) -> None:
    async def fake_run(
        self: MicrosoftSalesDemoAgentRuntime,
        request: AgentRunInput,
        *,
        bridge: SalesBridgePort,
    ) -> AgentRunResult:
        del self
        await bridge.execute_sales_tool(
            "update_lead_commercial_state",
            {"commercial_state": "interested"},
        )
        await bridge.send_public_message("Gracias, te hago unas preguntas para calificar.")
        return AgentRunResult(
            mode="fake-sales-agent",
            session_id=request.session_id or "sales-export-1",
            text="handled",
        )

    monkeypatch.setattr(MicrosoftSalesDemoAgentRuntime, "run", fake_run)
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        message = client.post(
            "/demo/api/messages",
            json={
                "conversation_id": "sales-export-1",
                "user_id": "demo-user-001",
                "scenario_id": "new-lead-empty",
                "scenario_params": {},
                "text": "Hola, queria saber como trabajan.",
                "eval_tags": ["eval:candidate"],
            },
        )
        feedback = client.post(
            "/demo/api/conversations/sales-export-1/feedback",
            json={
                "user_id": "demo-user-001",
                "feedback_tags": ["manual:partial", "manual:wrong-state"],
                "feedback_text": "State changed, but reply was incomplete.",
            },
        )
        export = client.get("/demo/api/conversations/sales-export-1/export.jsonl")

    assert message.status_code == 200
    assert feedback.status_code == 200
    assert feedback.json() == {
        "conversation_id": "sales-export-1",
        "feedback_tags": ["manual:partial", "manual:wrong-state"],
        "feedback_count": 1,
    }
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in export.text.splitlines()]
    assert len(lines) == 1
    item = lines[0]
    assert item["id"] == "sales-export-1:turn-1"
    assert item["input"]["scenario_id"] == "new-lead-empty"
    assert item["expected_output"] is None
    assert item["metadata"]["requires_expected_output_review"] is True
    assert item["metadata"]["manual_feedback_tags"] == [
        "manual:partial",
        "manual:wrong-state",
    ]
    assert item["metadata"]["manual_feedback"][0]["feedback_text"] == (
        "State changed, but reply was incomplete."
    )
    assert item["candidate_output"]["assistant_messages"] == [
        "Gracias, te hago unas preguntas para calificar."
    ]
    assert item["metadata"]["state_mutations"][0]["path"] == "lead.commercial_state"


def test_demo_messages_lock_scenario_per_conversation(monkeypatch: Any) -> None:
    async def fake_run(
        self: MicrosoftSalesDemoAgentRuntime,
        request: AgentRunInput,
        *,
        bridge: SalesBridgePort,
    ) -> AgentRunResult:
        del self, bridge
        return AgentRunResult(
            mode="fake-sales-agent",
            session_id=request.session_id or "sales-conversation-locked",
            text="ok",
        )

    monkeypatch.setattr(MicrosoftSalesDemoAgentRuntime, "run", fake_run)
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        first = client.post(
            "/demo/api/messages",
            json={
                "conversation_id": "sales-conversation-locked",
                "user_id": "demo-user-001",
                "scenario_id": "interested-lead",
                "scenario_params": {},
                "text": "Hola.",
            },
        )
        second = client.post(
            "/demo/api/messages",
            json={
                "conversation_id": "sales-conversation-locked",
                "user_id": "demo-user-001",
                "scenario_id": "opt-out",
                "scenario_params": {},
                "text": "No me escribas.",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "demo_sales_scenario_locked"


def test_demo_conversation_tags_include_scenario_metadata(
    monkeypatch: Any,
) -> None:
    observability = _RecordingObservability()
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.app.build_observability_provider",
        lambda settings: observability,
    )
    app = create_app(settings=_test_settings())

    with TestClient(app) as client:
        response = client.post(
            "/demo/api/conversation-tags",
            json={
                "conversation_id": "sales-tags-1",
                "user_id": "demo-user-001",
                "scenario_id": "activation-link-missing",
                "scenario_params": {"activation_link_status": "missing"},
                "eval_tags": ["eval:dataset-ready"],
                "context": {"transcript": [{"role": "user", "text": "No llego el link."}]},
            },
        )

    assert response.status_code == 200
    assert response.json()["eval_tags"] == ["eval:dataset-ready"]
    observation = observability.by_name["conversation.tags"][0]
    assert observation["input"]["scenario"]["scenario_id"] == "activation-link-missing"
    assert observation["input"]["mock_state"]["activation"]["link_status"] == "missing"


class _RecordingObservation:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def update(self, **kwargs: Any) -> None:
        self._record.update({key: value for key, value in kwargs.items() if value is not None})

    def score_trace(self, **kwargs: Any) -> None:
        self._record.setdefault("scores", []).append(dict(kwargs))


class _RecordingContext(AbstractContextManager[Observation]):
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record

    def __enter__(self) -> Observation:
        return _RecordingObservation(self._record)

    def __exit__(self, *args: Any) -> Literal[False]:
        del args
        return False


class _RecordingObservability:
    def __init__(self) -> None:
        self.by_name: dict[str, list[dict[str, Any]]] = {}

    def start_observation(
        self,
        *,
        name: str,
        as_type: ObservationType = "span",
        **kwargs: Any,
    ) -> AbstractContextManager[Observation]:
        record = {"name": name, "as_type": as_type, **kwargs}
        self.by_name.setdefault(name, []).append(record)
        return _RecordingContext(record)

    def create_score(self, **kwargs: Any) -> None:
        self.by_name.setdefault("score", []).append(dict(kwargs))

    def flush(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
