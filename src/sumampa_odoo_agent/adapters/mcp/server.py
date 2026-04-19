"""MCP server with dynamic tool registration per enabled module."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from sumampa_odoo_agent.adapters.mcp.errors import MCPToolError
from sumampa_odoo_agent.adapters.mcp.tools import load_tool_specs
from sumampa_odoo_agent.infrastructure.runtime import (
    get_runtime_container,
    get_runtime_state,
    shutdown_runtime,
    startup_runtime,
)


def _unknown_tool_payload(name: str) -> dict[str, Any]:
    return {
        "error": {
            "code": "unknown_tool",
            "message": f"Unknown tool: {name}",
            "details": {"tool": name},
        }
    }


def create_mcp_server() -> Server:
    """Create MCP server using runtime enabled modules."""
    state = get_runtime_state()
    tool_specs = load_tool_specs(state.enabled_modules)
    tool_map = {spec.name: spec for spec in tool_specs}

    server = Server(state.settings.service.name)
    server_any: Any = server

    @server_any.list_tools()  # type: ignore[untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
            )
            for tool in tool_specs
        ]

    @server_any.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        container = get_runtime_container()
        tool = tool_map.get(name)
        if tool is None:
            payload = _unknown_tool_payload(name)
            return [TextContent(type="text", text=json.dumps(payload))]

        try:
            result = await tool.handler(container, arguments)
        except MCPToolError as exc:
            result = exc.to_payload()
        except Exception as exc:
            result = {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                    "details": {"tool": name, "exception_type": exc.__class__.__name__},
                }
            }

        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def run_mcp_server() -> None:
    """Run MCP stdio server with runtime lifecycle management."""
    await startup_runtime()
    server = create_mcp_server()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await shutdown_runtime()
