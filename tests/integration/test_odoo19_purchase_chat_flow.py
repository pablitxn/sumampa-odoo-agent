"""Full local purchase chat flow against seeded Odoo 19."""

from __future__ import annotations

import json
import xmlrpc.client
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
    InvoiceAttachment,
    SearchJournalsQuery,
    SearchLocationsQuery,
    SearchPickingTypesQuery,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
    PurchaseChatPlannerDecision,
)
from sumampa_odoo_agent.infrastructure.odoo.client import OdooJsonRpcClient
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import (
    OpenAIPurchaseChatAssistant,
)
from sumampa_odoo_agent.infrastructure.purchase_chat.service import PurchaseChatService


class SnapshotPurchaseInvoiceExtractor:
    def __init__(self, extracted: ExtractedPurchaseInvoiceDocument) -> None:
        self._extracted = extracted

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        del command
        return self._extracted


class _FakePlanningResponses:
    async def parse(self, **kwargs: object) -> object:
        payload = kwargs["input"][1]["content"][0]["text"]  # type: ignore[index]
        stage, user_message = _parse_prompt_payload(str(payload))
        decision = _decision_for(stage=stage, user_message=user_message)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(parsed=decision)],
                )
            ]
        )


class _FakePlanningClient:
    def __init__(self) -> None:
        self.responses = _FakePlanningResponses()


def _test_assistant() -> OpenAIPurchaseChatAssistant:
    return OpenAIPurchaseChatAssistant(
        model="gpt-5.4",
        api_key_env_var="OPENAI_API_KEY",
        client=_FakePlanningClient(),  # type: ignore[arg-type]
    )


def _parse_prompt_payload(payload: str) -> tuple[str, str]:
    stage = "awaiting_invoice"
    user_message = ""
    for line in payload.splitlines():
        if line.startswith("Etapa actual: "):
            stage = line.removeprefix("Etapa actual: ").strip()
        if line.startswith("Mensaje usuario: "):
            user_message = line.removeprefix("Mensaje usuario: ").strip()
    return stage, user_message


def _decision_for(*, stage: str, user_message: str) -> PurchaseChatPlannerDecision:
    normalized = " ".join(user_message.casefold().replace(",", " ").replace(".", " ").split())
    if stage == "awaiting_invoice_confirmation" and any(
        token in normalized for token in ("si", "sí", "confirmo", "cargar factura", "dale")
    ):
        return PurchaseChatPlannerDecision(
            intent="confirm_invoice",
            assistant_message="Perfecto. Confirmo que querés cargar la factura.",
        )
    if stage == "awaiting_stock_confirmation" and any(
        token in normalized for token in ("si", "sí", "generar recepción", "dale")
    ):
        return PurchaseChatPlannerDecision(
            intent="confirm_stock",
            assistant_message="Perfecto. Avanzo con la recepción de stock.",
        )
    if stage == "awaiting_price_confirmation" and any(
        token in normalized for token in ("si", "sí", "actualizar precios", "dale")
    ):
        return PurchaseChatPlannerDecision(
            intent="confirm_prices",
            assistant_message="Perfecto. Avanzo con la actualización de precios.",
        )
    if "no" in normalized:
        intent = {
            "awaiting_invoice_confirmation": "reject_invoice",
            "awaiting_stock_confirmation": "reject_stock",
            "awaiting_price_confirmation": "reject_prices",
        }.get(stage, "other")
        return PurchaseChatPlannerDecision(
            intent=intent, assistant_message="Listo. No avanzo con ese paso por ahora."
        )
    return PurchaseChatPlannerDecision(
        intent="other" if stage != "awaiting_invoice" else "await_invoice",
        assistant_message="Contame qué necesitás y adjuntá la factura cuando quieras.",
    )


