"""Unit tests for Redis session cache payload handling."""

from __future__ import annotations

import pytest

from sumampa_odoo_agent.integrations.sessions import RedisSessionCache


class _FakeRedis:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def get(self, key: str) -> str | None:
        del key
        return self.value

    async def set(self, key: str, value: str, *, ex: int) -> None:
        del key, value, ex

    async def delete(self, *names: str) -> None:
        del names

    async def aclose(self) -> None:
        return None


def _cache_with_value(value: str | None) -> RedisSessionCache:
    return RedisSessionCache(
        url="redis://127.0.0.1:6379/0",
        key_prefix="test",
        ttl_seconds=60,
        client=_FakeRedis(value),
    )


@pytest.mark.asyncio
async def test_redis_session_cache_rejects_non_object_payload() -> None:
    cache = _cache_with_value("[]")

    with pytest.raises(ValueError, match="JSON object"):
        await cache.load(namespace="agent", session_id="session-1")


@pytest.mark.asyncio
async def test_redis_session_cache_loads_object_payload() -> None:
    cache = _cache_with_value('{"status": "active"}')

    assert await cache.load(namespace="agent", session_id="session-1") == {"status": "active"}
