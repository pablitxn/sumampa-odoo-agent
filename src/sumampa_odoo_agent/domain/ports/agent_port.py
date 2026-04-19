"""Port for agent execution backends."""

from __future__ import annotations

from typing import Any, Protocol


class AgentPort(Protocol):
    async def run(
        self,
        *,
        prompt: str,
        context: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one agent turn and return a structured payload."""