def _load_snapshot(path: Path) -> ExtractedPurchaseInvoiceDocument:
    return ExtractedPurchaseInvoiceDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _object_proxy(env: dict[str, str]) -> tuple[int, xmlrpc.client.ServerProxy]:
    common_proxy = xmlrpc.client.ServerProxy(
        f"{env['ORCHID_ODOO_BASE_URL']}/xmlrpc/2/common",
        allow_none=True,
    )
    uid = common_proxy.authenticate(
        env["ORCHID_ODOO_DATABASE"],
        env["ORCHID_ODOO_USERNAME"],
        env["ORCHID_ODOO_PASSWORD"],
        {},
    )
    assert isinstance(uid, int) and uid > 0
    object_proxy = xmlrpc.client.ServerProxy(
        f"{env['ORCHID_ODOO_BASE_URL']}/xmlrpc/2/object",
        allow_none=True,
    )
    return uid, object_proxy


def _read_one(
    *,
    env: dict[str, str],
    model: str,
    record_id: int,
    fields: list[str],
) -> dict[str, object]:
    uid, object_proxy = _object_proxy(env)
    rows = object_proxy.execute_kw(
        env["ORCHID_ODOO_DATABASE"],
        uid,
        env["ORCHID_ODOO_PASSWORD"],
        model,
        "read",
        [[record_id]],
        {"fields": fields},
    )
    assert rows
    return rows[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_flow_can_create_bill_receipt_and_price_updates_in_local_odoo(
    odoo19_env: dict[str, str],
) -> None:
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M. PALACIOS",
            "supplier_vat": "20-17978615-1",
            "invoice_number": f"TEST-{uuid4().hex[:10]}",
            "invoice_date": "13/4/2026",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PURE DE TOMATE ARCOR X 520 GR.",
                    "quantity": 2,
                    "unit_price_gross": 770.0,
                    "vat_rate": 21.0,
                },
                {
                    "description": "MENTA CRISTAL X 810 GR.",
                    "quantity": 1,
                    "unit_price_gross": 9196.0,
                    "vat_rate": 21.0,
                },
            ],
        }
    )
    client = OdooJsonRpcClient(
        base_url=odoo19_env["ORCHID_ODOO_BASE_URL"],
        database=odoo19_env["ORCHID_ODOO_DATABASE"],
        username=odoo19_env["ORCHID_ODOO_USERNAME"],
        password=odoo19_env["ORCHID_ODOO_PASSWORD"],
        timeout_seconds=float(odoo19_env["ORCHID_ODOO_TIMEOUT_SECONDS"]),
        invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
    )
    service = PurchaseChatService(
        odoo=client,
        assistant=_test_assistant(),
    )

    purchase_journal = (await client.search_journals(SearchJournalsQuery(query="purchase", limit=1))).hits[0]
    incoming_picking = (
        await client.search_picking_types(SearchPickingTypesQuery(query="incoming", limit=1))
    ).hits[0]
    vendors_location = (
        await client.search_locations(SearchLocationsQuery(query="Vendors", limit=1))
    ).hits[0]
    stock_location = (
        await client.search_locations(SearchLocationsQuery(query="Stock", limit=1))
    ).hits[0]

    context = PurchaseChatContext(
        journal_id=purchase_journal.id,
        picking_type_id=incoming_picking.id,
        location_id=vendors_location.id,
        location_dest_id=stock_location.id,
        create_stock_receipt=True,
        markup_percentage=30.0,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="arcor_1.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"snapshot-backed-image",
                )
            ],
            context=context,
        )
    )

    assert uploaded.stage == "awaiting_invoice_confirmation"
    assert uploaded.proposal is not None
    assert uploaded.proposal.invoice_date == "2026-04-13"
    assert uploaded.proposal.supplier_resolution is not None
    assert uploaded.proposal.supplier_resolution.selected_partner_id is not None

    billed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, cargar factura",
            context=PurchaseChatContext(
                journal_id=purchase_journal.id,
                picking_type_id=incoming_picking.id,
                location_id=vendors_location.id,
                location_dest_id=stock_location.id,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )

    assert billed.stage == "awaiting_stock_confirmation"
    assert billed.last_apply_result is not None
    assert billed.last_apply_result.applied is True
    assert any(
        operation.model == "account.move" for operation in billed.last_apply_result.operations
    )
    assert all(
        operation.model != "stock.picking" for operation in billed.last_apply_result.operations
    )

    vendor_bill_operation = next(
        operation for operation in billed.last_apply_result.operations if operation.model == "account.move"
    )

    vendor_bill = _read_one(
        env=odoo19_env,
        model="account.move",
        record_id=int(vendor_bill_operation.record_id),
        fields=["ref", "invoice_date", "partner_id", "move_type"],
    )

    assert vendor_bill["ref"] == extracted.invoice_number
    assert vendor_bill["invoice_date"] == "2026-04-13"
    assert vendor_bill["move_type"] == "in_invoice"

    stocked = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, generar recepción",
            context=PurchaseChatContext(
                journal_id=purchase_journal.id,
                picking_type_id=incoming_picking.id,
                location_id=vendors_location.id,
                location_dest_id=stock_location.id,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )

    assert stocked.stage == "awaiting_price_confirmation"
    assert stocked.last_apply_result is not None
    assert stocked.last_apply_result.applied is True
    assert any(
        operation.model == "stock.picking" for operation in stocked.last_apply_result.operations
    )

    receipt_operation = next(
        operation for operation in stocked.last_apply_result.operations if operation.model == "stock.picking"
    )
    stock_receipt = _read_one(
        env=odoo19_env,
        model="stock.picking",
        record_id=int(receipt_operation.record_id),
        fields=["origin", "partner_id", "picking_type_id", "location_id", "location_dest_id"],
    )
    assert stock_receipt["origin"] == extracted.invoice_number

    priced = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, actualizar precios",
            context=PurchaseChatContext(
                journal_id=purchase_journal.id,
                create_stock_receipt=True,
                markup_percentage=30.0,
            ),
        )
    )

    assert priced.stage == "completed"
    assert priced.last_apply_result is not None
    assert priced.last_apply_result.applied is True
    product_updates = [
        operation
        for operation in priced.last_apply_result.operations
        if operation.model == "product.template"
    ]
    assert product_updates

    updated_product = _read_one(
        env=odoo19_env,
        model="product.template",
        record_id=int(product_updates[0].record_id),
        fields=["list_price", "standard_price"],
    )
    assert float(updated_product["list_price"]) > 0
    assert float(updated_product["standard_price"]) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_blocks_duplicate_vendor_bill_in_local_odoo(
    odoo19_env: dict[str, str],
) -> None:
    invoice_number = f"TEST-{uuid4().hex[:10]}"
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": "JULIO M. PALACIOS",
            "supplier_vat": "20-17978615-1",
            "invoice_number": invoice_number,
            "invoice_date": "13/4/2026",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": "PURE DE TOMATE ARCOR X 520 GR.",
                    "quantity": 1,
                    "unit_price_gross": 770.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    client = OdooJsonRpcClient(
        base_url=odoo19_env["ORCHID_ODOO_BASE_URL"],
        database=odoo19_env["ORCHID_ODOO_DATABASE"],
        username=odoo19_env["ORCHID_ODOO_USERNAME"],
        password=odoo19_env["ORCHID_ODOO_PASSWORD"],
        timeout_seconds=float(odoo19_env["ORCHID_ODOO_TIMEOUT_SECONDS"]),
        invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
    )
    service = PurchaseChatService(odoo=client, assistant=_test_assistant())
    purchase_journal = (await client.search_journals(SearchJournalsQuery(query="purchase", limit=1))).hits[0]
    context = PurchaseChatContext(
        journal_id=purchase_journal.id,
        markup_percentage=30.0,
    )

    first_upload = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="duplicate-1.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"snapshot-backed-image",
                )
            ],
            context=context,
        )
    )
    assert first_upload.stage == "awaiting_invoice_confirmation"

    first_bill = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=first_upload.session_id,
            message="si, cargar factura",
            context=context,
        )
    )
    assert first_bill.stage == "awaiting_price_confirmation"
    assert first_bill.last_apply_result is not None
    assert first_bill.last_apply_result.applied is True

    second_upload = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la misma factura",
            attachments=[
                InvoiceAttachment(
                    filename="duplicate-2.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"snapshot-backed-image",
                )
            ],
            context=context,
        )
    )
    assert second_upload.stage == "awaiting_invoice_confirmation"

    second_bill = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=second_upload.session_id,
            message="si, cargar factura",
            context=context,
        )
    )
    assert second_bill.stage == "awaiting_invoice_confirmation"
    assert second_bill.last_apply_result is not None
    assert second_bill.last_apply_result.applied is False
    assert any(
        "ya existe una factura de compra similar" in warning.casefold()
        or "mismo numero/referencia" in warning.casefold()
        for warning in second_bill.last_apply_result.warnings
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_purchase_chat_can_create_new_supplier_and_product_in_local_odoo(
    odoo19_env: dict[str, str],
) -> None:
    suffix = uuid4().hex[:8]
    extracted = ExtractedPurchaseInvoiceDocument.model_validate(
        {
            "supplier_name": f"PROVEEDOR NUEVO {suffix}",
            "supplier_vat": f"3071{suffix[:4]}5678",
            "invoice_number": f"NEW-{suffix}",
            "invoice_date": "2026-04-18",
            "document_type": "Factura A",
            "currency": "ARS",
            "lines": [
                {
                    "description": f"PRODUCTO NUEVO CHAT {suffix}",
                    "quantity": 2,
                    "unit_price_gross": 1210.0,
                    "vat_rate": 21.0,
                }
            ],
        }
    )
    client = OdooJsonRpcClient(
        base_url=odoo19_env["ORCHID_ODOO_BASE_URL"],
        database=odoo19_env["ORCHID_ODOO_DATABASE"],
        username=odoo19_env["ORCHID_ODOO_USERNAME"],
        password=odoo19_env["ORCHID_ODOO_PASSWORD"],
        timeout_seconds=float(odoo19_env["ORCHID_ODOO_TIMEOUT_SECONDS"]),
        invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
    )
    service = PurchaseChatService(odoo=client, assistant=_test_assistant())
    purchase_journal = (await client.search_journals(SearchJournalsQuery(query="purchase", limit=1))).hits[0]
    context = PurchaseChatContext(
        journal_id=purchase_journal.id,
        markup_percentage=30.0,
    )

    uploaded = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            attachments=[
                InvoiceAttachment(
                    filename="create-new.jpeg",
                    content_type="image/jpeg",
                    content_bytes=b"snapshot-backed-image",
                )
            ],
            context=context,
        )
    )
    assert uploaded.stage == "awaiting_resolution"

    marked_new = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="proveedor nuevo linea 1 nuevo",
            context=context,
        )
    )
    assert marked_new.stage == "awaiting_resolution"

    created = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="crear nuevos",
            context=context,
        )
    )
    assert created.stage == "awaiting_invoice_confirmation"
    assert created.proposal is not None
    assert created.proposal.supplier_resolution is not None
    supplier_id = int(created.proposal.supplier_resolution.selected_partner_id or 0)
    product_id = int(created.proposal.lines[0].product_resolution.selected_product_id or 0)
    assert supplier_id > 0
    assert product_id > 0

    supplier = _read_one(
        env=odoo19_env,
        model="res.partner",
        record_id=supplier_id,
        fields=["name", "vat", "supplier_rank"],
    )
    product = _read_one(
        env=odoo19_env,
        model="product.template",
        record_id=product_id,
        fields=["name", "standard_price", "list_price"],
    )
    assert supplier["name"] == extracted.supplier_name
    assert supplier["vat"] == extracted.supplier_vat
    assert float(supplier["supplier_rank"]) >= 1
    assert product["name"] == extracted.lines[0].description
    assert float(product["standard_price"]) > 0
    assert float(product["list_price"]) > 0

    billed = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=uploaded.session_id,
            message="si, cargar factura",
            context=context,
        )
    )
    assert billed.stage == "awaiting_price_confirmation"
    assert billed.last_apply_result is not None
    assert billed.last_apply_result.applied is True
