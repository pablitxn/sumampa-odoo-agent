"""Stateful sales demo scenarios and mocks."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from sumampa_odoo_agent.integrations.agent.sales import MicrosoftSalesDemoAgentRuntime
from sumampa_odoo_agent.services.contracts import SalesBridgePort
from sumampa_odoo_agent.services.models.runtime import (
    AgentRunInput,
    AgentRunResult,
    ConversationRuntimeContext,
    TransportContext,
)
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
)
from sumampa_odoo_agent.services.session_state import normalize_eval_tags

DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[3] / "demo" / "scenarios" / "sales-v1.json"


class DemoSalesError(Exception):
    """Base class for demo sales validation errors."""

    code = "demo_sales_error"


class DemoSalesScenarioNotFoundError(DemoSalesError):
    code = "demo_sales_scenario_not_found"


class DemoSalesValidationError(DemoSalesError):
    code = "demo_sales_validation_error"


class DemoSalesScenarioLockedError(DemoSalesError):
    code = "demo_sales_scenario_locked"


class DemoSalesConversationNotFoundError(DemoSalesError):
    code = "demo_sales_conversation_not_found"


class DemoSalesParamOption(BaseModel):
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)


class DemoSalesParamDefinition(BaseModel):
    label: str = Field(min_length=1)
    options: list[DemoSalesParamOption] = Field(min_length=1)


class DemoSalesScenarioDefinition(BaseModel):
    scenario_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""
    default_params: dict[str, str] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    quick_messages: list[str] = Field(default_factory=list)


class DemoSalesScenarioCatalog(BaseModel):
    catalog_version: str = Field(min_length=1)
    params: dict[str, DemoSalesParamDefinition] = Field(default_factory=dict)
    scenarios: list[DemoSalesScenarioDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> DemoSalesScenarioCatalog:
        seen: set[str] = set()
        for scenario in self.scenarios:
            if scenario.scenario_id in seen:
                raise ValueError(f"duplicate scenario_id: {scenario.scenario_id}")
            seen.add(scenario.scenario_id)
            for name, value in scenario.default_params.items():
                _validate_param_value(self.params, name=name, value=value)
        return self


@dataclass(frozen=True, slots=True)
class ResolvedDemoSalesScenario:
    scenario: DemoSalesScenarioDefinition
    params: dict[str, str]
    initial_state: dict[str, Any]


@dataclass(slots=True)
class DemoSalesTurnInput:
    conversation_id: str
    user_id: str
    text: str
    scenario_id: str
    scenario_params: dict[str, str]
    channel: str = "whatsapp"
    context: dict[str, Any] = field(default_factory=dict)
    eval_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DemoSalesTurnResult:
    conversation_id: str
    messages: list[str]
    scenario: dict[str, Any]
    state: dict[str, Any]
    recent_tool_calls: list[dict[str, Any]]
    trace_input: dict[str, Any]
    trace_output: dict[str, Any]


@dataclass(slots=True)
class DemoSalesTagsInput:
    conversation_id: str
    user_id: str
    eval_tags: list[str]
    scenario_id: str | None = None
    scenario_params: dict[str, str] = field(default_factory=dict)
    channel: str = "whatsapp"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DemoSalesTagsResult:
    conversation_id: str
    eval_tags: list[str]


@dataclass(slots=True)
class DemoSalesFeedbackInput:
    conversation_id: str
    user_id: str
    feedback_tags: list[str]
    feedback_text: str = ""
    channel: str = "whatsapp"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DemoSalesFeedbackResult:
    conversation_id: str
    feedback_tags: list[str]
    feedback_count: int


class DemoSalesRuntime(Protocol):
    async def run(
        self,
        request: AgentRunInput,
        *,
        bridge: SalesBridgePort,
    ) -> AgentRunResult:
        """Run a sales demo turn."""


@dataclass(slots=True)
class DemoSalesSession:
    conversation_id: str
    scenario_id: str
    scenario_version: str
    scenario_params: dict[str, str]
    initial_state: dict[str, Any]
    current_state: dict[str, Any]
    channel: str = "whatsapp"
    user_id: str = "demo-user"
    transcript: list[dict[str, Any]] = field(default_factory=list)
    eval_tags: list[str] = field(default_factory=list)
    manual_feedback: list[dict[str, Any]] = field(default_factory=list)
    dataset_items: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())


class DemoSalesScenarioRepository:
    """Loads and clones versioned sales demo scenarios."""

    def __init__(self, catalog: DemoSalesScenarioCatalog) -> None:
        self._catalog = catalog
        self._scenarios = {scenario.scenario_id: scenario for scenario in catalog.scenarios}

    @classmethod
    def from_default(cls) -> DemoSalesScenarioRepository:
        return cls.from_path(DEFAULT_SCENARIO_PATH)

    @classmethod
    def from_path(cls, path: Path) -> DemoSalesScenarioRepository:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(DemoSalesScenarioCatalog.model_validate(payload))

    @property
    def catalog_version(self) -> str:
        return self._catalog.catalog_version

    def list_options(self) -> dict[str, Any]:
        return {
            "catalog_version": self._catalog.catalog_version,
            "params": {
                name: definition.model_dump(mode="json")
                for name, definition in self._catalog.params.items()
            },
            "scenarios": [
                {
                    "scenario_id": scenario.scenario_id,
                    "version": scenario.version,
                    "label": scenario.label,
                    "description": scenario.description,
                    "default_params": dict(scenario.default_params),
                    "quick_messages": list(scenario.quick_messages),
                }
                for scenario in self._catalog.scenarios
            ],
        }

    def resolve(
        self,
        *,
        scenario_id: str,
        params: dict[str, str] | None = None,
    ) -> ResolvedDemoSalesScenario:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise DemoSalesScenarioNotFoundError(f"unknown scenario_id: {scenario_id}")

        resolved_params = dict(scenario.default_params)
        for name, value in (params or {}).items():
            _validate_param_value(self._catalog.params, name=name, value=value)
            resolved_params[name] = value

        state = deepcopy(scenario.initial_state)
        _apply_params_to_state(state, resolved_params)
        return ResolvedDemoSalesScenario(
            scenario=scenario,
            params=resolved_params,
            initial_state=state,
        )


class DemoSalesSessionStore:
    """Process-local mutable scenario sessions keyed by conversation_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, DemoSalesSession] = {}

    def get_or_create(
        self,
        *,
        conversation_id: str,
        resolved: ResolvedDemoSalesScenario,
        channel: str = "whatsapp",
        user_id: str = "demo-user",
    ) -> DemoSalesSession:
        existing = self._sessions.get(conversation_id)
        if existing is not None:
            if (
                existing.scenario_id != resolved.scenario.scenario_id
                or existing.scenario_params != resolved.params
            ):
                raise DemoSalesScenarioLockedError(
                    "scenario and params are locked for an existing conversation"
                )
            existing.channel = channel
            existing.user_id = user_id
            return existing

        session = DemoSalesSession(
            conversation_id=conversation_id,
            scenario_id=resolved.scenario.scenario_id,
            scenario_version=resolved.scenario.version,
            scenario_params=dict(resolved.params),
            initial_state=deepcopy(resolved.initial_state),
            current_state=deepcopy(resolved.initial_state),
            channel=channel,
            user_id=user_id,
        )
        self._sessions[conversation_id] = session
        return session

    def get(self, conversation_id: str) -> DemoSalesSession | None:
        return self._sessions.get(conversation_id)

    def reset(self, conversation_id: str) -> bool:
        return self._sessions.pop(conversation_id, None) is not None


