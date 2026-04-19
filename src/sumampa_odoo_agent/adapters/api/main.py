"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sumampa_odoo_agent.adapters.api.error_handler import register_exception_handlers
from sumampa_odoo_agent.adapters.api.routes import load_routers
from sumampa_odoo_agent.adapters.dependencies import init_services, shutdown_services
from sumampa_odoo_agent.infrastructure.runtime.modules import (
    load_enabled_modules,
    load_module_manifest,
    resolve_enabled_modules,
)
from sumampa_odoo_agent.infrastructure.runtime.settings import load_settings
from sumampa_odoo_agent.infrastructure.runtime.state import resolve_environment


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize runtime resources on startup and close them on shutdown."""
    await init_services()
    yield
    await shutdown_services()


def create_app() -> FastAPI:
    """Create configured FastAPI application."""
    environment = resolve_environment()
    settings = load_settings(config_dir=Path("config"), env=environment)

    app = FastAPI(
        title=settings.service.name,
        version=settings.service.version,
        description="FastAPI + MCP scaffold for Odoo operator flows with strict hexagonal boundaries",
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    manifest = load_module_manifest()
    enabled_modules = resolve_enabled_modules(load_enabled_modules(), manifest)
    for router in load_routers(enabled_modules):
        app.include_router(router)

    return app


app = create_app()
