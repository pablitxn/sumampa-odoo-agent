"""API routes for agent execution."""

from __future__ import annotations

from fastapi import APIRouter

from sumampa_odoo_agent.adapters.dependencies import ContainerDep
from sumampa_odoo_agent.application.requests.agent import RunAgentCommand

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("/runs")
async def run_agent(command: RunAgentCommand, container: ContainerDep) -> dict[str, object]:
    return await container.command_bus.dispatch(command)
