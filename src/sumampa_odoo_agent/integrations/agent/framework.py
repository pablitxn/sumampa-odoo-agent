"""Compatibility helpers for Microsoft Agent Framework."""

from __future__ import annotations

import inspect
from importlib.metadata import version as package_version
from typing import Any, cast


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
