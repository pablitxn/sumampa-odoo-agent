"""Postgres-backed authoritative session store."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class PostgresSessionStore:
    """Persist session snapshots in Postgres JSONB."""

    def __init__(self, *, dsn: str) -> None:
        self._engine: AsyncEngine = create_async_engine(dsn, future=True)

    async def ensure_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS orchid_session_snapshots (
                        namespace TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (namespace, session_id)
                    )
                    """
                )
            )

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT payload
                    FROM orchid_session_snapshots
                    WHERE namespace = :namespace AND session_id = :session_id
                    """
                ),
                {"namespace": namespace, "session_id": session_id},
            )
            row = result.one_or_none()
        if row is None:
            return None
        return cast(dict[str, Any], row[0])

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        async with self._engine.begin() as conn:
            statement = text(
                """
                INSERT INTO orchid_session_snapshots (namespace, session_id, payload, updated_at)
                VALUES (:namespace, :session_id, :payload, NOW())
                ON CONFLICT (namespace, session_id)
                DO UPDATE SET payload = :payload, updated_at = NOW()
                """
            ).bindparams(bindparam("payload", type_=JSONB))
            await conn.execute(
                statement,
                {
                    "namespace": namespace,
                    "session_id": session_id,
                    "payload": payload,
                },
            )

    async def delete(self, *, namespace: str, session_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    DELETE FROM orchid_session_snapshots
                    WHERE namespace = :namespace AND session_id = :session_id
                    """
                ),
                {"namespace": namespace, "session_id": session_id},
            )

    async def aclose(self) -> None:
        await self._engine.dispose()
