"""Core routes."""

from __future__ import annotations

from fastapi import APIRouter

from sumampa_odoo_agent.api.dependencies import ServicesDep

router = APIRouter(tags=["core"])


@router.get("/health")
async def health(services: ServicesDep) -> dict[str, object]:
    return {
        "status": "ok",
        "service": services.settings.service.name,
        "version": services.settings.service.version,
    }