class DemoSalesBridge:
    """Stateful local mock for Chatwoot/Odoo/Evolution sales bridge operations."""

    def __init__(self, session: DemoSalesSession, *, turn_id: str) -> None:
        self._session = session
        self._turn_id = turn_id

    async def read_lead_state(self) -> dict[str, Any]:
        result = compact_sales_state(self._session.current_state)
        self._record_tool("read_lead_state", {}, result=result, mutations=[])
        return result

    async def read_reader_output(self, name: str) -> dict[str, Any]:
        reader_outputs = _dict_section(self._session.current_state, "reader_outputs")
        result = {
            "name": name,
            "found": name in reader_outputs,
            "value": deepcopy(reader_outputs.get(name)),
        }
        self._record_tool("read_sales_reader_output", {"name": name}, result=result, mutations=[])
        return result

    async def read_transcript(self) -> dict[str, Any]:
        result = {
            "conversation_id": self._session.conversation_id,
            "messages": deepcopy(self._session.transcript),
        }
        self._record_tool("read_sales_transcript", {}, result=result, mutations=[])
        return result

    async def execute_sales_tool(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        action_name = action.strip()
        args = dict(arguments)
        mutations: list[dict[str, Any]] = []
        state = self._session.current_state
        lead = _dict_section(state, "lead")
        followup = _dict_section(state, "followup")
        payment = _dict_section(state, "payment")
        activation = _dict_section(state, "activation")

        if action_name == "record_opt_out":
            reason = str(args.get("reason") or "Lead requested opt-out.")
            _set_value(lead, "opted_out", True, mutations, "lead.opted_out")
            _set_value(lead, "followup_disabled", True, mutations, "lead.followup_disabled")
            _set_value(lead, "commercial_state", "opted_out", mutations, "lead.commercial_state")
            _set_value(followup, "state", "disabled", mutations, "followup.state")
            _append_unique(lead, "tags", ["opt-out"], mutations, "lead.tags")
            result = {"ok": True, "action": action_name, "reason": reason}
        elif action_name == "request_human_review":
            reason = str(args.get("reason") or "Human review requested.")
            priority = str(args.get("priority") or "normal")
            _set_value(
                lead,
                "human_review_requested",
                True,
                mutations,
                "lead.human_review_requested",
            )
            _set_value(lead, "control_state", "human_review", mutations, "lead.control_state")
            _append_unique(lead, "tags", ["human-review"], mutations, "lead.tags")
            result = {"ok": True, "action": action_name, "reason": reason, "priority": priority}
        elif action_name == "set_interest_tags":
            tags = _string_list(args.get("tags"))
            _append_unique(lead, "interest_tags", tags, mutations, "lead.interest_tags")
            result = {"ok": True, "action": action_name, "tags": tags}
        elif action_name == "update_lead_commercial_state":
            commercial_state = str(args.get("commercial_state") or args.get("state") or "").strip()
            if not commercial_state:
                result = {"ok": False, "action": action_name, "error": "commercial_state required"}
            else:
                _set_value(
                    lead,
                    "commercial_state",
                    commercial_state,
                    mutations,
                    "lead.commercial_state",
                )
                result = {"ok": True, "action": action_name, "commercial_state": commercial_state}
        elif action_name == "schedule_followup":
            followup_state = str(args.get("followup_state") or args.get("state") or "scheduled")
            window = args.get("window") or args.get("scheduled_for") or "business_hours"
            _set_value(followup, "state", followup_state, mutations, "followup.state")
            _set_value(followup, "window", window, mutations, "followup.window")
            _set_value(
                followup,
                "count",
                int(followup.get("count") or 0) + 1,
                mutations,
                "followup.count",
            )
            _set_value(lead, "followup_disabled", False, mutations, "lead.followup_disabled")
            result = {
                "ok": True,
                "action": action_name,
                "followup_state": followup_state,
                "window": window,
            }
        elif action_name == "disable_followup":
            reason = str(args.get("reason") or "Follow-up disabled.")
            _set_value(lead, "followup_disabled", True, mutations, "lead.followup_disabled")
            _set_value(followup, "state", "disabled", mutations, "followup.state")
            result = {"ok": True, "action": action_name, "reason": reason}
        elif action_name == "set_contact_role":
            role = str(args.get("contact_role") or args.get("role") or "").strip()
            if not role:
                result = {"ok": False, "action": action_name, "error": "contact_role required"}
            else:
                _set_value(lead, "contact_role", role, mutations, "lead.contact_role")
                result = {"ok": True, "action": action_name, "contact_role": role}
        elif action_name == "set_control_state":
            control_state = str(args.get("control_state") or args.get("state") or "").strip()
            if not control_state:
                result = {"ok": False, "action": action_name, "error": "control_state required"}
            else:
                _set_value(lead, "control_state", control_state, mutations, "lead.control_state")
                result = {"ok": True, "action": action_name, "control_state": control_state}
        elif action_name == "mark_activation_link_sent":
            link = str(
                args.get("activation_link")
                or activation.get("activation_link")
                or f"https://demo.sumampa.test/activate/{lead.get('lead_id', 'lead')}"
            )
            _set_value(activation, "link_status", "sent", mutations, "activation.link_status")
            _set_value(activation, "activation_link", link, mutations, "activation.activation_link")
            result = {"ok": True, "action": action_name, "activation_link": link}
        elif action_name == "mark_payment_received":
            paid_at = str(args.get("paid_at") or _utc_now())
            _set_value(payment, "state", "paid", mutations, "payment.state")
            _set_value(payment, "last_payment_at", paid_at, mutations, "payment.last_payment_at")
            _set_value(lead, "commercial_state", "post_payment", mutations, "lead.commercial_state")
            result = {"ok": True, "action": action_name, "paid_at": paid_at}
        else:
            result = {"ok": False, "action": action_name, "error": "unknown sales action"}

        self._record_tool(
            "execute_sales_tool",
            {"action": action_name, "arguments": args},
            result=result,
            mutations=mutations,
        )
        self._session.updated_at = _utc_now()
        return result

    async def add_private_note(self, note: str) -> dict[str, Any]:
        notes = _list_section(self._session.current_state, "notes")
        payload = {
            "note": note,
            "created_at": _utc_now(),
            "visibility": "private",
            "turn_id": self._turn_id,
        }
        notes.append(payload)
        result = {"ok": True, "note": deepcopy(payload)}
        self._record_tool(
            "add_private_note",
            {"note": note},
            result=result,
            mutations=[{"path": "notes", "before": None, "after": deepcopy(payload)}],
        )
        self._session.updated_at = _utc_now()
        return result

    async def send_public_message(self, text: str) -> dict[str, Any]:
        public_messages = _list_section(self._session.current_state, "public_messages")
        transport = _dict_section(self._session.current_state, "transport")
        payload = {
            "text": text,
            "created_at": _utc_now(),
            "channel": str(transport.get("channel") or "whatsapp"),
            "transport": {
                "chatwoot_conversation_id": transport.get("chatwoot_conversation_id"),
                "evolution_instance": transport.get("evolution_instance"),
            },
            "turn_id": self._turn_id,
        }
        public_messages.append(payload)
        result = {"ok": True, "message": deepcopy(payload)}
        self._record_tool(
            "send_public_message",
            {"text": text},
            result=result,
            mutations=[
                {"path": "public_messages", "before": None, "after": deepcopy(payload)}
            ],
        )
        self._session.updated_at = _utc_now()
        return result

    def _record_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        result: dict[str, Any],
        mutations: list[dict[str, Any]],
    ) -> None:
        ledger = _list_section(self._session.current_state, "tool_ledger")
        ledger.append(
            {
                "tool": tool,
                "arguments": deepcopy(arguments),
                "result": deepcopy(result),
                "mutations": deepcopy(mutations),
                "timestamp": _utc_now(),
                "turn_id": self._turn_id,
            }
        )


