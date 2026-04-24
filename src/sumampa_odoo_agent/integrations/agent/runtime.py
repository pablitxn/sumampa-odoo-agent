"""Agent runtime builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent.service import (
    DisabledAgentService,
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.services.contracts import AgentRuntime, OdooGateway, SessionStore
from sumampa_odoo_agent.services.errors import ConfigurationError


def build_agent_runtime(
    settings: AppSettings,
    odoo_gateway: OdooGateway,
    session_store: SessionStore,
) -> AgentRuntime:
    """Build the configured agent runtime."""

    if settings.agent.mode == "openai":
        return MicrosoftAgentFrameworkOpenAIService(
            model=settings.agent.model,
            system_prompt=settings.agent.system_prompt_override,
            system_prompt_spec=settings.agent.system_prompt_spec,
            api_key_env_var=settings.agent.api_key_env_var,
            odoo=odoo_gateway,
            base_url=settings.agent.base_url,
            session_store=session_store,
        )
    if settings.agent.mode == "disabled":
        return DisabledAgentService()
    raise ConfigurationError(
        f"Unsupported agent.mode: {settings.agent.mode}",
        code="unsupported_agent_mode",
    )
