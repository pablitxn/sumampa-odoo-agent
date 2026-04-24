"""API route exports."""

from sumampa_odoo_agent.api.routes.core import router as core_router
from sumampa_odoo_agent.api.routes.messages import router as messages_router

__all__ = [
    "core_router",
    "messages_router",
]