class DemoSalesService:
    """Orchestrates demo sales turns and emits Phoenix-curatable trace payloads."""

    def __init__(
        self,
        runtime: DemoSalesRuntime,
        *,
        scenarios: DemoSalesScenarioRepository | None = None,
        sessions: DemoSalesSessionStore | None = None,
        observability: ObservabilityProvider | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._scenarios = scenarios or DemoSalesScenarioRepository.from_default()
        self._sessions = sessions or DemoSalesSessionStore()
        self._observability = observability or NoOpObservabilityProvider()
        self._trace_metadata = trace_metadata or {}

    @classmethod
    def from_settings(
        cls,
        *,
        model: str,
        api_key_env_var: str,
        base_url: str | None,
        session_store: Any,
        observability: ObservabilityProvider,
        trace_metadata: dict[str, Any] | None = None,
        scenarios: DemoSalesScenarioRepository | None = None,
    ) -> DemoSalesService:
        runtime = MicrosoftSalesDemoAgentRuntime(
            model=model,
            api_key_env_var=api_key_env_var,
            base_url=base_url,
            session_store=session_store,
            observability=observability,
        )
        return cls(
            runtime,
            scenarios=scenarios,
            observability=observability,
            trace_metadata=trace_metadata,
        )

    def list_scenarios(self) -> dict[str, Any]:
        return self._scenarios.list_options()

    async def run_turn(self, request: DemoSalesTurnInput) -> DemoSalesTurnResult:
        started_at = time.perf_counter()
        eval_tags = normalize_eval_tags(request.eval_tags)
        resolved = self._scenarios.resolve(
            scenario_id=request.scenario_id,
            params=request.scenario_params,
        )
        session = self._sessions.get_or_create(
            conversation_id=request.conversation_id,
            resolved=resolved,
            channel=request.channel,
            user_id=request.user_id,
        )
        session.eval_tags = eval_tags

        turn_id = f"turn-{len(session.transcript) + 1}"
        state_before = deepcopy(session.current_state)
        transcript_before = deepcopy(session.transcript)
        current_turn = {
            "role": "user",
            "text": request.text,
            "timestamp": _utc_now(),
            "turn_id": turn_id,
        }
        session.transcript.append(current_turn)

        initial_tool_count = len(_list_section(session.current_state, "tool_ledger"))
        initial_public_count = len(_list_section(session.current_state, "public_messages"))
        initial_note_count = len(_list_section(session.current_state, "notes"))
        trace_input = _trace_input(
            request=request,
            session=session,
            state_before=state_before,
            transcript_before=transcript_before,
            current_turn=current_turn,
            eval_tags=eval_tags,
        )
        bridge = DemoSalesBridge(session, turn_id=turn_id)
        agent_context = dict(request.context)
        agent_context["demo_sales"] = {
            "scenario_id": session.scenario_id,
            "scenario_version": session.scenario_version,
            "params": dict(session.scenario_params),
            "initial_state": deepcopy(session.initial_state),
            "state_before_turn": state_before,
            "transcript_before_turn": transcript_before,
            "current_turn": current_turn,
            "eval_tags": eval_tags,
        }
        metadata = {
            **self._trace_metadata,
            "transport.channel": request.channel,
            "transport.user_id": request.user_id,
            "transport.conversation_id": request.conversation_id,
            "demo.scenario_id": session.scenario_id,
            "demo.scenario_version": session.scenario_version,
            "eval.tags": eval_tags,
        }
        if eval_tags:
            metadata["evalTags"] = ",".join(eval_tags)

        with self._observability.start_observation(
            name="demo.message",
            as_type="agent",
            input=trace_input,
            metadata=metadata,
            user_id=request.user_id,
            session_id=request.conversation_id,
            tags=[
                "demo",
                "sales",
                "conversation",
                f"scenario:{session.scenario_id}",
                *eval_tags,
            ],
            version=str(self._trace_metadata.get("service.version", "")) or None,
            model=str(self._trace_metadata.get("agent.model", "")) or None,
        ) as observation:
            try:
                result = await self._runtime.run(
                    AgentRunInput(
                        prompt=request.text.strip(),
                        context=ConversationRuntimeContext(
                            transport=TransportContext(
                                channel=request.channel,
                                user_id=request.user_id,
                                conversation_id=request.conversation_id,
                            ),
                            context=agent_context,
                        ),
                        session_id=request.conversation_id,
                        eval_tags=eval_tags,
                    ),
                    bridge=bridge,
                )
            except Exception as exc:
                output = {
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "state_after_turn": compact_sales_state(session.current_state),
                    "transcript_after_turn": deepcopy(session.transcript),
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                }
                observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                    output=output,
                )
                observation.score_trace(
                    name="error",
                    value=1.0,
                    data_type="NUMERIC",
                    comment=f"{exc.__class__.__name__}: {exc}",
                )
                raise

            state_after = deepcopy(session.current_state)
            new_public_messages = _list_section(state_after, "public_messages")[
                initial_public_count:
            ]
            assistant_messages = [
                str(message.get("text") or "")
                for message in new_public_messages
                if str(message.get("text") or "").strip()
            ]
            if not assistant_messages and result.text.strip():
                assistant_messages = [result.text.strip()]

            for text in assistant_messages:
                session.transcript.append(
                    {
                        "role": "assistant",
                        "text": text,
                        "timestamp": _utc_now(),
                        "turn_id": turn_id,
                    }
                )
            session.updated_at = _utc_now()
            state_after_with_transcript = deepcopy(session.current_state)
            recent_tool_calls = _list_section(state_after_with_transcript, "tool_ledger")[
                initial_tool_count:
            ]
            output = {
                "conversation_id": result.session_id,
                "assistant_reply": result.text,
                "assistant_messages": assistant_messages,
                "handled": True,
                "reason": "agent_completed",
                "public_messages": new_public_messages,
                "private_notes": _list_section(state_after_with_transcript, "notes")[
                    initial_note_count:
                ],
                "tool_calls": recent_tool_calls,
                "state_after_turn": compact_sales_state(state_after_with_transcript),
                "state_mutations": [
                    mutation
                    for call in recent_tool_calls
                    for mutation in _as_list(call.get("mutations"))
                ],
                "transcript_after_turn": deepcopy(session.transcript),
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "eval_tags": eval_tags,
            }
            session.dataset_items.append(
                _dataset_item_from_turn(
                    session=session,
                    turn_id=turn_id,
                    trace_input=trace_input,
                    trace_output=output,
                    started_at=current_turn["timestamp"],
                )
            )
            observation.update(output=output, metadata={**metadata, "runtime.mode": result.mode})
            observation.score_trace(
                name="error",
                value=0.0,
                data_type="NUMERIC",
                comment="Sales demo turn completed without exception.",
            )

        return DemoSalesTurnResult(
            conversation_id=result.session_id,
            messages=assistant_messages or [result.text],
            scenario=_scenario_payload(session),
            state=compact_sales_state(session.current_state),
            recent_tool_calls=recent_tool_calls,
            trace_input=trace_input,
            trace_output=output,
        )

    async def update_eval_tags(self, request: DemoSalesTagsInput) -> DemoSalesTagsResult:
        eval_tags = normalize_eval_tags(request.eval_tags)
        session = self._sessions.get(request.conversation_id)
        scenario_payload: dict[str, Any] | None = None
        state_payload: dict[str, Any] | None = None
        if session is not None:
            session.eval_tags = eval_tags
            session.updated_at = _utc_now()
            scenario_payload = _scenario_payload(session)
            state_payload = compact_sales_state(session.current_state)
        elif request.scenario_id:
            resolved = self._scenarios.resolve(
                scenario_id=request.scenario_id,
                params=request.scenario_params,
            )
            scenario_payload = {
                "scenario_id": resolved.scenario.scenario_id,
                "scenario_version": resolved.scenario.version,
                "params": dict(resolved.params),
                "catalog_version": self._scenarios.catalog_version,
            }
            state_payload = compact_sales_state(resolved.initial_state)

        trace_input = {
            "conversation_id": request.conversation_id,
            "channel": request.channel,
            "user_id": request.user_id,
            "eval_tags": eval_tags,
            "context": request.context,
            "scenario": scenario_payload,
            "mock_state": state_payload,
        }
        metadata = {
            **self._trace_metadata,
            "transport.channel": request.channel,
            "transport.user_id": request.user_id,
            "transport.conversation_id": request.conversation_id,
            "eval.tags": eval_tags,
        }
        if scenario_payload is not None:
            metadata["demo.scenario_id"] = scenario_payload["scenario_id"]
            metadata["demo.scenario_version"] = scenario_payload["scenario_version"]
        if eval_tags:
            metadata["evalTags"] = ",".join(eval_tags)

        with self._observability.start_observation(
            name="conversation.tags",
            as_type="span",
            input=trace_input,
            output={"conversation_id": request.conversation_id, "eval_tags": eval_tags},
            metadata=metadata,
            user_id=request.user_id,
            session_id=request.conversation_id,
            tags=["conversation", "eval-tags", "demo", "sales", *eval_tags],
            version=str(self._trace_metadata.get("service.version", "")) or None,
            model=str(self._trace_metadata.get("agent.model", "")) or None,
        ):
            pass

        return DemoSalesTagsResult(
            conversation_id=request.conversation_id,
            eval_tags=eval_tags,
        )

    def reset_conversation(self, conversation_id: str) -> bool:
        return self._sessions.reset(conversation_id)

    async def record_manual_feedback(
        self,
        request: DemoSalesFeedbackInput,
    ) -> DemoSalesFeedbackResult:
        feedback_tags = normalize_eval_tags(request.feedback_tags)
        session = self._sessions.get(request.conversation_id)
        if session is None:
            raise DemoSalesConversationNotFoundError(
                f"unknown demo conversation_id: {request.conversation_id}"
            )

        feedback = {
            "feedback_tags": feedback_tags,
            "feedback_text": request.feedback_text.strip(),
            "user_id": request.user_id,
            "channel": request.channel,
            "context": deepcopy(request.context),
            "created_at": _utc_now(),
        }
        session.manual_feedback.append(feedback)
        session.updated_at = _utc_now()
        trace_payload = {
            "conversation_id": request.conversation_id,
            "channel": request.channel,
            "user_id": request.user_id,
            "scenario": _scenario_payload(session),
            "feedback": feedback,
            "state_snapshot": compact_sales_state(session.current_state),
            "transcript": deepcopy(session.transcript),
        }
        metadata = {
            **self._trace_metadata,
            "transport.channel": request.channel,
            "transport.user_id": request.user_id,
            "transport.conversation_id": request.conversation_id,
            "demo.scenario_id": session.scenario_id,
            "demo.scenario_version": session.scenario_version,
            "manual_feedback.tags": feedback_tags,
        }
        with self._observability.start_observation(
            name="conversation.feedback",
            as_type="span",
            input=trace_payload,
            output={
                "conversation_id": request.conversation_id,
                "feedback_tags": feedback_tags,
                "feedback_count": len(session.manual_feedback),
            },
            metadata=metadata,
            user_id=request.user_id,
            session_id=request.conversation_id,
            tags=["conversation", "manual-feedback", "demo", "sales", *feedback_tags],
            version=str(self._trace_metadata.get("service.version", "")) or None,
            model=str(self._trace_metadata.get("agent.model", "")) or None,
        ):
            pass
        return DemoSalesFeedbackResult(
            conversation_id=request.conversation_id,
            feedback_tags=feedback_tags,
            feedback_count=len(session.manual_feedback),
        )

    def export_conversation_jsonl(self, conversation_id: str) -> str:
        session = self._sessions.get(conversation_id)
        if session is None:
            raise DemoSalesConversationNotFoundError(
                f"unknown demo conversation_id: {conversation_id}"
            )
        items = session.dataset_items or [
            _conversation_level_dataset_item(session=session)
        ]
        export_items = [_with_manual_feedback(item, session=session) for item in items]
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in export_items) + "\n"


