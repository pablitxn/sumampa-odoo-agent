"""In-memory session store for tests and local development."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemorySessionStore:
    """Simple in-process fallback store for tests and dev."""

    def __init__(self) -> None:
        self._payloads: dict[tuple[str, str], dict[str, Any]] = {}

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        payload = self._payloads.get((namespace, session_id))
        if payload is None:
            return None
        return deepcopy(payload)

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        self._payloads[(namespace, session_id)] = deepcopy(payload)

    async def delete(self, *, namespace: str, session_id: str) -> None:
        self._payloads.pop((namespace, session_id), None)

    async def aclose(self) -> None:
        return None
