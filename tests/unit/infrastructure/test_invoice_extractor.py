"""Unit tests for purchase invoice extraction backends."""

from __future__ import annotations

from types import SimpleNamespace

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)
from sumampa_odoo_agent.infrastructure.extraction.service import (
    OpenAIPurchaseInvoiceExtractor,
    StubPurchaseInvoiceExtractor,
)


class _FakeResponses:
    def __init__(self, parsed: ExtractedPurchaseInvoiceDocument) -> None:
        self.kwargs: dict[str, object] | None = None
        self._parsed = parsed

    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(parsed=self._parsed)],
                )
            ]
        )


class _FakeClient:
    def __init__(self, parsed: ExtractedPurchaseInvoiceDocument) -> None:
        self.responses = _FakeResponses(parsed)


async def test_stub_purchase_invoice_extractor_returns_deterministic_payload() -> None:
    extractor = StubPurchaseInvoiceExtractor()

    result = await extractor.extract(
        AnalyzePurchaseInvoiceCommand(
            filename="factura-mates.jpg",
            content_type="image/jpeg",
            image_bytes=b"abc",
            supplier_name="Proveedor Norte",
        )
    )

    assert result.supplier_name == "Proveedor Norte"
    assert len(result.lines) >= 1


async def test_openai_purchase_invoice_extractor_uses_structured_parse() -> None:
    parsed = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "Acme SA",
            "invoice_number": "0001-00001234",
            "currency": "ARS",
            "lines": [
                {
                    "description": "Bombilla inox",
                    "quantity": 2,
                    "unit_price_gross": 100,
                    "vat_rate": 21,
                }
            ],
        }
    )
    fake_client = _FakeClient(parsed)
    extractor = OpenAIPurchaseInvoiceExtractor(
        model="gpt-5.4",
        api_key_env_var="OPENAI_API_KEY",
        client=fake_client,  # type: ignore[arg-type]
    )

    result = await extractor.extract(
        AnalyzePurchaseInvoiceCommand(
            filename="factura-acme.jpg",
            content_type="image/jpeg",
            image_bytes=b"image-bytes",
            supplier_name="Acme SA",
        )
    )

    assert result == parsed
    assert fake_client.responses.kwargs is not None
    assert fake_client.responses.kwargs["model"] == "gpt-5.4"
    assert fake_client.responses.kwargs["text_format"] is ExtractedPurchaseInvoiceDocument
