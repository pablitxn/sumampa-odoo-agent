from __future__ import annotations

from uuid import uuid4

import pytest

from sumampa_odoo_agent.infrastructure.db.redis.session_cache import RedisSessionCache


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_session_cache_round_trip(session_store_env: dict[str, str]) -> None:
    cache = RedisSessionCache(
        url=session_store_env["redis_url"],
        key_prefix=f"test-session-cache-{uuid4()}",
        ttl_seconds=60,
    )
    namespace = f"test-redis-{uuid4()}"
    session_id = str(uuid4())
    payload = {"stage": "awaiting_resolution", "warnings": ["uno", "dos"]}

    try:
        await cache.save(namespace=namespace, session_id=session_id, payload=payload)

        loaded = await cache.load(namespace=namespace, session_id=session_id)
        assert loaded == payload

        await cache.delete(namespace=namespace, session_id=session_id)
        deleted = await cache.load(namespace=namespace, session_id=session_id)
        assert deleted is None
    finally:
        await cache.aclose()
