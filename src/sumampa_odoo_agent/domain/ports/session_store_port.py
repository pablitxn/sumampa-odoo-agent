"""Port for persisted conversational session state."""

from __future__ import annotations

from typing import Any, Protocol


class SessionStorePort(Protocol):
    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        """Load one persisted session payload."""

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        """Persist one session payload."""

    async def delete(self, *, namespace: str, session_id: str) -> None:
        """Delete one persisted session payload."""

    async def aclose(self) -> None:
        """Release store resources."""
