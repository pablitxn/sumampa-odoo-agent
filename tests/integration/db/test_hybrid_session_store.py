from __future__ import annotations

from uuid import uuid4

import pytest

from sumampa_odoo_agent.integrations.postgres_session_store import PostgresSessionStore
from sumampa_odoo_agent.integrations.redis_session_cache import RedisSessionCache
from sumampa_odoo_agent.integrations.session_store_backends import HybridSessionStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_session_store_rehydrates_redis_from_postgres(
    session_store_env: dict[str, str],
) -> None:
    key_prefix = f"test-hybrid-cache-{uuid4()}"
    primary = PostgresSessionStore(dsn=session_store_env["postgres_dsn"])
    cache = RedisSessionCache(
        url=session_store_env["redis_url"],
        key_prefix=key_prefix,
        ttl_seconds=60,
    )
    store = HybridSessionStore(primary=primary, cache=cache)
    namespace = f"test-hybrid-{uuid4()}"
    session_id = str(uuid4())
    payload = {"status": "active", "history": ["a", "b", "c"]}

    try:
        await store.ensure_schema()
        await store.save(namespace=namespace, session_id=session_id, payload=payload)

        cached = await cache.load(namespace=namespace, session_id=session_id)
        assert cached == payload

        await cache.delete(namespace=namespace, session_id=session_id)
        assert await cache.load(namespace=namespace, session_id=session_id) is None

        loaded = await store.load(namespace=namespace, session_id=session_id)
        assert loaded == payload
        assert await cache.load(namespace=namespace, session_id=session_id) == payload

        await store.delete(namespace=namespace, session_id=session_id)
        assert await primary.load(namespace=namespace, session_id=session_id) is None
        assert await cache.load(namespace=namespace, session_id=session_id) is None
    finally:
        await store.aclose()
