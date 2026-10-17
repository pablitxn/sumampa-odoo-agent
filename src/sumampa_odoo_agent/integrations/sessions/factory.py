"""Session store builders."""

from __future__ import annotations

from sumampa_odoo_agent.config import AppSettings
from sumampa_odoo_agent.integrations.sessions.hybrid import HybridSessionStore
from sumampa_odoo_agent.integrations.sessions.memory import InMemorySessionStore
from sumampa_odoo_agent.services.contracts import SessionStore
from sumampa_odoo_agent.services.errors import ConfigurationError


async def build_session_store(settings: AppSettings) -> SessionStore:
    """Build the configured session store."""

    mode = settings.session_store.mode
    if mode == "memory":
        return InMemorySessionStore()
    if mode == "hybrid":
        if not settings.session_store.postgres_dsn.strip():
            raise ConfigurationError(
                "Set SESSION_STORE_POSTGRES_DSN privately for hybrid sessions.",
                code="session_store_credentials_missing",
            )
        from sumampa_odoo_agent.integrations.sessions.postgres import PostgresSessionStore
        from sumampa_odoo_agent.integrations.sessions.redis import RedisSessionCache

        primary = PostgresSessionStore(dsn=settings.session_store.postgres_dsn)
        cache = RedisSessionCache(
            url=settings.session_store.redis_url,
            key_prefix=settings.session_store.redis_key_prefix,
            ttl_seconds=settings.session_store.redis_ttl_seconds,
        )
        store = HybridSessionStore(primary=primary, cache=cache)
        await store.ensure_schema()
        return store
    raise ConfigurationError(
        f"Unsupported session_store.mode: {mode}",
        code="unsupported_session_store_mode",
    )
