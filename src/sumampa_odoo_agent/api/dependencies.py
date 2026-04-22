"""FastAPI dependencies for app services."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from sumampa_odoo_agent.services import AppServices


def get_services(request: Request) -> AppServices:
    """Return the app-scoped service graph."""

    return cast(AppServices, request.app.state.services)


ServicesDep = Annotated[AppServices, Depends(get_services)]
