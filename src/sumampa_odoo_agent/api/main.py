"""FastAPI app factory for the simplified WhatsApp-oriented backend."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sumampa_odoo_agent.api.error_handler import register_exception_handlers
from sumampa_odoo_agent.api.routes import (
    core_router,
    messages_router,
    odoo_router,
    purchase_invoices_router,
)
from sumampa_odoo_agent.config import AppSettings, load_settings, resolve_environment
from sumampa_odoo_agent.services import build_app_services


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize app services on startup and close them on shutdown."""

    settings: AppSettings = app.state.settings
    services = await build_app_services(settings)
    app.state.services = services
    yield
    await services.aclose()


def create_app(*, settings: AppSettings | None = None, env: str | None = None) -> FastAPI:
    """Create configured FastAPI application."""

    resolved_settings = settings or load_settings(env=resolve_environment(env))

    app = FastAPI(
        title=resolved_settings.service.name,
        version=resolved_settings.service.version,
        description="WhatsApp-oriented Odoo bot backend",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(core_router)
    app.include_router(messages_router)
    app.include_router(purchase_invoices_router)
    app.include_router(odoo_router)
    return app


app = create_app()
