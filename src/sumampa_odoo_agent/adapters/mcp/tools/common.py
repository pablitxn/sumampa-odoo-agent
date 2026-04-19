"""Shared MCP tool specification model."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sumampa_odoo_agent.infrastructure.runtime.container import ApplicationContainer

ToolHandler = Callable[[ApplicationContainer, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Defines a tool exposed by MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
