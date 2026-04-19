"""Dynamic API router registry."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module

from fastapi import APIRouter

ROUTE_MODULES: dict[str, str] = {
    "core": "sumampa_odoo_agent.adapters.api.routes.core",
    "agent": "sumampa_odoo_agent.adapters.api.routes.agent",
    "odoo": "sumampa_odoo_agent.adapters.api.routes.odoo",
}


def load_routers(enabled_modules: Iterable[str]) -> list[APIRouter]:
    """Load routers only for enabled modules."""
    routers: list[APIRouter] = []
    for module_name in sorted(set(enabled_modules)):
        module_path = ROUTE_MODULES.get(module_name)
        if module_path is None:
            continue
        module = import_module(module_path)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers


__all__ = ["load_routers"]
