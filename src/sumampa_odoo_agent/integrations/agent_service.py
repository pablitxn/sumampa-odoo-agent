"""Agent backends built around Microsoft Agent Framework."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from importlib.metadata import version as package_version
from typing import Any, cast
from uuid import uuid4

from openai import RateLimitError

from sumampa_odoo_agent.integrations.llm_specs import load_llm_spec
from sumampa_odoo_agent.services.contracts import OdooGateway, SessionStore
from sumampa_odoo_agent.services.errors import (
    ConfigurationError,
    TooManyRequestsError,
    UpstreamServiceError,
)
from sumampa_odoo_agent.services.models.runtime import AgentRunInput, AgentRunResult
from sumampa_odoo_agent.tools import build_agent_tools

AGENT_SESSION_NAMESPACE = "agent"
AGENT_MODULE_DISABLED_MESSAGE = (
    "El módulo agent está deshabilitado. Configurá ORCHID_AGENT_MODE=openai para usarlo."
)
AGENT_RATE_LIMITED_MESSAGE = "El modelo esta temporalmente saturado. Reintenta en unos segundos."
AGENT_UPSTREAM_FAILURE_MESSAGE = "El servicio del agente no pudo completar la solicitud."
_RATE_LIMIT_RETRY_AFTER_PATTERN = re.compile(
    r"Please try again in (?P<seconds>\d+(?:\.\d+)?)s",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


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
        system_prompt_spec: str = "agent/system.md",
        api_key_env_var: str,
        odoo: OdooGateway | None = None,
        base_url: str | None = None,
        session_store: SessionStore,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt or load_llm_spec(system_prompt_spec)
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


def _load_openai_chat_client() -> type[Any]:
    """Work around current upstream packaging bug around `agent_framework.__version__`."""
    import agent_framework

    _ensure_agent_framework_version(agent_framework)

    from agent_framework.openai import OpenAIChatClient

    return OpenAIChatClient


def _load_agent_type() -> type[Any]:
    from agent_framework._agents import Agent

    return Agent


def _load_agent_session_type() -> type[Any]:
    import agent_framework

    _ensure_agent_framework_version(agent_framework)

    from agent_framework._sessions import AgentSession

    if getattr(agent_framework, "AgentSession", None) is None:
        cast(Any, agent_framework).AgentSession = AgentSession

    return AgentSession


def _ensure_agent_framework_version(agent_framework: Any) -> None:
    if getattr(agent_framework, "__version__", None) is None:
        agent_framework.__version__ = package_version("agent-framework")


def _create_compatible_agent(
    *,
    chat_client: Any,
    agent_type: type[Any],
    name: str,
    instructions: str,
    tools: list[Any],
    max_function_calls: int,
) -> Any:
    kwargs: dict[str, Any] = {
        "name": name,
        "instructions": instructions,
        "tools": tools,
    }
    if _chat_client_accepts_function_invocation_configuration(chat_client):
        if _agent_accepts_function_invocation_configuration(agent_type):
            kwargs["function_invocation_configuration"] = {
                "max_function_calls": max_function_calls,
            }
        else:
            kwargs["function_invocation_configuration"] = None
    return chat_client.as_agent(**kwargs)


def _agent_accepts_function_invocation_configuration(agent_type: type[Any]) -> bool:
    try:
        parameters = inspect.signature(agent_type.__init__).parameters
    except (TypeError, ValueError):
        return False
    return "function_invocation_configuration" in parameters


def _chat_client_accepts_function_invocation_configuration(chat_client: Any) -> bool:
    try:
        parameters = inspect.signature(chat_client.as_agent).parameters
    except (TypeError, ValueError):
        return False
    return "function_invocation_configuration" in parameters


def _build_agent_message(
    *,
    prompt: str,
    context: dict[str, Any],
) -> str:
    if not context:
        return prompt
    return (
        f"{prompt}\n\n"
        "Contexto JSON:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )


def _translate_agent_run_error(
    exc: Exception,
    *,
    model: str,
) -> TooManyRequestsError | UpstreamServiceError | None:
    rate_limit_error = _find_openai_rate_limit_error(exc)
    if rate_limit_error is not None:
        retry_after_seconds = _extract_retry_after_seconds(rate_limit_error)
        details: dict[str, object] = {
            "provider": "openai",
            "model": model,
        }
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        return TooManyRequestsError(
            AGENT_RATE_LIMITED_MESSAGE,
            code="agent_rate_limited",
            details=details,
        )

    if any(_is_chat_client_exception(error) for error in _exception_chain(exc)):
        return UpstreamServiceError(
            AGENT_UPSTREAM_FAILURE_MESSAGE,
            code="agent_upstream_failure",
            details={
                "provider": "openai",
                "model": model,
                "exception_type": exc.__class__.__name__,
            },
        )

    return None


def _is_chat_client_exception(error: BaseException) -> bool:
    try:
        from agent_framework.exceptions import ChatClientException
    except ModuleNotFoundError:  # pragma: no cover
        return error.__class__.__name__ == "ChatClientException"
    return isinstance(error, ChatClientException)


def _find_openai_rate_limit_error(exc: Exception) -> RateLimitError | None:
    for error in _exception_chain(exc):
        if isinstance(error, RateLimitError):
            return error
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    errors: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        errors.append(current)
        current = current.__cause__ or current.__context__
    return errors


def _extract_retry_after_seconds(rate_limit_error: RateLimitError) -> float | None:
    retry_after = getattr(getattr(rate_limit_error, "response", None), "headers", {}).get(
        "retry-after"
    )
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            logger.debug("Ignoring non-numeric retry-after header: %s", retry_after)

    match = _RATE_LIMIT_RETRY_AFTER_PATTERN.search(str(rate_limit_error))
    if match is None:
        return None
    return float(match.group("seconds"))
