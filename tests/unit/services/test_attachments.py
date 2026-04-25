"""Unit tests for attachment resolution helpers."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from types import TracebackType

import httpx
import pytest

from sumampa_odoo_agent.config import AttachmentSettings
from sumampa_odoo_agent.integrations.storage import InMemoryAttachmentObjectStore
from sumampa_odoo_agent.services.attachments import (
    AttachmentIngestionService,
    _detect_content_type,
    resolve_invoice_attachment,
)
from sumampa_odoo_agent.services.errors import UpstreamServiceError, ValidationError
from sumampa_odoo_agent.services.models.attachments import AttachmentSource


class _FailingDownloadClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> _FailingDownloadClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def stream(self, method: str, url: str) -> _ResponseStream:
        del method
        return _ResponseStream(
            httpx.Response(
                502,
                request=httpx.Request("GET", url),
                json={"error": "bad gateway"},
            )
        )


class _LargeDownloadClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> _LargeDownloadClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def stream(self, method: str, url: str) -> _ResponseStream:
        del method, url
        return _ResponseStream(_ChunkedResponse(headers={"content-length": "10"}, chunks=[b"abcdef"]))


class _ResponseStream:
    def __init__(self, response: httpx.Response | _ChunkedResponse) -> None:
        self._response = response

    async def __aenter__(self) -> httpx.Response | _ChunkedResponse:
        return self._response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback


class _ChunkedResponse:
    def __init__(self, *, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.headers = headers
        self._chunks = chunks

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class _ChunkedDownloadClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> _ChunkedDownloadClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def stream(self, method: str, url: str) -> _ResponseStream:
        del method, url
        return _ResponseStream(
            _ChunkedResponse(
                headers={"content-type": "text/plain"},
                chunks=[b"hello", b" ", b"world"],
            )
        )


@pytest.mark.asyncio
async def test_resolve_invoice_attachment_translates_download_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.attachments.httpx.AsyncClient",
        _FailingDownloadClient,
    )

    with pytest.raises(UpstreamServiceError) as exc_info:
        await resolve_invoice_attachment(
            filename="invoice.pdf",
            mime_type=None,
            content_base64=None,
            download_url="https://example.test/invoice.pdf",
        )

    assert exc_info.value.code == "attachment_download_failed"
    assert exc_info.value.details["filename"] == "invoice.pdf"


@pytest.mark.asyncio
async def test_attachment_ingestion_streams_downloads_with_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.attachments.httpx.AsyncClient",
        _LargeDownloadClient,
    )
    store = InMemoryAttachmentObjectStore()
    service = AttachmentIngestionService(
        object_store=store,
        settings=AttachmentSettings(store_mode="memory", max_attachment_bytes=5),
    )

    with pytest.raises(ValidationError) as exc_info:
        await service.prepare_attachments(
            [
                AttachmentSource(
                    filename="large.txt",
                    download_url="https://example.test/large.txt",
                )
            ],
            conversation_id="conversation-1",
            channel="whatsapp",
            user_id="user-1",
        )

    assert exc_info.value.code == "attachment_too_large"
    assert store.objects == {}


@pytest.mark.asyncio
async def test_attachment_ingestion_reads_chunked_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sumampa_odoo_agent.services.attachments.httpx.AsyncClient",
        _ChunkedDownloadClient,
    )
    store = InMemoryAttachmentObjectStore()
    service = AttachmentIngestionService(
        object_store=store,
        settings=AttachmentSettings(store_mode="memory"),
    )

    prepared = await service.prepare_attachments(
        [
            AttachmentSource(
                filename="note.txt",
                download_url="https://example.test/note.txt",
            )
        ],
        conversation_id="conversation-1",
        channel="whatsapp",
        user_id="user-1",
    )

    assert prepared[0].artifacts[0].text == "hello world"


@pytest.mark.asyncio
async def test_attachment_ingestion_stores_original_and_prepares_image() -> None:
    store = InMemoryAttachmentObjectStore()
    service = AttachmentIngestionService(
        object_store=store,
        settings=AttachmentSettings(store_mode="memory"),
    )

    prepared = await service.prepare_attachments(
        [
            AttachmentSource(
                filename="attachment.jpg",
                content_type="image/jpeg",
                content_base64=base64.b64encode(b"fake-image").decode("ascii"),
            )
        ],
        conversation_id="conversation-1",
        channel="whatsapp",
        user_id="user-1",
    )

    assert len(prepared) == 1
    assert prepared[0].stored.storage_uri.startswith("memory://")
    assert prepared[0].stored.object_key in store.objects
    assert prepared[0].artifacts[0].kind == "image"
    assert prepared[0].artifacts[0].content_bytes == b"fake-image"


@pytest.mark.asyncio
async def test_attachment_ingestion_rejects_video_after_storing_original() -> None:
    store = InMemoryAttachmentObjectStore()
    service = AttachmentIngestionService(
        object_store=store,
        settings=AttachmentSettings(store_mode="memory"),
    )

    with pytest.raises(ValidationError) as exc_info:
        await service.prepare_attachments(
            [
                AttachmentSource(
                    filename="clip.mp4",
                    content_type="video/mp4",
                    content_base64=base64.b64encode(b"fake-video").decode("ascii"),
                )
            ],
            conversation_id="conversation-1",
            channel="whatsapp",
            user_id="user-1",
        )

    assert exc_info.value.code == "unsupported_attachment_type"
    assert len(store.objects) == 1


def test_detect_content_type_prefers_magic_bytes_over_declared_mime() -> None:
    assert (
        _detect_content_type(
            filename="invoice.jpg",
            declared_content_type="image/jpeg",
            content_bytes=b"%PDF-1.7\n",
        )
        == "application/pdf"
    )
