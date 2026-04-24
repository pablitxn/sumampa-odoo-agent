"""Redis cache for conversational session snapshots."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from redis.asyncio import Redis


class RedisClient(Protocol):
    async def get(self, name: str) -> str | None:
        """Return one decoded value."""

    async def set(self, name: str, value: str, *, ex: int) -> object:
        """Set one value with an expiry."""

    async def delete(self, *names: str) -> object:
        """Delete one or more values."""

    async def aclose(self) -> None:
        """Close the client."""


class RedisSessionCache:
    """Best-effort Redis cache for session payloads."""

    def __init__(
        self,
        *,
        url: str,
        key_prefix: str,
        ttl_seconds: int,
        client: RedisClient | None = None,
    ) -> None:
        self._client = client or cast(RedisClient, Redis.from_url(url, decode_responses=True))
        self._key_prefix = key_prefix
        self._ttl_seconds = ttl_seconds

    def _key(self, *, namespace: str, session_id: str) -> str:
        return f"{self._key_prefix}:{namespace}:{session_id}"

    async def load(self, *, namespace: str, session_id: str) -> dict[str, Any] | None:
        value = await self._client.get(self._key(namespace=namespace, session_id=session_id))
        if value is None:
            return None
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("Redis session payload must be a JSON object")
        if not all(isinstance(key, str) for key in payload):
            raise ValueError("Redis session payload keys must be strings")
        return dict(payload)

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
