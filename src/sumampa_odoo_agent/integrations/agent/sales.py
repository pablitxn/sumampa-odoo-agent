"""Sales demo agent runtime built on Microsoft Agent Framework."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from sumampa_odoo_agent.integrations.agent.errors import (
    AGENT_UPSTREAM_FAILURE_MESSAGE,
    _translate_agent_run_error,
)
from sumampa_odoo_agent.integrations.agent.framework import (
    _create_compatible_agent,
    _load_agent_session_type,
    _load_agent_type,
    _load_openai_chat_client,
)
from sumampa_odoo_agent.integrations.agent.messages import _build_agent_message
from sumampa_odoo_agent.integrations.agent.prompts import DEFAULT_SALES_AGENT_SYSTEM_PROMPT
from sumampa_odoo_agent.services.contracts import SalesBridgePort, SessionStore
from sumampa_odoo_agent.services.errors import ConfigurationError, UpstreamServiceError
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.services.observability import (
    NoOpObservabilityProvider,
    ObservabilityProvider,
    to_observability_payload,
)
from sumampa_odoo_agent.services.session_state import (
    AGENT_SESSION_NAMESPACE,
    normalize_eval_tags,
    with_merged_eval_tags,
)
from sumampa_odoo_agent.tools.sales import build_sales_agent_tools


class MicrosoftSalesDemoAgentRuntime:
    """Run the real LLM agent against in-process sales mock tools."""

    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str,
        session_store: SessionStore,
        observability: ObservabilityProvider | None = None,
        system_prompt: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var
        self._session_store = session_store
        self._observability = observability or NoOpObservabilityProvider()
        self._system_prompt = system_prompt or DEFAULT_SALES_AGENT_SYSTEM_PROMPT
        self._base_url = base_url

    async def run(
        self,
        request: AgentRunInput,
        *,
        bridge: SalesBridgePort,
    ) -> AgentRunResult:
        OpenAIChatClient = _load_openai_chat_client()
        Agent = _load_agent_type()

        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise ConfigurationError(
                f"Missing API key in environment variable '{self._api_key_env_var}'",
                code="agent_api_key_missing",
                details={"env_var": self._api_key_env_var},
            )

        chat_client = OpenAIChatClient(model=self._model, api_key=api_key, base_url=self._base_url)
        resolved_session_id = request.session_id or str(uuid4())
        eval_tags = normalize_eval_tags(request.eval_tags)
        agent: Any = _create_compatible_agent(
            chat_client=chat_client,
            agent_type=Agent,
            name="Sumampa Sales Demo Agent",
            instructions=self._system_prompt,
            tools=build_sales_agent_tools(bridge),
            max_function_calls=20,
        )
        if not isinstance(agent, Agent):
            raise UpstreamServiceError(
                AGENT_UPSTREAM_FAILURE_MESSAGE,
                code="agent_creation_failed",
                details={"provider": "openai", "model": self._model, "agent": "sales-demo"},
            )

        session = await self._load_or_create_session(agent=agent, session_id=resolved_session_id)
        message = _build_agent_message(
            prompt=request.prompt,
            context=request.context.to_agent_context(),
            attachments=request.attachments,
        )
        with self._observability.start_observation(
            name="sales.agent.run",
            as_type="agent",
            input={
                "prompt": request.prompt,
                "context": request.context.to_agent_context(),
                "session_id": resolved_session_id,
                "eval_tags": eval_tags,
            },
            metadata={
                "provider": "openai",
                "agent.provider": "microsoft-agent-framework-openai",
                "agent.kind": "sales-demo",
                "agent.model": self._model,
                "eval.tags": eval_tags,
                "evalTags": ",".join(eval_tags) if eval_tags else None,
            },
            model=self._model,
        ) as observation:
            try:
                response = await agent.run(message, session=session)
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                )
                translated_error = _translate_agent_run_error(exc, model=self._model)
                if translated_error is not None:
                    raise translated_error from exc
                raise

            response_text = str(getattr(response, "text", str(response)))
            observation.update(output={"text": response_text}, model=self._model)

        session_payload = with_merged_eval_tags(session.to_dict(), eval_tags)
        with self._observability.start_observation(
            name="sales.agent.session.save",
            as_type="span",
            input={
                "namespace": AGENT_SESSION_NAMESPACE,
                "session_id": session.session_id,
                "payload": to_observability_payload(session_payload),
            },
            metadata={"store.namespace": AGENT_SESSION_NAMESPACE, "agent.kind": "sales-demo"},
        ) as observation:
            try:
                await self._session_store.save(
                    namespace=AGENT_SESSION_NAMESPACE,
                    session_id=session.session_id,
                    payload=session_payload,
                )
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                )
                raise
            observation.update(output={"saved": True})

        return AgentRunResult(
            mode="microsoft-agent-framework-openai-sales-demo",
            session_id=resolved_session_id,
            text=response_text,
        )

    async def _load_or_create_session(self, *, agent: Any, session_id: str) -> Any:
        AgentSession = _load_agent_session_type()
        with self._observability.start_observation(
            name="sales.agent.session.load",
            as_type="span",
            input={"namespace": AGENT_SESSION_NAMESPACE, "session_id": session_id},
            metadata={"store.namespace": AGENT_SESSION_NAMESPACE, "agent.kind": "sales-demo"},
        ) as observation:
            try:
                payload = await self._session_store.load(
                    namespace=AGENT_SESSION_NAMESPACE,
                    session_id=session_id,
                )
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=f"{exc.__class__.__name__}: {exc}",
                )
                raise
            observation.update(
                output={
                    "found": payload is not None,
                    "payload": to_observability_payload(payload),
                }
            )
        if payload is not None:
            return AgentSession.from_dict(payload)
        return agent.create_session(session_id=session_id)
