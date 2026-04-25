"""FastAPI app factory for the simplified WhatsApp-oriented backend."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from sumampa_odoo_agent.api.error_handler import register_exception_handlers
from sumampa_odoo_agent.api.routes import (
    core_router,
    messages_router,
)
from sumampa_odoo_agent.config import AppSettings, load_settings, resolve_environment
from sumampa_odoo_agent.integrations.telemetry import bootstrap_telemetry, instrument_fastapi_app
from sumampa_odoo_agent.services import build_app_services
from sumampa_odoo_agent.services.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize app services on startup and close them on shutdown."""

    settings: AppSettings = app.state.settings
    telemetry_runtime = app.state.telemetry_runtime
    services = await build_app_services(
        settings,
        telemetry_observability=telemetry_runtime.observability,
        metrics=telemetry_runtime.metrics,
    )
    app.state.services = services
    yield
    await services.aclose()
    await telemetry_runtime.aclose()


def create_app(*, settings: AppSettings | None = None, env: str | None = None) -> FastAPI:
    """Create configured FastAPI application."""

    resolved_settings = settings or load_settings(env=resolve_environment(env))
    configure_logging(resolved_settings)
    telemetry_runtime = bootstrap_telemetry(resolved_settings)

    app = FastAPI(
        title=resolved_settings.service.name,
        version=resolved_settings.service.version,
        description="WhatsApp-oriented Odoo bot backend",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.telemetry_runtime = telemetry_runtime

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
    _add_http_metrics_middleware(app)
    instrument_fastapi_app(app, resolved_settings)
    return app

def _add_http_metrics_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def record_http_metrics(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        timer = request.app.state.telemetry_runtime.metrics.start_timer()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            request.app.state.telemetry_runtime.metrics.record_http_request(
                method=request.method,
                route=_route_label(request),
                status=status_code,
                duration_seconds=timer(),
            )


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    return "unmatched"


app = create_app()
