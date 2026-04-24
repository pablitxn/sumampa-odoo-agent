from __future__ import annotations

from uuid import uuid4

import pytest

from sumampa_odoo_agent.integrations.postgres_session_store import PostgresSessionStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_session_store_round_trip(session_store_env: dict[str, str]) -> None:
    store = PostgresSessionStore(dsn=session_store_env["postgres_dsn"])
    namespace = f"test-postgres-{uuid4()}"
    session_id = str(uuid4())
    payload = {"status": "active", "count": 2}

    try:
        await store.ensure_schema()
        await store.save(namespace=namespace, session_id=session_id, payload=payload)

        loaded = await store.load(namespace=namespace, session_id=session_id)
        assert loaded == payload

        await store.delete(namespace=namespace, session_id=session_id)
        deleted = await store.load(namespace=namespace, session_id=session_id)
        assert deleted is None
    finally:
        await store.aclose()
