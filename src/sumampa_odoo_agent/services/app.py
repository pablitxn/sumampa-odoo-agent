"""Bootstrap helpers for the service layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent import build_agent_runtime
from sumampa_odoo_agent.integrations.observability import (
    ObservedOdooGateway,
    build_observability_provider,
)
from sumampa_odoo_agent.integrations.odoo import build_odoo_gateway
from sumampa_odoo_agent.integrations.sessions import build_session_store
from sumampa_odoo_agent.integrations.storage import build_attachment_store
from sumampa_odoo_agent.services.attachments import AttachmentIngestionService
from sumampa_odoo_agent.services.conversation import ConversationService
from sumampa_odoo_agent.services.metrics import AppMetrics
from sumampa_odoo_agent.services.observability import (
    CompositeObservabilityProvider,
    NoOpObservabilityProvider,
    ObservabilityProvider,
)


@dataclass(slots=True)
class AppServices:
    """All app-facing services assembled for one FastAPI instance."""

    settings: AppSettings
    conversation: ConversationService
    closers: tuple[Callable[[], Awaitable[None]], ...] = ()

    async def aclose(self) -> None:
        for closer in reversed(self.closers):
            await closer()


async def build_app_services(
    settings: AppSettings,
    *,
    telemetry_observability: ObservabilityProvider | None = None,
    metrics: AppMetrics | None = None,
) -> AppServices:
    """Build the explicit service graph from runtime integrations."""

    semantic_observability = build_observability_provider(settings)
    observability = CompositeObservabilityProvider(
        [
            semantic_observability,
            telemetry_observability or NoOpObservabilityProvider(),
        ]
    )
    app_metrics = metrics or AppMetrics.disabled(settings)
    session_store = await build_session_store(settings)
    attachment_store = await build_attachment_store(settings)
    odoo_gateway = ObservedOdooGateway(
        wrapped=build_odoo_gateway(settings),
        observability=observability,
        mode=settings.odoo.mode,
        metrics=app_metrics,
    )
    agent_runtime = build_agent_runtime(
        settings,
        odoo_gateway,
        session_store,
        observability,
    )
    attachment_ingestion = AttachmentIngestionService(
        object_store=attachment_store,
        settings=settings.attachments,
    )

    conversation = ConversationService(
        agent_runtime,
        attachment_ingestion=attachment_ingestion,
        observability=observability,
        metrics=app_metrics,
        trace_metadata={
            "service.name": settings.service.name,
            "service.version": settings.service.version,
            "agent.mode": settings.agent.mode,
            "agent.model": settings.agent.model,
            "odoo.mode": settings.odoo.mode,
        },
    )
    return AppServices(
        settings=settings,
        conversation=conversation,
        closers=(
            observability.aclose,
            session_store.aclose,
            attachment_store.aclose,
            odoo_gateway.aclose,
        ),
    )