def compact_sales_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "lead": deepcopy(_dict_section(state, "lead")),
        "payment": deepcopy(_dict_section(state, "payment")),
        "subscription": deepcopy(_dict_section(state, "subscription")),
        "activation": deepcopy(_dict_section(state, "activation")),
        "followup": deepcopy(_dict_section(state, "followup")),
        "transport": deepcopy(_dict_section(state, "transport")),
        "notes": deepcopy(_list_section(state, "notes")[-8:]),
        "public_messages": deepcopy(_list_section(state, "public_messages")[-8:]),
        "tool_ledger": deepcopy(_list_section(state, "tool_ledger")[-12:]),
    }


def _trace_input(
    *,
    request: DemoSalesTurnInput,
    session: DemoSalesSession,
    state_before: dict[str, Any],
    transcript_before: list[dict[str, Any]],
    current_turn: dict[str, Any],
    eval_tags: list[str],
) -> dict[str, Any]:
    return {
        "conversation_id": request.conversation_id,
        "channel": request.channel,
        "user_id": request.user_id,
        "text": request.text,
        "context": request.context,
        "eval_tags": eval_tags,
        "scenario_id": session.scenario_id,
        "scenario_version": session.scenario_version,
        "scenario_params": dict(session.scenario_params),
        "initial_state": deepcopy(session.initial_state),
        "state_before_turn": compact_sales_state(state_before),
        "transcript_before_turn": transcript_before,
        "transcript_current_turn": current_turn,
        "eval": {
            "source": "demo.sales",
            "trace_first_dataset_flow": True,
        },
    }


