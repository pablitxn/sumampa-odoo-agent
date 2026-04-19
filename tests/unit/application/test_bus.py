"""Unit tests for application request buses."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from sumampa_odoo_agent.application.bus import CommandBus, HandlerNotRegisteredError, QueryBus


class _EchoCommand(BaseModel):
    value: str


class _EchoQuery(BaseModel):
    value: str


class _EchoHandler:
    async def handle(self, request: BaseModel) -> str:
        return request.model_dump()["value"]


@pytest.mark.asyncio
async def test_command_bus_dispatches_registered_handler() -> None:
    bus = CommandBus()
    bus.register(_EchoCommand, _EchoHandler())

    result = await bus.dispatch(_EchoCommand(value="ok"))

    assert result == "ok"


@pytest.mark.asyncio
async def test_query_bus_raises_for_unregistered_request() -> None:
    bus = QueryBus()

    with pytest.raises(HandlerNotRegisteredError):
        await bus.dispatch(_EchoQuery(value="missing"))
