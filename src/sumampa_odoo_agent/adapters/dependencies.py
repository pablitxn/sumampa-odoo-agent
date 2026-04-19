"""Adapter-level dependency functions shared by API and MCP."""

from typing import Annotated

from fastapi import Depends

from sumampa_odoo_agent.infrastructure.runtime import (
    ApplicationContainer,
    get_runtime_container,
    shutdown_runtime,
    startup_runtime,
)


def get_container() -> ApplicationContainer:
    """Return active application container."""
    return get_runtime_container()


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]


async def init_services() -> None:
    """Initialize runtime resources."""
    await startup_runtime()


async def shutdown_services() -> None:
    """Shutdown runtime resources."""
    await shutdown_runtime()
