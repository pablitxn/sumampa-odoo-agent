"""Unit tests for attachment resolution helpers."""

from __future__ import annotations

from types import TracebackType

import httpx
import pytest

from sumampa_odoo_agent.services.attachments import resolve_invoice_attachment
from sumampa_odoo_agent.services.errors import UpstreamServiceError


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

    async def get(self, url: str) -> httpx.Response:
        return httpx.Response(
            502,
            request=httpx.Request("GET", url),
            json={"error": "bad gateway"},
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