def _scenario_payload(session: DemoSalesSession) -> dict[str, Any]:
    return {
        "scenario_id": session.scenario_id,
        "scenario_version": session.scenario_version,
        "params": dict(session.scenario_params),
    }


def _dataset_item_from_turn(
    *,
    session: DemoSalesSession,
    turn_id: str,
    trace_input: dict[str, Any],
    trace_output: dict[str, Any],
    started_at: str,
) -> dict[str, Any]:
    return {
        "id": f"{session.conversation_id}:{turn_id}",
        "input": deepcopy(trace_input),
        "expected_output": None,
        "candidate_output": deepcopy(trace_output),
        "metadata": _dataset_metadata(
            session=session,
            source="demo_sales_jsonl_export",
            started_at=started_at,
            tool_ledger=trace_output.get("tool_calls", []),
            state_mutations=trace_output.get("state_mutations", []),
            transcript_after_turn=trace_output.get("transcript_after_turn", []),
        ),
    }


def _conversation_level_dataset_item(*, session: DemoSalesSession) -> dict[str, Any]:
    tool_ledger = _list_section(session.current_state, "tool_ledger")
    state_mutations = [
        mutation
        for call in tool_ledger
        for mutation in _as_list(call.get("mutations"))
    ]
    return {
        "id": f"{session.conversation_id}:conversation",
        "input": {
            "conversation_id": session.conversation_id,
            "channel": session.channel,
            "user_id": session.user_id,
            "scenario_id": session.scenario_id,
            "scenario_version": session.scenario_version,
            "scenario_params": dict(session.scenario_params),
            "initial_state": deepcopy(session.initial_state),
            "transcript": deepcopy(session.transcript),
            "eval_tags": list(session.eval_tags),
        },
        "expected_output": None,
        "candidate_output": {
            "state_after_conversation": compact_sales_state(session.current_state),
            "tool_calls": deepcopy(tool_ledger),
            "state_mutations": state_mutations,
            "transcript_after_conversation": deepcopy(session.transcript),
            "public_messages": deepcopy(_list_section(session.current_state, "public_messages")),
            "private_notes": deepcopy(_list_section(session.current_state, "notes")),
        },
        "metadata": _dataset_metadata(
            session=session,
            source="demo_sales_jsonl_export_conversation_fallback",
            started_at=session.created_at,
            tool_ledger=tool_ledger,
            state_mutations=state_mutations,
            transcript_after_turn=session.transcript,
        ),
    }


