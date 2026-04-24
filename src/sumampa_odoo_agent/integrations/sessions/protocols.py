"""Internal contracts for session persistence adapters."""

from __future__ import annotations

from typing import Any, Protocol


class SessionCache(Protocol):
    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        """Load one cached session payload."""

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        """Cache one session payload."""

    async def delete(self, *, namespace: str, session_id: str) -> None:
        """Delete one cached session payload."""

    async def aclose(self) -> None:
        """Release cache resources."""


class DurableSessionStore(SessionCache, Protocol):
    async def ensure_schema(self) -> None:
        """Ensure durable storage is ready."""
