"""Unit tests for session store fallback behavior."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sumampa_odoo_agent.integrations.sessions import HybridSessionStore


class _PrimaryStore:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.saved: dict[str, Any] | None = None
        self.deleted = False

    async def ensure_schema(self) -> None:
        return None

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        del namespace, session_id
        return self.payload

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        del namespace, session_id
        self.saved = payload

    async def delete(self, *, namespace: str, session_id: str) -> None:
        del namespace, session_id
        self.deleted = True

    async def aclose(self) -> None:
        return None


class _FailingCache:
    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        del namespace, session_id
        raise RuntimeError("cache unavailable")

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        del namespace, session_id, payload
        raise RuntimeError("cache unavailable")

    async def delete(self, *, namespace: str, session_id: str) -> None:
        del namespace, session_id
        raise RuntimeError("cache unavailable")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_hybrid_session_store_logs_cache_failures_and_uses_primary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = _PrimaryStore(payload={"status": "active"})
    store = HybridSessionStore(
        primary=primary,
        cache=_FailingCache(),
    )

    with caplog.at_level(logging.WARNING):
        loaded = await store.load(namespace="agent", session_id="session-1")
        await store.save(namespace="agent", session_id="session-1", payload={"status": "next"})
        await store.delete(namespace="agent", session_id="session-1")

    assert loaded == {"status": "active"}
    assert primary.saved == {"status": "next"}
    assert primary.deleted is True
    assert "Session cache load failed" in caplog.text
    assert "Session cache save failed" in caplog.text
    assert "Session cache delete failed" in caplog.text