def _dataset_metadata(
    *,
    session: DemoSalesSession,
    source: str,
    started_at: str,
    tool_ledger: Any,
    state_mutations: Any,
    transcript_after_turn: Any,
) -> dict[str, Any]:
    return {
        "source": source,
        "exported_at": _utc_now(),
        "conversation_id": session.conversation_id,
        "scenario": _scenario_payload(session),
        "turn_started_at": started_at,
        "requires_expected_output_review": True,
        "tool_ledger": deepcopy(_as_list(tool_ledger)),
        "state_mutations": deepcopy(_as_list(state_mutations)),
        "transcript_after_turn": deepcopy(_as_list(transcript_after_turn)),
        "rubric": {
            "task_success": "The assistant advances or correctly blocks the sales task.",
            "grounded_in_tool_result": "State claims are grounded in sales mock tool output.",
            "missing_data_handled": "The assistant asks for missing qualification data.",
            "communication_quality": "WhatsApp reply is concise, commercial, and useful.",
            "needs_human_review": "Human handoff is requested for policy or pricing exceptions.",
        },
    }


def _with_manual_feedback(
    item: dict[str, Any],
    *,
    session: DemoSalesSession,
) -> dict[str, Any]:
    exported = deepcopy(item)
    metadata = exported.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["manual_feedback"] = deepcopy(session.manual_feedback)
        metadata["manual_feedback_tags"] = _unique_feedback_tags(session.manual_feedback)
    return exported


