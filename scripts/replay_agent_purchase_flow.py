"""Replay a full local purchase flow against Odoo through the agent."""

from __future__ import annotations

import argparse
import asyncio
import base64
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
from sumampa_odoo_agent.application.requests.purchase_workflow import PurchaseWorkflowContext
from sumampa_odoo_agent.infrastructure.agent.service import (
    MicrosoftAgentFrameworkOpenAIService,
)
from sumampa_odoo_agent.infrastructure.db.session_store import InMemorySessionStore
from sumampa_odoo_agent.infrastructure.odoo.client import OdooJsonRpcClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = (
    REPO_ROOT / "tests" / "integration" / "fixtures" / "purchase_invoice_extractions"
)
DEFAULT_AGENT_MODEL = "gpt-5.4-mini"
DEFAULT_AGENT_API_KEY_ENV = "OPENAI_API_KEY"


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
    workflow_context = await _default_context(
        client=client,
        markup_percentage=args.markup,
        create_stock_receipt=args.create_stock_receipt,
    )
    agent = MicrosoftAgentFrameworkOpenAIService(
        model=os.environ.get("ORCHID_AGENT_MODEL", DEFAULT_AGENT_MODEL),
        api_key_env_var=DEFAULT_AGENT_API_KEY_ENV,
        base_url=os.environ.get("ORCHID_AGENT_BASE_URL"),
        odoo=client,
        session_store=InMemorySessionStore(),
    )

    turns: list[dict[str, object]] = []
    session_id = str(uuid4())
    response = await _run_turn(
        agent=agent,
        session_id=session_id,
        prompt="Analizá la factura adjunta y avanzá con el flujo de compra.",
        context=workflow_context,
        attach_invoice=True,
        fixture_name=args.fixture,
    )
    turns.append(response)

    if response["stage"] == "awaiting_resolution":
        resolution_message = _auto_resolution_message(
            response.get("proposal"),
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
        response = await _run_turn(
            agent=agent,
            session_id=session_id,
            prompt=resolution_message,
            context=workflow_context,
        )
        turns.append(response)
        if response["stage"] == "awaiting_resolution" and _proposal_has_new_items(response.get("proposal")):
            response = await _run_turn(
                agent=agent,
                session_id=session_id,
                prompt="Creá en Odoo todos los faltantes marcados como nuevos.",
                context=workflow_context,
            )
            turns.append(response)
        if response["stage"] == "awaiting_resolution":
            response = await _run_turn(
                agent=agent,
                session_id=session_id,
                prompt="Aceptá la resolución actual y seguí.",
                context=workflow_context,
            )
            turns.append(response)

    if response["stage"] != "awaiting_invoice_confirmation":
        _print_turns(turns, as_json=args.json)
        print(
            f"\nEl flujo no llegó a confirmación de factura. Etapa actual: {response['stage']}",
            file=sys.stderr,
        )
        return 1

    response = await _run_turn(
        agent=agent,
        session_id=session_id,
        prompt="Confirmá la factura con el contexto actual.",
        context=workflow_context,
    )
    turns.append(response)
    if args.create_stock_receipt:
        if response["stage"] != "awaiting_stock_confirmation":
            _print_turns(turns, as_json=args.json)
            print(
                "\nLa factura no quedó cargada correctamente o no entró a la etapa de stock.",
                file=sys.stderr,
            )
            return 1
        response = await _run_turn(
            agent=agent,
            session_id=session_id,
            prompt="Generá la recepción de stock.",
            context=workflow_context,
        )
        turns.append(response)

    if response["stage"] != "awaiting_price_confirmation":
        _print_turns(turns, as_json=args.json)
        print(
            "\nLa factura/recepción no quedó cargada correctamente. Revisá warnings y contexto local.",
            file=sys.stderr,
        )
        return 1

    final_message = (
        "Actualizá los precios y costos con esta factura."
        if args.confirm_prices
        else "No actualices los precios por ahora."
    )
    response = await _run_turn(
        agent=agent,
        session_id=session_id,
        prompt=final_message,
        context=workflow_context,
    )
    turns.append(response)

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
) -> PurchaseWorkflowContext:
    journal = (await client.search_journals(SearchJournalsQuery(query="purchase", limit=1))).hits[0]
    context = PurchaseWorkflowContext(
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


async def _run_turn(
    *,
    agent: MicrosoftAgentFrameworkOpenAIService,
    session_id: str,
    prompt: str,
    context: PurchaseWorkflowContext,
    attach_invoice: bool = False,
    fixture_name: str = "snapshot",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "purchase_workflow": {
            "context": context.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        }
    }
    if attach_invoice:
        payload["purchase_workflow"]["attachments"] = [  # type: ignore[index]
            {
                "filename": f"{fixture_name}.jpeg",
                "content_type": "image/jpeg",
                "content_base64": base64.b64encode(b"snapshot-backed-image").decode("ascii"),
            }
        ]

    result = await agent.run(
        prompt=prompt,
        context=payload,
        session_id=session_id,
    )
    purchase_flow = result.get("purchase_flow") or {}
    if not isinstance(purchase_flow, dict):
        purchase_flow = {}
    return {
        "session_id": str(result.get("session_id") or session_id),
        "stage": str(purchase_flow.get("stage") or "awaiting_invoice"),
        "assistant_message": str(result.get("text") or ""),
        "proposal": purchase_flow.get("proposal"),
        "last_apply_result": purchase_flow.get("last_apply_result"),
    }


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
    proposal: object,
    *,
    allow_new_supplier: bool,
    allow_new_products: bool,
) -> str | None:
    if not isinstance(proposal, dict):
        return None

    commands: list[str] = []
    supplier_resolution = proposal.get("supplier_resolution")
    if isinstance(supplier_resolution, dict):
        status = supplier_resolution.get("status")
        candidates = supplier_resolution.get("candidates") or []
        if status == "candidate" and candidates:
            candidate = candidates[0]
            if isinstance(candidate, dict) and candidate.get("partner_id") is not None:
                commands.append(
                    f"Elegí el proveedor candidato {candidate['partner_id']}."
                )
        elif status == "missing":
            if not allow_new_supplier:
                return None
            commands.append("Marcá el proveedor como nuevo.")

    for line in proposal.get("lines") or []:
        if not isinstance(line, dict):
            continue
        resolution = line.get("product_resolution")
        if not isinstance(resolution, dict):
            continue
        line_number = line.get("line_number")
        candidates = resolution.get("candidates") or []
        if resolution.get("status") == "candidate" and candidates:
            candidate = candidates[0]
            if (
                isinstance(candidate, dict)
                and candidate.get("product_id") is not None
                and line_number is not None
            ):
                commands.append(
                    f"Para la línea {line_number}, elegí el producto candidato {candidate['product_id']}."
                )
        elif resolution.get("status") == "missing":
            if not allow_new_products:
                return None
            commands.append(f"Marcá la línea {line_number} como producto nuevo.")

    if commands:
        return " ".join(commands)
    return "Aceptá la resolución actual y seguí."


def _proposal_has_new_items(proposal: object) -> bool:
    if not isinstance(proposal, dict):
        return False
    supplier_resolution = proposal.get("supplier_resolution")
    if isinstance(supplier_resolution, dict) and supplier_resolution.get("status") == "new":
        return True
    for line in proposal.get("lines") or []:
        if isinstance(line, dict):
            resolution = line.get("product_resolution")
            if isinstance(resolution, dict) and resolution.get("status") == "new":
                return True
    return False


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
