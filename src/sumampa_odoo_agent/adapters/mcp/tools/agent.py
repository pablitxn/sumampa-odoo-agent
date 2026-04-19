"""MCP tools for agent execution."""

from __future__ import annotations

from sumampa_odoo_agent.adapters.mcp.tools.common import ToolSpec
from sumampa_odoo_agent.application.requests.agent import RunAgentCommand


async def _run_agent(container, arguments: dict[str, object]) -> dict[str, object]:
    command = RunAgentCommand.model_validate(arguments)
    result = await container.command_bus.dispatch(command)
    return {"result": result}


def get_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="agent_run",
            description="Run the Sumampa Odoo assistant for planning or operator guidance.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "context": {"type": "object"},
                },
                "required": ["prompt"],
            },
            handler=_run_agent,
        )
    ]
