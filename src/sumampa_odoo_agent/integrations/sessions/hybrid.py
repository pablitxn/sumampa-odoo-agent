"""Hybrid session store implementation."""

from __future__ import annotations

import logging
from typing import Any

from sumampa_odoo_agent.integrations.sessions.protocols import (
    DurableSessionStore,
    SessionCache,
)

logger = logging.getLogger(__name__)


class HybridSessionStore:
    """Write-through Postgres + best-effort Redis cache."""

    def __init__(
        self,
        *,
        primary: DurableSessionStore,
        cache: SessionCache,
    ) -> None:
        self._primary = primary
        self._cache = cache

    async def ensure_schema(self) -> None:
        await self._primary.ensure_schema()

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        try:
            cached = await self._cache.load(namespace=namespace, session_id=session_id)
        except Exception:
            _log_cache_failure("load")
            cached = None
        if cached is not None:
            return cached

        payload = await self._primary.load(namespace=namespace, session_id=session_id)
        if payload is None:
            return None
        try:
            await self._cache.save(namespace=namespace, session_id=session_id, payload=payload)
        except Exception:
            _log_cache_failure("save")
        return payload

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        await self._primary.save(namespace=namespace, session_id=session_id, payload=payload)
        try:
            await self._cache.save(namespace=namespace, session_id=session_id, payload=payload)
        except Exception:
            _log_cache_failure("save")

    async def delete(self, *, namespace: str, session_id: str) -> None:
        await self._primary.delete(namespace=namespace, session_id=session_id)
        try:
            await self._cache.delete(namespace=namespace, session_id=session_id)
        except Exception:
            _log_cache_failure("delete")

    async def aclose(self) -> None:
        try:
            await self._cache.aclose()
        finally:
            await self._primary.aclose()


def _log_cache_failure(operation: str) -> None:
    logger.warning(
        "Session cache %s failed; continuing with primary store",
        operation,
        exc_info=True,
    )
