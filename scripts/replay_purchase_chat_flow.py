"""Replay a full local purchase flow against the seeded Odoo 19 stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from bootstrap_odoo_integration import (
    DEFAULT_ADMIN_LOGIN,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_BASE_URL,
    DEFAULT_DATABASE,
)

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ExtractedPurchaseInvoiceDocument,
    SearchJournalsQuery,
    SearchLocationsQuery,
    SearchPickingTypesQuery,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
)
from sumampa_odoo_agent.infrastructure.odoo.client import OdooJsonRpcClient
from sumampa_odoo_agent.infrastructure.purchase_chat.assistant import StubPurchaseChatAssistant
from sumampa_odoo_agent.infrastructure.purchase_chat.service import PurchaseChatService

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = (
    REPO_ROOT / "tests" / "integration" / "fixtures" / "purchase_invoice_extractions"
)


class SnapshotPurchaseInvoiceExtractor:
    def __init__(self, extracted: ExtractedPurchaseInvoiceDocument) -> None:
        self._extracted = extracted

    async def extract(
        self,
        command: AnalyzePurchaseInvoiceCommand,
    ) -> ExtractedPurchaseInvoiceDocument:
        del command
        return self._extracted


async def main_async(args: argparse.Namespace) -> int:
    extracted = _load_snapshot(_resolve_snapshot_path(args.fixture))
    if not args.reuse_invoice_number:
        extracted = extracted.model_copy(
            update={"invoice_number": _unique_invoice_number(extracted.invoice_number)}
        )

    client = OdooJsonRpcClient(
        base_url=os.environ.get("ORCHID_ODOO_BASE_URL", DEFAULT_BASE_URL),
        database=os.environ.get("ORCHID_ODOO_DATABASE", DEFAULT_DATABASE),
        username=os.environ.get("ORCHID_ODOO_USERNAME", DEFAULT_ADMIN_LOGIN),
        password=os.environ.get("ORCHID_ODOO_PASSWORD", DEFAULT_ADMIN_PASSWORD),
        timeout_seconds=float(os.environ.get("ORCHID_ODOO_TIMEOUT_SECONDS", "30")),
        invoice_extractor=SnapshotPurchaseInvoiceExtractor(extracted),
    )
    context = await _default_context(
        client=client,
        markup_percentage=args.markup,
        create_stock_receipt=args.create_stock_receipt,
    )
    service = PurchaseChatService(odoo=client, assistant=StubPurchaseChatAssistant())

    turns: list[dict[str, object]] = []
    response = await service.run_turn(
        PurchaseChatMessageCommand(
            message="te paso la factura",
            image_bytes=b"snapshot-backed-image",
            filename=f"{args.fixture}.jpeg",
            content_type="image/jpeg",
            context=context,
        )
    )
    turns.append(response.model_dump())

    if response.stage == "awaiting_resolution":
        resolution_message = _auto_resolution_message(
            response.proposal,
            allow_new_supplier=args.allow_new_supplier,
            allow_new_products=args.allow_new_products,
        )
        if not resolution_message:
            _print_turns(turns, as_json=args.json)
            print(
                "\nNo pude resolver automáticamente toda la factura. "
                "Probá con otro fixture seedado o habilitá --allow-new-products/--allow-new-supplier.",
                file=sys.stderr,
            )
            return 1
        response = await service.run_turn(
            PurchaseChatMessageCommand(
                session_id=response.session_id,
                message=resolution_message,
                context=context,
            )
        )
        turns.append(response.model_dump())
        if response.stage == "awaiting_resolution":
            if _proposal_has_new_items(response.proposal):
                response = await service.run_turn(
                    PurchaseChatMessageCommand(
                        session_id=response.session_id,
                        message="crear nuevos",
                        context=context,
                    )
                )
                turns.append(response.model_dump())
        if response.stage == "awaiting_resolution":
            response = await service.run_turn(
                PurchaseChatMessageCommand(
                    session_id=response.session_id,
                    message="si",
                    context=context,
                )
            )
            turns.append(response.model_dump())

    if response.stage != "awaiting_invoice_confirmation":
        _print_turns(turns, as_json=args.json)
        print(
            f"\nEl flujo no llegó a confirmación de factura. Etapa actual: {response.stage}",
            file=sys.stderr,
        )
        return 1

    response = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=response.session_id,
            message="si, cargar factura",
            context=context,
        )
    )
    turns.append(response.model_dump())
    if args.create_stock_receipt:
        if response.stage != "awaiting_stock_confirmation":
            _print_turns(turns, as_json=args.json)
            print(
                "\nLa factura no quedó cargada correctamente o no entró a la etapa de stock.",
                file=sys.stderr,
            )
            return 1
        response = await service.run_turn(
            PurchaseChatMessageCommand(
                session_id=response.session_id,
                message="si, generar recepción",
                context=context,
            )
        )
        turns.append(response.model_dump())

    if response.stage != "awaiting_price_confirmation":
        _print_turns(turns, as_json=args.json)
        print(
            "\nLa factura/recepción no quedó cargada correctamente. Revisá warnings y contexto local.",
            file=sys.stderr,
        )
        return 1

    final_message = "si, actualizar precios" if args.confirm_prices else "no, por ahora no"
    response = await service.run_turn(
        PurchaseChatMessageCommand(
            session_id=response.session_id,
            message=final_message,
            context=context,
        )
    )
    turns.append(response.model_dump())

    _print_turns(turns, as_json=args.json)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture",
        nargs="?",
        default="molinos_1",
        help="Nombre del snapshot bajo tests/integration/fixtures/purchase_invoice_extractions.",
    )
    parser.add_argument(
        "--create-stock-receipt",
        action="store_true",
        help="Pedir también la recepción de stock después de confirmar la factura.",
    )
    parser.add_argument(
        "--confirm-prices",
        action="store_true",
        help="Confirmar también la actualización de costos/precios al final.",
    )
    parser.add_argument(
        "--allow-new-products",
        action="store_true",
        help="Marcar como nuevos los productos sin match y, si hace falta, crearlos automáticamente.",
    )
    parser.add_argument(
        "--allow-new-supplier",
        action="store_true",
        help="Marcar como nuevo el proveedor si no aparece ninguno claro y crearlo automáticamente.",
    )
    parser.add_argument(
        "--reuse-invoice-number",
        action="store_true",
        help="No generar un número de factura único para el replay.",
    )
    parser.add_argument("--markup", type=float, default=30.0, help="Markup sugerido.")
    parser.add_argument("--json", action="store_true", help="Emitir el resultado en JSON.")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


async def _default_context(
    *,
    client: OdooJsonRpcClient,
    markup_percentage: float,
    create_stock_receipt: bool,
) -> PurchaseChatContext:
    journal = (await client.search_journals(SearchJournalsQuery(query="purchase", limit=1))).hits[0]
    context = PurchaseChatContext(
        journal_id=journal.id,
        markup_percentage=markup_percentage,
        create_stock_receipt=create_stock_receipt,
    )
    if not create_stock_receipt:
        return context

    picking = (await client.search_picking_types(SearchPickingTypesQuery(query="incoming", limit=1))).hits[0]
    vendors = (await client.search_locations(SearchLocationsQuery(query="Vendors", limit=1))).hits[0]
    stock = (await client.search_locations(SearchLocationsQuery(query="Stock", limit=1))).hits[0]
    context.picking_type_id = picking.id
    context.location_id = vendors.id
    context.location_dest_id = stock.id
    return context


def _load_snapshot(path: Path) -> ExtractedPurchaseInvoiceDocument:
    return ExtractedPurchaseInvoiceDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _resolve_snapshot_path(value: str) -> Path:
    raw_path = Path(value)
    if raw_path.exists():
        return raw_path.resolve()
    candidate = SNAPSHOTS_DIR / f"{value}.json"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"No encontré snapshot {value!r}. Probé {candidate} y la ruta literal."
    )


def _unique_invoice_number(value: str | None) -> str:
    base = (value or "SIN-NRO").replace(" ", "").replace("/", "-")
    return f"{base}-{uuid4().hex[:8]}"


def _auto_resolution_message(
    proposal,
    *,
    allow_new_supplier: bool,
    allow_new_products: bool,
) -> str | None:
    if proposal is None:
        return None
    commands: list[str] = []
    supplier_resolution = proposal.supplier_resolution
    if supplier_resolution is not None:
        if supplier_resolution.status == "candidate" and supplier_resolution.candidates:
            commands.append(f"proveedor {supplier_resolution.candidates[0].partner_id}")
        elif supplier_resolution.status == "missing":
            if not allow_new_supplier:
                return None
            commands.append("proveedor nuevo")

    for line in proposal.lines:
        resolution = line.product_resolution
        if resolution.status == "candidate" and resolution.candidates:
            commands.append(
                f"linea {line.line_number} producto {resolution.candidates[0].product_id}"
            )
        elif resolution.status == "missing":
            if not allow_new_products:
                return None
            commands.append(f"linea {line.line_number} nuevo")

    return " ".join(commands) if commands else "si"


def _proposal_has_new_items(proposal) -> bool:
    if proposal is None:
        return False
    if proposal.supplier_resolution is not None and proposal.supplier_resolution.status == "new":
        return True
    return any(line.product_resolution.status == "new" for line in proposal.lines)


def _print_turns(turns: list[dict[str, object]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(turns, indent=2, ensure_ascii=False))
        return

    for index, turn in enumerate(turns, start=1):
        print(f"\nTurno {index}")
        print(f"- etapa: {turn['stage']}")
        print(f"- mensaje: {turn['assistant_message']}")
        proposal = turn.get("proposal")
        if isinstance(proposal, dict):
            print(
                "- propuesta: "
                f"{proposal.get('document_type') or 'factura'} "
                f"{proposal.get('invoice_number') or 's/n'} "
                f"proveedor {proposal.get('supplier_name') or 's/d'} "
                f"total {proposal.get('totals', {}).get('total')}"
            )
        apply_result = turn.get("last_apply_result")
        if isinstance(apply_result, dict):
            models = ", ".join(operation["model"] for operation in apply_result.get("operations", []))
            print(
                "- apply: "
                f"applied={apply_result.get('applied')} "
                f"operations={models or 'sin operaciones'}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
