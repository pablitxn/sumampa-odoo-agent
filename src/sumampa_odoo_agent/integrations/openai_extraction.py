"""Purchase invoice extraction backends."""

from __future__ import annotations

import base64
import mimetypes
import os
from typing import Any, cast

from openai import AsyncOpenAI

from sumampa_odoo_agent.integrations.llm_specs import render_llm_spec
from sumampa_odoo_agent.services.models.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)


class OpenAIPurchaseInvoiceExtractor:
    """Structured multimodal extraction using OpenAI Responses API."""

    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str,
        base_url: str | None = None,
        max_output_tokens: int = 3000,
        prompt_spec: str = "invoice_extraction/purchase_invoice.md",
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._max_output_tokens = max_output_tokens
        self._prompt_spec = prompt_spec
        self._client = client

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        client = self._client or self._build_client()
        request_input = cast(
            Any,
            [
                {
                    "role": "user",
                    "content": _purchase_invoice_input(
                        command,
                        prompt_spec=self._prompt_spec,
                    ),
                }
            ],
        )
        response = await client.responses.parse(
            model=self._model,
            text_format=ExtractedPurchaseInvoiceDocument,
            max_output_tokens=self._max_output_tokens,
            text={"verbosity": "low"},
            input=request_input,
        )
        parsed = _extract_parsed_content(response)
        if parsed is None:
            raise RuntimeError("OpenAI no devolvio una salida estructurada parseable.")
        if isinstance(parsed, ExtractedPurchaseInvoiceDocument):
            return parsed
        return ExtractedPurchaseInvoiceDocument.model_validate(parsed)

    def _build_client(self) -> AsyncOpenAI:
        api_key = os.environ.get(self._api_key_env_var)
        if not api_key:
            raise RuntimeError(
                f"Missing API key in environment variable '{self._api_key_env_var}'"
            )
        return AsyncOpenAI(api_key=api_key, base_url=self._base_url)


def _purchase_invoice_prompt(
    command: AnalyzePurchaseInvoiceCommand,
    *,
    prompt_spec: str,
) -> str:
    supplier_hint = []
    if command.supplier_name:
        supplier_hint.append(f"Proveedor esperado: {command.supplier_name}.")
    if command.supplier_vat:
        supplier_hint.append(f"CUIT esperado del proveedor: {command.supplier_vat}.")
    return render_llm_spec(
        prompt_spec,
        supplier_hints=" ".join(supplier_hint),
    )


def _purchase_invoice_input(
    command: AnalyzePurchaseInvoiceCommand,
    *,
    prompt_spec: str,
) -> list[dict[str, str]]:
    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": _purchase_invoice_prompt(
                command,
                prompt_spec=prompt_spec,
            ),
        }
    ]
    for attachment in command.attachments:
        content.append({"type": "input_image", "image_url": _to_data_url(attachment.filename, attachment.content_type, attachment.content_bytes)})
    return content


def _to_data_url(filename: str, content_type: str | None, content_bytes: bytes) -> str:
    resolved_content_type = content_type or mimetypes.guess_type(filename)[0] or "image/jpeg"
    encoded = base64.b64encode(content_bytes).decode("ascii")
    return f"data:{resolved_content_type};base64,{encoded}"


def _extract_parsed_content(response: Any) -> Any | None:
    for output in getattr(response, "output", []):
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", []):
            parsed = getattr(content, "parsed", None)
            if parsed is not None:
                return parsed
    return None
