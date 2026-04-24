"""Service layer exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sumampa_odoo_agent.services.app import AppServices, build_app_services
    from sumampa_odoo_agent.services.conversation import (
        ConversationService,
        ConversationTurnInput,
        ConversationTurnResult,
    )

__all__ = [
    "AppServices",
    "ConversationService",
    "ConversationTurnInput",
    "ConversationTurnResult",
    "build_app_services",
]

_EXPORTS = {
    "AppServices": ("sumampa_odoo_agent.services.app", "AppServices"),
    "build_app_services": ("sumampa_odoo_agent.services.app", "build_app_services"),
    "ConversationService": (
        "sumampa_odoo_agent.services.conversation",
        "ConversationService",
    ),
    "ConversationTurnInput": (
        "sumampa_odoo_agent.services.conversation",
        "ConversationTurnInput",
    ),
    "ConversationTurnResult": (
        "sumampa_odoo_agent.services.conversation",
        "ConversationTurnResult",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_name)
    return getattr(module, attr_name)
