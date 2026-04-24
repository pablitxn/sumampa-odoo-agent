"""Bootstrap helpers for the service layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent_runtime import build_agent_runtime
from sumampa_odoo_agent.integrations.odoo import build_odoo_gateway
from sumampa_odoo_agent.integrations.session_store import build_session_store
from sumampa_odoo_agent.services.conversation import ConversationService


@dataclass(slots=True)
class AppServices:
    """All app-facing services assembled for one FastAPI instance."""

    settings: AppSettings
    conversation: ConversationService
    closers: tuple[Callable[[], Awaitable[None]], ...] = ()

    async def aclose(self) -> None:
        for closer in reversed(self.closers):
            await closer()


async def build_app_services(settings: AppSettings) -> AppServices:
    """Build the explicit service graph from runtime integrations."""

    session_store = await build_session_store(settings)
    odoo_gateway = build_odoo_gateway(settings)
    agent_runtime = build_agent_runtime(settings, odoo_gateway, session_store)

    conversation = ConversationService(agent_runtime)
    return AppServices(
        settings=settings,
        conversation=conversation,
        closers=(session_store.aclose, odoo_gateway.aclose),
    )
