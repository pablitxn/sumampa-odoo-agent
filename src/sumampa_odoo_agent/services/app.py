"""Bootstrap helpers for the service layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.agent_runtime import build_agent_runtime
from sumampa_odoo_agent.integrations.extraction import build_invoice_extractor
from sumampa_odoo_agent.integrations.odoo import build_odoo_gateway
from sumampa_odoo_agent.integrations.session_store import build_session_store
from sumampa_odoo_agent.services.conversation import ConversationService
from sumampa_odoo_agent.services.odoo import OdooService
from sumampa_odoo_agent.services.purchase_invoices import PurchaseInvoiceService


@dataclass(slots=True)
class AppServices:
    """All app-facing services assembled for one FastAPI instance."""

    settings: AppSettings
    odoo: OdooService
    purchase_invoices: PurchaseInvoiceService
    conversation: ConversationService
    closers: tuple[Callable[[], Awaitable[None]], ...] = ()

    async def aclose(self) -> None:
        for closer in reversed(self.closers):
            await closer()


async def build_app_services(settings: AppSettings) -> AppServices:
    """Build the explicit service graph from runtime integrations."""

    session_store = await build_session_store(settings)
    invoice_extractor = build_invoice_extractor(settings)
    odoo_gateway = build_odoo_gateway(settings, invoice_extractor)
    agent_runtime = build_agent_runtime(settings, odoo_gateway, session_store)

    odoo = OdooService(odoo_gateway)
    purchase_invoices = PurchaseInvoiceService(odoo)
    conversation = ConversationService(agent_runtime)
    return AppServices(
        settings=settings,
        odoo=odoo,
        purchase_invoices=purchase_invoices,
        conversation=conversation,
        closers=(session_store.aclose,),
    )
