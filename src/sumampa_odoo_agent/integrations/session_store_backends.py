"""Session store implementations."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sumampa_odoo_agent.integrations.postgres_session_store import PostgresSessionStore
    from sumampa_odoo_agent.integrations.redis_session_cache import RedisSessionCache


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


class HybridSessionStore:
    """Write-through Postgres + best-effort Redis cache."""

    def __init__(
        self,
        *,
        primary: PostgresSessionStore,
        cache: RedisSessionCache,
    ) -> None:
        self._primary = primary
        self._cache = cache

    async def ensure_schema(self) -> None:
        await self._primary.ensure_schema()

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        try:
            cached = await self._cache.load(namespace=namespace, session_id=session_id)
        except Exception:
            cached = None
        if cached is not None:
            return cached

        payload = await self._primary.load(namespace=namespace, session_id=session_id)
        if payload is None:
            return None
        try:
            await self._cache.save(namespace=namespace, session_id=session_id, payload=payload)
        except Exception:
            pass
        return payload

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        await self._primary.save(namespace=namespace, session_id=session_id, payload=payload)
        try:
            await self._cache.save(namespace=namespace, session_id=session_id, payload=payload)
        except Exception:
            pass

    async def delete(self, *, namespace: str, session_id: str) -> None:
        await self._primary.delete(namespace=namespace, session_id=session_id)
        try:
            await self._cache.delete(namespace=namespace, session_id=session_id)
        except Exception:
            pass

    async def aclose(self) -> None:
        try:
            await self._cache.aclose()
        finally:
            await self._primary.aclose()
