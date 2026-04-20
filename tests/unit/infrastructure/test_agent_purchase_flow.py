from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
)
from sumampa_odoo_agent.infrastructure.agent.service import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.infrastructure.db.session_store import InMemorySessionStore
from sumampa_odoo_agent.infrastructure.odoo.client import DryRunOdooClient


class _SnapshotExtractor:
    def __init__(self, extracted: ExtractedPurchaseInvoiceDocument) -> None:
        self._extracted = extracted

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        del command
        return self._extracted


class _FakeAgentSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def to_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id}

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> _FakeAgentSession:
        return cls(payload["session_id"])


class _FakeAgent:
    def __init__(self, tools, runner) -> None:  # type: ignore[no-untyped-def]
        self._tool_map = {tool.__name__: tool for tool in tools}
        self._runner = runner

    def create_session(self, *, session_id: str | None = None) -> _FakeAgentSession:
        assert session_id is not None
        return _FakeAgentSession(session_id)

    async def run(self, message: str, *, session: _FakeAgentSession) -> object:
        text = await self._runner(self._tool_map, message, session)
        return SimpleNamespace(text=text)


class _FakeChatClient:
    runner = None

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        del model, api_key, base_url

    def as_agent(self, *, name: str, instructions: str, tools, function_invocation_configuration):  # type: ignore[no-untyped-def]
        del name, instructions, function_invocation_configuration
        runner = type(self).runner
        assert runner is not None
        return _FakeAgent(tools, runner)


def _attachment_payload(filename: str = "factura.jpg") -> list[dict[str, str | None]]:
    return [
        {
            "filename": filename,
            "content_type": "image/jpeg",
            "content_base64": base64.b64encode(b"fake-image").decode("ascii"),
        }
    ]


@pytest.mark.asyncio
async def test_agent_purchase_tools_can_analyze_and_confirm_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "Sumampa SRL",
            "invoice_number": "TEST-0001",
            "invoice_date": "2026-04-19",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "Mate camionero",
                    "quantity": 2,
                    "unit_price_gross": 100.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    odoo = DryRunOdooClient(invoice_extractor=_SnapshotExtractor(extracted))
    store = InMemorySessionStore()

    async def _runner(tool_map, message: str, session: _FakeAgentSession) -> str:  # type: ignore[no-untyped-def]
        del message, session
        await tool_map["purchase_analyze_invoice"]()
        await tool_map["purchase_confirm_invoice"](journal_id=301)
        return "Factura cargada."

    _FakeChatClient.runner = _runner
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_openai_chat_client",
        lambda: _FakeChatClient,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_agent_type",
        lambda: _FakeAgent,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_agent_session_type",
        lambda: _FakeAgentSession,
    )

    service = MicrosoftAgentFrameworkOpenAIService(
        model="gpt-5.4-mini",
        api_key_env_var="OPENAI_API_KEY",
        odoo=odoo,
        session_store=store,
    )

    result = await service.run(
        prompt="Procesá la factura",
        context={
            "purchase_workflow": {
                "context": {"supplier_name": "Sumampa SRL", "markup_percentage": 30.0},
                "attachments": _attachment_payload(),
            }
        },
        session_id="purchase-session-1",
    )

    assert result["session_id"] == "purchase-session-1"
    assert result["text"] == "Factura cargada."
    purchase_flow = result["purchase_flow"]
    assert purchase_flow["stage"] == "awaiting_price_confirmation"
    assert purchase_flow["proposal"]["invoice_number"] == "TEST-0001"
    assert purchase_flow["last_apply_result"]["applied"] is True


@pytest.mark.asyncio
async def test_agent_purchase_tools_can_create_missing_product_through_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "Sumampa SRL",
            "invoice_number": "TEST-0002",
            "invoice_date": "2026-04-19",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PRODUCTO NUEVO SIN MATCH",
                    "quantity": 1,
                    "unit_price_gross": 100.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    monkeypatch.setattr(DryRunOdooClient, "_products", [])
    odoo = DryRunOdooClient(invoice_extractor=_SnapshotExtractor(extracted))
    store = InMemorySessionStore()

    async def _runner(tool_map, message: str, session: _FakeAgentSession) -> str:  # type: ignore[no-untyped-def]
        del message, session
        await tool_map["purchase_analyze_invoice"]()
        await tool_map["purchase_review_resolution"](
            lines=[{"line_number": 1, "action": "mark_new"}]
        )
        await tool_map["purchase_review_resolution"](
            lines=[{"line_number": 1, "action": "create_missing"}]
        )
        return "Producto creado y listo para confirmar."

    _FakeChatClient.runner = _runner
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_openai_chat_client",
        lambda: _FakeChatClient,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_agent_type",
        lambda: _FakeAgent,
    )
    monkeypatch.setattr(
        "sumampa_odoo_agent.infrastructure.agent.service._load_agent_session_type",
        lambda: _FakeAgentSession,
    )

    service = MicrosoftAgentFrameworkOpenAIService(
        model="gpt-5.4-mini",
        api_key_env_var="OPENAI_API_KEY",
        odoo=odoo,
        session_store=store,
    )

    result = await service.run(
        prompt="Analizá y resolvé el producto nuevo",
        context={
            "purchase_workflow": {
                "context": {"supplier_name": "Sumampa SRL"},
                "attachments": _attachment_payload("nuevo.jpg"),
            }
        },
        session_id="purchase-session-2",
    )

    purchase_flow = result["purchase_flow"]
    assert purchase_flow["stage"] == "awaiting_invoice_confirmation"
    assert purchase_flow["proposal"]["lines"][0]["product_resolution"]["selected_product_id"] is not None
