"""Session store builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.session_store_backends import (
    HybridSessionStore,
    InMemorySessionStore,
)
from sumampa_odoo_agent.services.contracts import SessionStore


async def build_session_store(settings: AppSettings) -> SessionStore:
    """Build the configured session store."""

    mode = settings.session_store.mode
    if mode == "memory":
        return InMemorySessionStore()
    if mode == "hybrid":
        from sumampa_odoo_agent.integrations.postgres_session_store import PostgresSessionStore
        from sumampa_odoo_agent.integrations.redis_session_cache import RedisSessionCache

        primary = PostgresSessionStore(dsn=settings.session_store.postgres_dsn)
        cache = RedisSessionCache(
            url=settings.session_store.redis_url,
            key_prefix=settings.session_store.redis_key_prefix,
            ttl_seconds=settings.session_store.redis_ttl_seconds,
        )
        store = HybridSessionStore(primary=primary, cache=cache)
        await store.ensure_schema()
        return store
    raise RuntimeError(f"Unsupported session_store.mode: {mode}")
