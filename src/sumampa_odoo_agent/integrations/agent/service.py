"""Agent backends built around Microsoft Agent Framework."""

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
from sumampa_odoo_agent.integrations.agent.prompts import DEFAULT_AGENT_SYSTEM_PROMPT
from sumampa_odoo_agent.services.contracts import OdooGateway, SessionStore
from sumampa_odoo_agent.services.errors import (
    ConfigurationError,
    UpstreamServiceError,
)
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.tools import build_agent_tools

AGENT_SESSION_NAMESPACE = "agent"
AGENT_MODULE_DISABLED_MESSAGE = (
    "El módulo agent está deshabilitado. Configurá ORCHID_AGENT_MODE=openai para usarlo."
)


class DisabledAgentService:
    """Explicit runtime disabled state for the agent module."""

    async def run(self, request: AgentRunInput) -> AgentRunResult:
        del request
        raise ConfigurationError(
            AGENT_MODULE_DISABLED_MESSAGE,
            code="agent_module_disabled",
        )


class MicrosoftAgentFrameworkOpenAIService:
    """Thin wrapper around Microsoft Agent Framework OpenAI chat client."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str | None = None,
        api_key_env_var: str,
        odoo: OdooGateway | None = None,
        base_url: str | None = None,
        session_store: SessionStore,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt or DEFAULT_AGENT_SYSTEM_PROMPT
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._odoo = odoo
        self._session_store = session_store

    async def run(self, request: AgentRunInput) -> AgentRunResult:
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

        agent: Any = _create_compatible_agent(
            chat_client=chat_client,
            agent_type=Agent,
            name="Sumampa Odoo Agent",
            instructions=self._system_prompt,
            tools=build_agent_tools(odoo=self._odoo),
            max_function_calls=16,
        )
        if not isinstance(agent, Agent):
            raise UpstreamServiceError(
                AGENT_UPSTREAM_FAILURE_MESSAGE,
                code="agent_creation_failed",
                details={"provider": "openai", "model": self._model},
            )

        session = await self._load_or_create_session(agent=agent, session_id=resolved_session_id)
        message = _build_agent_message(
            prompt=request.prompt,
            context=request.context.to_agent_context(),
        )
        try:
            response = await agent.run(message, session=session)
        except Exception as exc:
            translated_error = _translate_agent_run_error(exc, model=self._model)
            if translated_error is not None:
                raise translated_error from exc
            raise

        await self._session_store.save(
            namespace=AGENT_SESSION_NAMESPACE,
            session_id=session.session_id,
            payload=session.to_dict(),
        )
        return AgentRunResult(
            mode="microsoft-agent-framework-openai",
            session_id=resolved_session_id,
            text=str(getattr(response, "text", str(response))),
        )

    async def _load_or_create_session(
        self,
        *,
        agent: Any,
        session_id: str,
    ) -> Any:
        AgentSession = _load_agent_session_type()
        payload = await self._session_store.load(
            namespace=AGENT_SESSION_NAMESPACE,
            session_id=session_id,
        )
        if payload is not None:
            return AgentSession.from_dict(payload)
        return agent.create_session(session_id=session_id)
