"""FastAPI exception handlers for consistent API error responses."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sumampa_odoo_agent.application.errors import ApplicationError
from sumampa_odoo_agent.application.message_specs import render_message

logger = logging.getLogger(__name__)


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for API responses."""

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("Application error: %s", exc.message)
        else:
            logger.warning("Application error: %s", exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        payload: dict[str, Any] = {
            "error": "ValidationError",
            "message": render_message("runtime.json", "request_validation_failed"),
            "code": "validation_error",
            "details": {"errors": _validation_details(exc)},
        }
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            payload = detail
        else:
            payload = {
                "error": "HTTPException",
                "message": str(detail),
                "code": "http_error",
            }
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        detail = exc.detail
        payload = {
            "error": "HTTPException",
            "message": str(detail),
            "code": "http_error",
        }
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception")
        payload = {
            "error": "InternalServerError",
            "message": render_message("runtime.json", "unexpected_error"),
            "code": "internal_error",
            "details": {"exception_type": exc.__class__.__name__},
        }
        return JSONResponse(status_code=500, content=payload)
