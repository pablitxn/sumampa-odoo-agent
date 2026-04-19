"""Application request buses (command/query) in romy-style layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

RequestT = TypeVar("RequestT", bound=BaseModel, contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class Handler(Protocol[RequestT, ResultT]):
    """Generic request handler contract."""

    async def handle(self, request: RequestT) -> ResultT:
        """Handle a validated request model."""


class HandlerNotRegisteredError(LookupError):
    """Raised when dispatching a request without a registered handler."""

    def __init__(self, request_type: type[BaseModel]) -> None:
        super().__init__(f"No handler registered for request type: {request_type.__name__}")
        self.request_type = request_type


@dataclass(slots=True)
class _Bus:
    _handlers: dict[type[BaseModel], Handler[Any, Any]] = field(default_factory=dict)

    def register(self, request_type: type[BaseModel], handler: Handler[Any, Any]) -> None:
        self._handlers[request_type] = handler

    def has_handler(self, request_type: type[BaseModel]) -> bool:
        return request_type in self._handlers

    async def dispatch(self, request: BaseModel) -> Any:
        handler = self._handlers.get(type(request))
        if handler is None:
            raise HandlerNotRegisteredError(type(request))
        return await handler.handle(request)


class CommandBus(_Bus):
    """Dispatcher for command requests (state-changing)."""


class QueryBus(_Bus):
    """Dispatcher for query requests (read-only)."""
