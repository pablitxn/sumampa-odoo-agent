"""Generic attachment models used across transport, storage, and agent prep."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AttachmentArtifactKind = Literal["text", "image", "audio"]


class AttachmentSource(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str | None = None
    content_base64: str | None = None
    download_url: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> AttachmentSource:
        if bool(self.content_base64) == bool(self.download_url):
            raise ValueError("provide exactly one of content_base64 or download_url")
        return self


class StoredObjectReference(BaseModel):
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    etag: str | None = None


class StoredAttachment(BaseModel):
    attachment_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)
    object_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    expires_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class PreparedAttachmentArtifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    source_attachment_id: str = Field(min_length=1)
    kind: AttachmentArtifactKind
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    text: str | None = None
    content_bytes: bytes | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> PreparedAttachmentArtifact:
        if self.kind == "text" and not self.text:
            raise ValueError("text artifacts require text")
        if self.kind in {"image", "audio"} and not self.content_bytes:
            raise ValueError(f"{self.kind} artifacts require content_bytes")
        return self


class AttachmentArtifactContext(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: AttachmentArtifactKind
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachmentRuntimeManifest(BaseModel):
    attachment_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)
    storage_uri: str = Field(min_length=1)
    expires_at: datetime
    artifacts: list[AttachmentArtifactContext] = Field(default_factory=list)


class PreparedAttachment(BaseModel):
    stored: StoredAttachment
    artifacts: list[PreparedAttachmentArtifact] = Field(default_factory=list)

    def to_runtime_manifest(self) -> AttachmentRuntimeManifest:
        return AttachmentRuntimeManifest(
            attachment_id=self.stored.attachment_id,
            filename=self.stored.filename,
            content_type=self.stored.content_type,
            size_bytes=self.stored.size_bytes,
            sha256=self.stored.sha256,
            storage_uri=self.stored.storage_uri,
            expires_at=self.stored.expires_at,
            artifacts=[
                AttachmentArtifactContext(
                    artifact_id=artifact.artifact_id,
                    kind=artifact.kind,
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    metadata=artifact.metadata,
                )
                for artifact in self.artifacts
            ],
        )
