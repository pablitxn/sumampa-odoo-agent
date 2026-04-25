"""In-memory attachment object store for tests."""

from __future__ import annotations

from dataclasses import dataclass

from sumampa_odoo_agent.services.models.attachments import StoredObjectReference


@dataclass(slots=True)
class StoredMemoryObject:
    content_bytes: bytes
    content_type: str
    metadata: dict[str, str]


class InMemoryAttachmentObjectStore:
    """Small in-process object store used by unit and API tests."""

    def __init__(self, *, bucket_name: str = "memory-attachments") -> None:
        self._bucket_name = bucket_name
        self.objects: dict[str, StoredMemoryObject] = {}

    async def put_object(
        self,
        *,
        key: str,
        content_bytes: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> StoredObjectReference:
        self.objects[key] = StoredMemoryObject(
            content_bytes=content_bytes,
            content_type=content_type,
            metadata=dict(metadata),
        )
        return StoredObjectReference(
            bucket=self._bucket_name,
            key=key,
            uri=f"memory://{self._bucket_name}/{key}",
        )

    async def aclose(self) -> None:
        return None
