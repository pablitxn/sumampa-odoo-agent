"""Core routes always available regardless of enabled business modules."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from sumampa_odoo_agent.adapters.dependencies import ContainerDep

router = APIRouter(tags=["core"])
DEMO_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "purchase_invoice_demo.html"
DEMO_COPY_JS_PATH = Path(__file__).resolve().parent.parent / "static" / "purchase_invoice_demo_copy.js"


@router.get("/health")
async def health(container: ContainerDep) -> dict[str, object]:
    return {
        "status": "ok",
        "service": container.settings.service.name,
        "version": container.settings.service.version,
        "enabled_modules": sorted(container.enabled_modules),
    }


@router.get("/api/v1/capabilities")
async def capabilities(container: ContainerDep) -> dict[str, object]:
    return {
        "service": container.settings.service.name,
        "modules": [
            {
                "name": name,
                "description": module.description,
                "enabled": name in container.enabled_modules,
            }
            for name, module in sorted(container.module_manifest.items())
        ],
    }


@router.get("/demo/purchase-invoices")
async def purchase_invoice_demo() -> FileResponse:
    return FileResponse(DEMO_HTML_PATH)


@router.get("/demo/purchase-invoices-copy.js")
async def purchase_invoice_demo_copy() -> FileResponse:
    return FileResponse(DEMO_COPY_JS_PATH, media_type="text/javascript")