def _unique_feedback_tags(feedback_items: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    for feedback in feedback_items:
        for tag in _as_list(feedback.get("feedback_tags")):
            value = str(tag)
            if value and value not in tags:
                tags.append(value)
    return tags


def _validate_param_value(
    definitions: dict[str, DemoSalesParamDefinition],
    *,
    name: str,
    value: str,
) -> None:
    definition = definitions.get(name)
    if definition is None:
        raise DemoSalesValidationError(f"unknown scenario param: {name}")
    allowed_values = {option.value for option in definition.options}
    if value not in allowed_values:
        raise DemoSalesValidationError(f"invalid value for scenario param {name}: {value}")


def _apply_params_to_state(state: dict[str, Any], params: dict[str, str]) -> None:
    lead = _dict_section(state, "lead")
    payment = _dict_section(state, "payment")
    subscription = _dict_section(state, "subscription")
    activation = _dict_section(state, "activation")
    followup = _dict_section(state, "followup")

    _assign_if_present(lead, "control_state", params, "control_state")
    _assign_if_present(lead, "commercial_state", params, "commercial_state")
    _assign_if_present(lead, "contact_role", params, "contact_role")
    _assign_if_present(payment, "state", params, "payment_state")
    _assign_if_present(subscription, "state", params, "subscription_state")
    _assign_if_present(activation, "link_status", params, "activation_link_status")
    _assign_if_present(followup, "state", params, "followup_state")

    if activation.get("link_status") in {None, "missing", "expired"}:
        activation["activation_link"] = None
    elif activation.get("link_status") in {"available", "sent"} and activation.get("activation_link") is None:
        activation["activation_link"] = (
            f"https://demo.sumampa.test/activate/{lead.get('lead_id', 'lead')}"
        )
    if lead.get("commercial_state") == "opted_out":
        lead["opted_out"] = True
        lead["followup_disabled"] = True
        followup["state"] = "disabled"
        _append_list_value(lead, "tags", "opt-out")
    if followup.get("state") == "disabled":
        lead["followup_disabled"] = True
    if lead.get("control_state") == "human_review":
        lead["human_review_requested"] = True
        _append_list_value(lead, "tags", "human-review")
    if payment.get("state") == "paid":
        lead["commercial_state"] = "post_payment"


def _assign_if_present(
    target: dict[str, Any],
    target_key: str,
    params: dict[str, str],
    param_key: str,
) -> None:
    if param_key in params:
        target[target_key] = None if params[param_key] == "unset" else params[param_key]


def _dict_section(state: dict[str, Any], name: str) -> dict[str, Any]:
    value = state.setdefault(name, {})
    if not isinstance(value, dict):
        value = {}
        state[name] = value
    return value


def _list_section(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = state.setdefault(name, [])
    if not isinstance(value, list):
        value = []
        state[name] = value
    return value


def _set_value(
    target: dict[str, Any],
    key: str,
    value: Any,
    mutations: list[dict[str, Any]],
    path: str,
) -> None:
    before = deepcopy(target.get(key))
    if before == value:
        return
    target[key] = value
    mutations.append({"path": path, "before": before, "after": deepcopy(value)})


def _append_unique(
    target: dict[str, Any],
    key: str,
    values: list[str],
    mutations: list[dict[str, Any]],
    path: str,
) -> None:
    before = deepcopy(target.get(key, []))
    for value in values:
        _append_list_value(target, key, value)
    after = deepcopy(target.get(key, []))
    if before != after:
        mutations.append({"path": path, "before": before, "after": after})


def _append_list_value(target: dict[str, Any], key: str, value: str) -> None:
    items = target.setdefault(key, [])
    if not isinstance(items, list):
        items = []
        target[key] = items
    if value and value not in items:
        items.append(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    normalized: list[str] = []
    for raw_value in raw_values:
        item = str(raw_value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
