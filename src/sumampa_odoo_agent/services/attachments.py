"""Helpers for converting API attachments into internal invoice attachments."""

from __future__ import annotations

import base64

import httpx

from sumampa_odoo_agent.services.errors import ValidationError
from sumampa_odoo_agent.services.models.odoo import InvoiceAttachment


async def resolve_invoice_attachment(
    *,
    filename: str,
    mime_type: str | None,
    content_base64: str | None,
    download_url: str | None,
) -> InvoiceAttachment:
    """Resolve an attachment from inline bytes or a remote URL."""

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
        return InvoiceAttachment(
            filename=filename,
            content_type=mime_type,
            content_bytes=content_bytes,
        )

    if download_url:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
        if not response.content:
            raise ValidationError(
                "attachment payload is empty",
                details={"filename": filename, "download_url": download_url},
            )
        return InvoiceAttachment(
            filename=filename,
            content_type=mime_type or response.headers.get("content-type"),
            content_bytes=response.content,
        )

    raise ValidationError(
        "attachment requires either content_base64 or download_url",
        details={"filename": filename},
    )


def serialize_invoice_attachments(
    attachments: list[InvoiceAttachment],
) -> list[dict[str, str | None]]:
    """Serialize attachments for the persisted purchase workflow context."""

    return [
        {
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "content_base64": base64.b64encode(attachment.content_bytes).decode("ascii"),
        }
        for attachment in attachments
    ]
