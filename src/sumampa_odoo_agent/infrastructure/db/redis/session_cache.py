"""Redis cache for conversational session snapshots."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis


class RedisSessionCache:
    """Best-effort Redis cache for session payloads."""

    def __init__(self, *, url: str, key_prefix: str, ttl_seconds: int) -> None:
        self._client = Redis.from_url(url, decode_responses=True)
        self._key_prefix = key_prefix
        self._ttl_seconds = ttl_seconds

    def _key(self, *, namespace: str, session_id: str) -> str:
        return f"{self._key_prefix}:{namespace}:{session_id}"

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        value = await self._client.get(self._key(namespace=namespace, session_id=session_id))
        if value is None:
            return None
        return json.loads(value)  # type: ignore[no-any-return]

    async def save(self, *, namespace: str, session_id: str, payload: dict[str, Any]) -> None:
        await self._client.set(
            self._key(namespace=namespace, session_id=session_id),
            json.dumps(payload),
            ex=self._ttl_seconds,
        )

    async def delete(self, *, namespace: str, session_id: str) -> None:
        await self._client.delete(self._key(namespace=namespace, session_id=session_id))

    async def aclose(self) -> None:
        await self._client.aclose()
