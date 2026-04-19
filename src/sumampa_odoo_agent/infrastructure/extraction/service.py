"""Purchase invoice extraction backends."""

from __future__ import annotations

import base64
import mimetypes
import os
from typing import Any

from openai import AsyncOpenAI

from sumampa_odoo_agent.application.requests.odoo import (
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
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._api_key_env_var = api_key_env_var
        self._base_url = base_url
        self._max_output_tokens = max_output_tokens
        self._client = client

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        client = self._client or self._build_client()
        response = await client.responses.parse(
            model=self._model,
            text_format=ExtractedPurchaseInvoiceDocument,
            max_output_tokens=self._max_output_tokens,
            text={"verbosity": "low"},
            input=[
                {
                    "role": "user",
                    "content": _purchase_invoice_input(command),
                }
            ],
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


def _purchase_invoice_prompt(command: AnalyzePurchaseInvoiceCommand) -> str:
    supplier_hint = []
    if command.supplier_name:
        supplier_hint.append(f"Proveedor esperado: {command.supplier_name}.")
    if command.supplier_vat:
        supplier_hint.append(f"CUIT esperado del proveedor: {command.supplier_vat}.")
    hints = " ".join(supplier_hint)
    return (
        "Extrae una factura de compra argentina desde una o varias fotos del mismo comprobante. "
        "Devolve exclusivamente los campos del schema con structured output estricto. "
        "No inventes lineas ni valores. "
        "Si un dato no es legible, usa null en campos opcionales. "
        "Las imágenes pueden ser distintas fotos del frente, pie o distintas secciones de la misma factura física; tomalas como un único documento. "
        "Extrae razon social, CUIT del proveedor, numero de factura, fecha, tipo de comprobante, moneda, subtotal neto, IVA total y total final si aparecen. "
        "Para cada linea usa descripcion tal como aparece, cantidad, precio unitario final de la factura y alicuota IVA. "
        "Si hay bonificacion o descuento ya incluido en el precio de linea, devuelve el precio neto final de esa linea tal como queda en la factura. "
        "No sumes campos auxiliares, no agregues texto libre fuera del schema. "
        f"{hints}"
    )


def _purchase_invoice_input(command: AnalyzePurchaseInvoiceCommand) -> list[dict[str, str]]:
    content: list[dict[str, str]] = [{"type": "input_text", "text": _purchase_invoice_prompt(command)}]
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
