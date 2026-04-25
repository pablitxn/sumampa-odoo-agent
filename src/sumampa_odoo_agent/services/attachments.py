"""Attachment ingestion, storage, and LLM preparation helpers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import uuid4

import httpx

from sumampa_odoo_agent.config import AttachmentSettings
from sumampa_odoo_agent.services.contracts import AttachmentObjectStore
from sumampa_odoo_agent.services.errors import UpstreamServiceError, ValidationError
from sumampa_odoo_agent.services.models.attachments import (
    AttachmentSource,
    PreparedAttachment,
    PreparedAttachmentArtifact,
    StoredAttachment,
)
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment

if TYPE_CHECKING:
    from sumampa_odoo_agent.services.models.runtime import SerializedInvoiceAttachment

ATTACHMENT_DOWNLOAD_FAILED_MESSAGE = "Could not download the attachment."


@dataclass(frozen=True, slots=True)
class _ResolvedAttachmentBytes:
    filename: str
    content_type: str | None
    content_bytes: bytes


class AttachmentIngestionService:
    """Persist original attachments and prepare model-readable derivatives."""

    def __init__(
        self,
        *,
        object_store: AttachmentObjectStore,
        settings: AttachmentSettings,
    ) -> None:
        self._object_store = object_store
        self._settings = settings

    async def prepare_attachments(
        self,
        sources: list[AttachmentSource],
        *,
        conversation_id: str,
        channel: str,
        user_id: str,
    ) -> list[PreparedAttachment]:
        prepared: list[PreparedAttachment] = []
        for source in sources:
            resolved = await _resolve_attachment_bytes(
                filename=source.filename,
                content_type=source.content_type,
                content_base64=source.content_base64,
                download_url=source.download_url,
                max_bytes=self._settings.max_attachment_bytes,
            )
            prepared.append(
                await self._prepare_one(
                    resolved,
                    conversation_id=conversation_id,
                    channel=channel,
                    user_id=user_id,
                )
            )
        return prepared

    async def _prepare_one(
        self,
        attachment: _ResolvedAttachmentBytes,
        *,
        conversation_id: str,
        channel: str,
        user_id: str,
    ) -> PreparedAttachment:
        content_size = len(attachment.content_bytes)
        if content_size > self._settings.max_attachment_bytes:
            raise ValidationError(
                "attachment is larger than the configured limit",
                code="attachment_too_large",
                details={
                    "filename": attachment.filename,
                    "size_bytes": content_size,
                    "max_attachment_bytes": self._settings.max_attachment_bytes,
                },
            )

        content_type = _detect_content_type(
            filename=attachment.filename,
            declared_content_type=attachment.content_type,
            content_bytes=attachment.content_bytes,
        )
        attachment_id = str(uuid4())
        sha256 = hashlib.sha256(attachment.content_bytes).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.retention_ttl_seconds)
        object_key = _build_object_key(
            key_prefix=self._settings.key_prefix,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
            filename=attachment.filename,
        )
        stored_ref = await self._object_store.put_object(
            key=object_key,
            content_bytes=attachment.content_bytes,
            content_type=content_type,
            metadata={
                "attachment-id": attachment_id,
                "sha256": sha256,
                "size-bytes": str(content_size),
                "conversation-id": conversation_id,
                "user-id": user_id,
                "channel": channel,
                "expires-at": expires_at.isoformat(),
                "filename": quote(attachment.filename, safe=""),
            },
        )
        stored = StoredAttachment(
            attachment_id=attachment_id,
            filename=attachment.filename,
            content_type=content_type,
            size_bytes=content_size,
            sha256=sha256,
            object_key=stored_ref.key,
            storage_uri=stored_ref.uri,
            expires_at=expires_at,
            metadata={"etag": stored_ref.etag} if stored_ref.etag else {},
        )
        artifacts = await self._prepare_artifacts(
            stored=stored,
            content_bytes=attachment.content_bytes,
        )
        return PreparedAttachment(stored=stored, artifacts=artifacts)

    async def _prepare_artifacts(
        self,
        *,
        stored: StoredAttachment,
        content_bytes: bytes,
    ) -> list[PreparedAttachmentArtifact]:
        if stored.content_type.startswith("image/"):
            return [
                PreparedAttachmentArtifact(
                    artifact_id=str(uuid4()),
                    source_attachment_id=stored.attachment_id,
                    kind="image",
                    filename=stored.filename,
                    content_type=stored.content_type,
                    content_bytes=content_bytes,
                )
            ]
        if stored.content_type.startswith("text/"):
            return [
                _build_text_artifact(
                    source_attachment_id=stored.attachment_id,
                    filename=stored.filename,
                    text=_decode_text(content_bytes),
                    max_text_chars=self._settings.max_text_chars,
                )
            ]
        if stored.content_type == "application/pdf":
            return await _prepare_pdf_artifacts(
                source_attachment_id=stored.attachment_id,
                filename=stored.filename,
                content_bytes=content_bytes,
                max_pdf_pages=self._settings.max_pdf_pages,
                max_text_chars=self._settings.max_text_chars,
            )
        if stored.content_type.startswith("audio/"):
            return await _prepare_audio_artifacts(
                source_attachment_id=stored.attachment_id,
                filename=stored.filename,
                content_bytes=content_bytes,
            )
        if stored.content_type.startswith("video/"):
            raise ValidationError(
                "video attachments are not supported for LLM ingestion yet",
                code="unsupported_attachment_type",
                details={"filename": stored.filename, "content_type": stored.content_type},
            )
        raise ValidationError(
            "attachment content type is not supported for LLM ingestion",
            code="unsupported_attachment_type",
            details={"filename": stored.filename, "content_type": stored.content_type},
        )


async def _resolve_attachment_bytes(
    *,
    filename: str,
    content_type: str | None,
    content_base64: str | None,
    download_url: str | None,
    max_bytes: int | None = None,
) -> _ResolvedAttachmentBytes:
    if content_base64:
        try:
            content_bytes = base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise ValidationError(
                "attachment content_base64 is not valid base64",
                details={"filename": filename},
            ) from exc
        if not content_bytes:
            raise ValidationError(
                "attachment payload is empty",
                details={"filename": filename},
            )
        _validate_attachment_size(
            filename=filename,
            size_bytes=len(content_bytes),
            max_bytes=max_bytes,
        )
        return _ResolvedAttachmentBytes(
            filename=filename,
            content_type=content_type,
            content_bytes=content_bytes,
        )

    if download_url:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    content_bytes = await _read_limited_response_bytes(
                        response,
                        filename=filename,
                        max_bytes=max_bytes,
                    )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError(
                ATTACHMENT_DOWNLOAD_FAILED_MESSAGE,
                code="attachment_download_failed",
                details={
                    "filename": filename,
                    "download_url": download_url,
                    "exception_type": exc.__class__.__name__,
                },
            ) from exc
        if not content_bytes:
            raise ValidationError(
                "attachment payload is empty",
                details={"filename": filename, "download_url": download_url},
            )
        return _ResolvedAttachmentBytes(
            filename=filename,
            content_type=content_type or response.headers.get("content-type"),
            content_bytes=content_bytes,
        )

    raise ValidationError(
        "attachment requires either content_base64 or download_url",
        details={"filename": filename},
    )


def _detect_content_type(
    *,
    filename: str,
    declared_content_type: str | None,
    content_bytes: bytes,
) -> str:
    declared = _normalize_content_type(declared_content_type)
    detected = _detect_content_type_from_magic(content_bytes)
    if detected:
        if detected == "video/mp4" and declared in {"audio/mp4", "video/mp4"}:
            return declared
        return detected
    guessed_content_type, _ = mimetypes.guess_type(filename)
    guessed = _normalize_content_type(guessed_content_type)
    if guessed:
        if declared and _top_level_content_type(declared) == _top_level_content_type(guessed):
            return declared
        return guessed
    if _looks_like_text(content_bytes):
        return "text/plain"
    return declared or "application/octet-stream"


async def _read_limited_response_bytes(
    response: httpx.Response,
    *,
    filename: str,
    max_bytes: int | None,
) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            _validate_attachment_size(
                filename=filename,
                size_bytes=int(content_length),
                max_bytes=max_bytes,
            )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total_size = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        total_size += len(chunk)
        _validate_attachment_size(
            filename=filename,
            size_bytes=total_size,
            max_bytes=max_bytes,
        )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_attachment_size(
    *,
    filename: str,
    size_bytes: int,
    max_bytes: int | None,
) -> None:
    if max_bytes is not None and size_bytes > max_bytes:
        raise ValidationError(
            "attachment is larger than the configured limit",
            code="attachment_too_large",
            details={
                "filename": filename,
                "size_bytes": size_bytes,
                "max_attachment_bytes": max_bytes,
            },
        )


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized or None


def _detect_content_type_from_magic(content_bytes: bytes) -> str | None:
    if content_bytes.startswith(b"%PDF"):
        return "application/pdf"
    if content_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content_bytes.startswith(b"GIF87a") or content_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if content_bytes.startswith(b"RIFF"):
        if content_bytes[8:12] == b"WAVE":
            return "audio/wav"
        if content_bytes[8:12] == b"WEBP":
            return "image/webp"
    if content_bytes.startswith(b"OggS"):
        return "audio/ogg"
    if content_bytes.startswith(b"ID3") or (
        len(content_bytes) >= 2 and content_bytes[0] == 0xFF and content_bytes[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if len(content_bytes) >= 12 and content_bytes[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _top_level_content_type(content_type: str) -> str:
    return content_type.split("/", 1)[0]


def _looks_like_text(content_bytes: bytes) -> bool:
    try:
        content_bytes[:4096].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _build_object_key(
    *,
    key_prefix: str,
    conversation_id: str,
    attachment_id: str,
    filename: str,
) -> str:
    safe_prefix = key_prefix.strip("/")
    safe_conversation_id = _safe_key_part(conversation_id)
    safe_filename = _safe_key_part(Path(filename).name or "attachment")
    date_path = datetime.now(UTC).strftime("%Y/%m/%d")
    return f"{safe_prefix}/{date_path}/{safe_conversation_id}/{attachment_id}/{safe_filename}"


def _safe_key_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]+", "_", value).strip("._") or "attachment"


def _decode_text(content_bytes: bytes) -> str:
    return content_bytes.decode("utf-8", errors="replace").strip()


def _build_text_artifact(
    *,
    source_attachment_id: str,
    filename: str,
    text: str,
    max_text_chars: int,
) -> PreparedAttachmentArtifact:
    metadata: dict[str, str] = {}
    if len(text) > max_text_chars:
        text = text[:max_text_chars]
        metadata["truncated"] = "true"
    return PreparedAttachmentArtifact(
        artifact_id=str(uuid4()),
        source_attachment_id=source_attachment_id,
        kind="text",
        filename=f"{Path(filename).stem or 'attachment'}.txt",
        content_type="text/plain",
        text=text or "(empty text attachment)",
        metadata=metadata,
    )


async def _prepare_pdf_artifacts(
    *,
    source_attachment_id: str,
    filename: str,
    content_bytes: bytes,
    max_pdf_pages: int,
    max_text_chars: int,
) -> list[PreparedAttachmentArtifact]:
    _require_command("pdftotext", processor="pdf")
    _require_command("pdftoppm", processor="pdf")

    def _run_pdf_tools() -> list[PreparedAttachmentArtifact]:
        with tempfile.TemporaryDirectory(prefix="sumampa-pdf-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.pdf"
            input_path.write_bytes(content_bytes)

            text_result = subprocess.run(
                ["pdftotext", "-f", "1", "-l", str(max_pdf_pages), str(input_path), "-"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            artifacts: list[PreparedAttachmentArtifact] = []
            extracted_text = text_result.stdout.strip()
            if extracted_text:
                artifacts.append(
                    _build_text_artifact(
                        source_attachment_id=source_attachment_id,
                        filename=filename,
                        text=extracted_text,
                        max_text_chars=max_text_chars,
                    )
                )

            output_prefix = temp_path / "page"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    str(max_pdf_pages),
                    "-jpeg",
                    "-r",
                    "144",
                    str(input_path),
                    str(output_prefix),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            for index, page_path in enumerate(sorted(temp_path.glob("page-*.jpg")), start=1):
                artifacts.append(
                    PreparedAttachmentArtifact(
                        artifact_id=str(uuid4()),
                        source_attachment_id=source_attachment_id,
                        kind="image",
                        filename=f"{Path(filename).stem or 'attachment'}-page-{index}.jpg",
                        content_type="image/jpeg",
                        content_bytes=page_path.read_bytes(),
                        metadata={"page": str(index)},
                    )
                )
            if not artifacts:
                raise ValidationError(
                    "PDF attachment did not produce model-readable artifacts",
                    code="attachment_processing_failed",
                    details={"filename": filename},
                )
            return artifacts

    try:
        return await asyncio.to_thread(_run_pdf_tools)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(
            "PDF attachment could not be processed",
            code="attachment_processing_failed",
            details={"filename": filename},
        ) from exc


async def _prepare_audio_artifacts(
    *,
    source_attachment_id: str,
    filename: str,
    content_bytes: bytes,
) -> list[PreparedAttachmentArtifact]:
    _require_command("ffmpeg", processor="audio")

    def _run_ffmpeg() -> bytes:
        with tempfile.TemporaryDirectory(prefix="sumampa-audio-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input"
            output_path = temp_path / "output.mp3"
            input_path.write_bytes(content_bytes)
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "64k",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            return output_path.read_bytes()

    try:
        audio_bytes = await asyncio.to_thread(_run_ffmpeg)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(
            "audio attachment could not be processed",
            code="attachment_processing_failed",
            details={"filename": filename},
        ) from exc

    return [
        PreparedAttachmentArtifact(
            artifact_id=str(uuid4()),
            source_attachment_id=source_attachment_id,
            kind="audio",
            filename=f"{Path(filename).stem or 'attachment'}.mp3",
            content_type="audio/mp3",
            content_bytes=audio_bytes,
            metadata={"transcoded": "true"},
        )
    ]


def _require_command(command: str, *, processor: str) -> None:
    if shutil.which(command) is None:
        raise ValidationError(
            f"{processor} attachment processor is not available",
            code="attachment_processor_unavailable",
            details={"command": command, "processor": processor},
        )


async def resolve_invoice_attachment(
    *,
    filename: str,
    mime_type: str | None,
    content_base64: str | None,
    download_url: str | None,
) -> InvoiceAttachment:
    """Compatibility wrapper for older invoice-oriented attachment callers."""

    resolved = await _resolve_attachment_bytes(
        filename=filename,
        content_type=mime_type,
        content_base64=content_base64,
        download_url=download_url,
    )
    return InvoiceAttachment(
        filename=resolved.filename,
        content_type=resolved.content_type,
        content_bytes=resolved.content_bytes,
    )


def serialize_invoice_attachments(
    attachments: list[InvoiceAttachment],
) -> list[SerializedInvoiceAttachment]:
    """Compatibility serializer for older invoice-oriented runtime context."""

    from sumampa_odoo_agent.services.models.runtime import SerializedInvoiceAttachment

    return [
        SerializedInvoiceAttachment(
            filename=attachment.filename,
            content_type=attachment.content_type,
            content_base64=base64.b64encode(attachment.content_bytes).decode("ascii"),
        )
        for attachment in attachments
    ]
