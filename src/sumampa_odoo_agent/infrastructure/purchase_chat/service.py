"""Conversational purchase invoice workflow service."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from uuid import uuid4

from sumampa_odoo_agent.application.requests.odoo import (
    AnalyzePurchaseInvoiceCommand,
    ApplyPurchaseInvoiceProposalCommand,
    ApplyPurchaseInvoiceProposalResult,
    CreatePartnerCommand,
    CreateProductCommand,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_chat import (
    PurchaseChatContext,
    PurchaseChatMessageCommand,
    PurchaseChatResponse,
)
from sumampa_odoo_agent.domain.ports.odoo_port import OdooPort
from sumampa_odoo_agent.domain.ports.purchase_chat_assistant_port import (
    PurchaseChatAssistantPort,
)

SUPPLIER_ID_RE = re.compile(r"\bproveedor\s+(\d+)\b")
SUPPLIER_NEW_RE = re.compile(r"\bproveedor\s+nuevo\b")
SUPPLIER_CREATE_RE = re.compile(r"\b(?:crear|alta)\s+proveedor\b")
CREATE_NEW_ITEMS_RE = re.compile(r"\b(?:crear|alta)\s+nuevos\b")
LINE_PRODUCT_RE = re.compile(r"\blinea\s+(\d+)\s+producto\s+(\d+)\b")
LINE_NEW_RE = re.compile(r"\blinea\s+(\d+)\s+nuevo\b")
LINE_CREATE_RE = re.compile(r"\blinea\s+(\d+)\s+crear\b")
CREATE_LINE_RE = re.compile(r"\bcrear\s+linea\s+(\d+)\b")


@dataclass(slots=True)
class PurchaseChatSession:
    session_id: str
    stage: str = "awaiting_invoice"
    proposal: PurchaseInvoiceProposalResult | None = None
    bill_result: ApplyPurchaseInvoiceProposalResult | None = None
    stock_result: ApplyPurchaseInvoiceProposalResult | None = None
    price_result: ApplyPurchaseInvoiceProposalResult | None = None
    context: PurchaseChatContext = field(
        default_factory=lambda: PurchaseChatContext(
            create_stock_receipt=False,
            markup_percentage=30.0,
        )
    )


class PurchaseChatService:
    def __init__(self, odoo: OdooPort, assistant: PurchaseChatAssistantPort) -> None:
        self._odoo = odoo
        self._assistant = assistant
        self._sessions: dict[str, PurchaseChatSession] = {}

    async def run_turn(self, command: PurchaseChatMessageCommand) -> PurchaseChatResponse:
        session = self._get_session(command.session_id)
        session.context = _merge_context(session.context, command.context)
        message = command.message.strip()

        if command.image_bytes:
            session.proposal = await self._odoo.analyze_purchase_invoice(
                AnalyzePurchaseInvoiceCommand(
                    filename=command.filename or "factura.jpg",
                    content_type=command.content_type,
                    image_bytes=command.image_bytes,
                    supplier_name=session.context.supplier_name,
                    supplier_vat=session.context.supplier_vat,
                    markup_percentage=session.context.markup_percentage or 30.0,
                )
            )
            session.bill_result = None
            session.stock_result = None
            session.price_result = None
            _sync_context_from_proposal(session)
            if _proposal_needs_resolution(session.proposal):
                session.stage = "awaiting_resolution"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_resolution",
                    assistant_message=_resolution_message(session.proposal),
                    proposal=session.proposal,
                )
            session.stage = "awaiting_invoice_confirmation"
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice_confirmation",
                assistant_message=_proposal_message(session.proposal),
                proposal=session.proposal,
            )

        if session.stage == "awaiting_invoice":
            decision = await self._assistant.plan(
                stage=session.stage,
                proposal_summary=None,
                user_message=message,
            )
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice",
                assistant_message=decision.assistant_message,
            )

        if session.proposal is None:
            session.stage = "awaiting_invoice"
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice",
                assistant_message="Perdí el contexto de la factura. Reenviame la imagen y retomamos.",
            )

        if session.stage == "awaiting_resolution":
            return await self._handle_resolution_turn(session, message)

        decision = await self._assistant.plan(
            stage=session.stage,
            proposal_summary=_proposal_summary(session.proposal),
            user_message=message,
        )

        if session.stage == "awaiting_invoice_confirmation":
            if decision.intent in {"reject_invoice", "reset"}:
                session.stage = "awaiting_invoice"
                session.proposal = None
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_invoice",
                    assistant_message=decision.assistant_message,
                )
            if decision.intent == "confirm_invoice":
                try:
                    bill_result = await self._odoo.apply_purchase_invoice_proposal(
                        ApplyPurchaseInvoiceProposalCommand(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            create_vendor_bill=True,
                            update_products=False,
                            learn_resolutions=True,
                            create_stock_receipt=False,
                            picking_type_id=session.context.picking_type_id,
                            location_id=session.context.location_id,
                            location_dest_id=session.context.location_dest_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_invoice_confirmation",
                        assistant_message=(
                            "No pude cargar la factura en Odoo todavía.\n"
                            f"{_odoo_runtime_error_message(exc)}"
                        ),
                        proposal=session.proposal,
                    )
                if not bill_result.applied:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_invoice_confirmation",
                        assistant_message=_apply_blocked_message(
                            prefix="Todavía no pude cargar la factura en Odoo.",
                            result=bill_result,
                            next_step=(
                                "Revisá los warnings, ajustá el contexto si hace falta y "
                                "después volvé a confirmarme la factura."
                            ),
                        ),
                        proposal=session.proposal,
                        last_apply_result=bill_result,
                    )
                session.bill_result = bill_result
                if session.context.create_stock_receipt:
                    session.stage = "awaiting_stock_confirmation"
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_stock_confirmation",
                        assistant_message=_bill_applied_message(
                            proposal=session.proposal,
                            result=bill_result,
                            prefix=decision.assistant_message,
                            create_stock_receipt=True,
                        ),
                        proposal=session.proposal,
                        last_apply_result=bill_result,
                    )
                session.stage = "awaiting_price_confirmation"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_price_confirmation",
                    assistant_message=_bill_applied_message(
                        proposal=session.proposal,
                        result=bill_result,
                        prefix=decision.assistant_message,
                        create_stock_receipt=False,
                    ),
                    proposal=session.proposal,
                    last_apply_result=bill_result,
                )
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
            )

        if session.stage == "awaiting_stock_confirmation":
            if decision.intent == "confirm_stock":
                try:
                    stock_result = await self._odoo.apply_purchase_invoice_proposal(
                        ApplyPurchaseInvoiceProposalCommand(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            create_vendor_bill=False,
                            update_products=False,
                            learn_resolutions=False,
                            create_stock_receipt=True,
                            picking_type_id=session.context.picking_type_id,
                            location_id=session.context.location_id,
                            location_dest_id=session.context.location_dest_id,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_stock_confirmation",
                        assistant_message=(
                            "No pude generar la recepción de stock en Odoo todavía.\n"
                            f"{_odoo_runtime_error_message(exc)}"
                        ),
                        proposal=session.proposal,
                        last_apply_result=session.bill_result,
                    )
                if not stock_result.applied:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_stock_confirmation",
                        assistant_message=_apply_blocked_message(
                            prefix="Todavía no pude generar la recepción de stock.",
                            result=stock_result,
                            next_step=(
                                "Revisá los warnings, ajustá el contexto si hace falta y "
                                "después volvé a confirmarme la recepción."
                            ),
                        ),
                        proposal=session.proposal,
                        last_apply_result=stock_result,
                    )
                session.stock_result = stock_result
                session.stage = "awaiting_price_confirmation"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_price_confirmation",
                    assistant_message=_stock_applied_message(
                        result=stock_result,
                        prefix=decision.assistant_message,
                    ),
                    proposal=session.proposal,
                    last_apply_result=stock_result,
                )
            if decision.intent in {"reject_stock", "reset"}:
                session.stage = "awaiting_price_confirmation"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_price_confirmation",
                    assistant_message=(
                        f"{decision.assistant_message}\n"
                        "Ahora decime si querés actualizar los precios de productos usando el markup propuesto."
                    ),
                    proposal=session.proposal,
                    last_apply_result=session.bill_result,
                )
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_stock_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
                last_apply_result=session.bill_result,
            )

        if session.stage == "awaiting_price_confirmation":
            if decision.intent == "confirm_prices":
                try:
                    price_result = await self._odoo.apply_purchase_invoice_proposal(
                        ApplyPurchaseInvoiceProposalCommand(
                            supplier_id=session.context.supplier_id,
                            journal_id=session.context.journal_id,
                            create_vendor_bill=False,
                            update_products=True,
                            learn_resolutions=False,
                            create_stock_receipt=False,
                            proposal=session.proposal,
                        )
                    )
                except RuntimeError as exc:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_price_confirmation",
                        assistant_message=(
                            "No pude actualizar los precios en Odoo todavía.\n"
                            f"{_odoo_runtime_error_message(exc)}"
                        ),
                        proposal=session.proposal,
                        last_apply_result=session.bill_result,
                    )
                if not price_result.applied:
                    return PurchaseChatResponse(
                        session_id=session.session_id,
                        stage="awaiting_price_confirmation",
                        assistant_message=_apply_blocked_message(
                            prefix="Todavía no pude actualizar los precios.",
                            result=price_result,
                            next_step=(
                                "Revisá los warnings y, si sigue teniendo sentido, "
                                "confirmame de nuevo la actualización."
                            ),
                        ),
                        proposal=session.proposal,
                        last_apply_result=price_result,
                    )
                session.price_result = price_result
                session.stage = "completed"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="completed",
                    assistant_message=_price_applied_message(price_result, decision.assistant_message),
                    proposal=session.proposal,
                    last_apply_result=price_result,
                )
            if decision.intent in {"reject_prices", "reset"}:
                session.stage = "completed"
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="completed",
                    assistant_message=decision.assistant_message,
                    proposal=session.proposal,
                    last_apply_result=session.stock_result or session.bill_result,
                )
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_price_confirmation",
                assistant_message=decision.assistant_message,
                proposal=session.proposal,
                last_apply_result=session.stock_result or session.bill_result,
            )

        return PurchaseChatResponse(
            session_id=session.session_id,
            stage="completed",
            assistant_message=(
                "Este flujo ya terminó. Si querés arrancar otra factura, mandame una nueva imagen."
            ),
            proposal=session.proposal,
            last_apply_result=session.price_result or session.stock_result or session.bill_result,
        )

    async def _handle_resolution_turn(
        self,
        session: PurchaseChatSession,
        message: str,
    ) -> PurchaseChatResponse:
        proposal = session.proposal
        assert proposal is not None

        normalized = _normalize_resolution_text(message)
        if _looks_reset(normalized):
            session.stage = "awaiting_invoice"
            session.proposal = None
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice",
                assistant_message="Listo, descarto esta factura. Cuando quieras mandame otra.",
            )

        changes = _apply_resolution_commands(proposal, normalized)
        created_summary, creation_error = await self._apply_creation_commands(session, normalized)
        if creation_error is not None:
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_resolution",
                assistant_message=(
                    f"{creation_error}\n"
                    f"{_resolution_message(proposal)}"
                ),
                proposal=proposal,
            )
        _sync_context_from_proposal(session)

        if _looks_positive(normalized):
            if _proposal_has_resolution_blockers(proposal):
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_resolution",
                    assistant_message=(
                        "Todavía quedan cosas por resolver antes de cargar la factura.\n"
                        f"{_resolution_message(proposal)}"
                    ),
                    proposal=proposal,
                )
            proposal.needs_user_resolution = False
            session.stage = "awaiting_invoice_confirmation"
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice_confirmation",
                assistant_message=(
                    "Tomo la resolución actual como válida.\n"
                    f"{_proposal_message(proposal)}"
                ),
                proposal=proposal,
            )

        if changes or created_summary is not None:
            if _proposal_has_resolution_blockers(proposal):
                return PurchaseChatResponse(
                    session_id=session.session_id,
                    stage="awaiting_resolution",
                    assistant_message=(
                        f"{created_summary}\n" if created_summary else ""
                    ) + (
                        "Registré esos cambios, pero todavía quedan items para revisar.\n"
                        f"{_resolution_message(proposal)}"
                    ),
                    proposal=proposal,
                )
            proposal.needs_user_resolution = False
            session.stage = "awaiting_invoice_confirmation"
            return PurchaseChatResponse(
                session_id=session.session_id,
                stage="awaiting_invoice_confirmation",
                assistant_message=(
                    f"{created_summary}\n" if created_summary else ""
                ) + (
                    "Registré esas resoluciones.\n"
                    f"{_proposal_message(proposal)}"
                ),
                proposal=proposal,
            )

        return PurchaseChatResponse(
            session_id=session.session_id,
            stage="awaiting_resolution",
            assistant_message=(
                "No te seguí del todo.\n"
                f"{_resolution_message(proposal)}"
            ),
            proposal=proposal,
        )

    def _get_session(self, session_id: str | None) -> PurchaseChatSession:
        resolved = session_id or str(uuid4())
        session = self._sessions.get(resolved)
        if session is None:
            session = PurchaseChatSession(session_id=resolved)
            self._sessions[resolved] = session
        return session

    async def _apply_creation_commands(
        self,
        session: PurchaseChatSession,
        normalized: str,
    ) -> tuple[str | None, str | None]:
        proposal = session.proposal
        assert proposal is not None

        created_messages: list[str] = []
        create_all_new = bool(CREATE_NEW_ITEMS_RE.search(normalized))
        create_supplier_explicitly = bool(SUPPLIER_CREATE_RE.search(normalized))
        line_numbers_to_create = _line_numbers_to_create(normalized)
        if create_all_new:
            line_numbers_to_create.update(
                line.line_number
                for line in proposal.lines
                if line.product_resolution.status == "new"
            )

        if (
            proposal.supplier_resolution is not None
            and (
                create_supplier_explicitly
                or (create_all_new and proposal.supplier_resolution.status == "new")
            )
            and proposal.supplier_resolution.status not in {"exact", "manual"}
        ):
            resolution = proposal.supplier_resolution
            try:
                result = await self._odoo.create_partner(
                    CreatePartnerCommand(
                        name=resolution.selected_display_name
                        or resolution.extracted_name
                        or "Proveedor sin nombre",
                        vat=resolution.selected_vat or resolution.extracted_vat,
                        supplier_rank=1,
                    )
                )
            except RuntimeError as exc:
                return None, (
                    "No pude crear el proveedor nuevo en Odoo todavía.\n"
                    f"{_odoo_runtime_error_message(exc)}"
                )
            resolution.status = "manual"
            resolution.selected_partner_id = int(result.record_id or 0) or None
            resolution.selected_display_name = str(result.payload.get("name") or resolution.selected_display_name)
            resolution.selected_vat = str(result.payload.get("vat")) if result.payload.get("vat") else None
            session.context.supplier_id = resolution.selected_partner_id
            created_messages.append(
                f"Creé el proveedor {resolution.selected_display_name} con ID {resolution.selected_partner_id}."
            )

        for line_number in sorted(line_numbers_to_create):
            line = _proposal_line_by_number(proposal.lines, line_number)
            if line is None or line.product_resolution.status in {"exact", "manual"}:
                continue
            try:
                result = await self._odoo.create_product(
                    CreateProductCommand(
                        name=line.description,
                        default_code=_suggest_product_default_code(line),
                        list_price=line.suggested_sale_price,
                        standard_price=line.unit_price_net,
                        description_sale=line.description,
                    )
                )
            except RuntimeError as exc:
                return None, (
                    f"No pude crear el producto nuevo de la línea {line.line_number} en Odoo todavía.\n"
                    f"{_odoo_runtime_error_message(exc)}"
                )
            product_id = int(result.record_id or 0) or None
            line.product_resolution.status = "manual"
            line.product_resolution.selected_product_id = product_id
            line.product_resolution.selected_display_name = str(result.payload.get("name") or line.description)
            line.product_resolution.selected_default_code = (
                str(result.payload.get("default_code")) if result.payload.get("default_code") else None
            )
            line.product_match.product_id = product_id
            line.product_match.display_name = line.product_resolution.selected_display_name
            line.product_match.default_code = line.product_resolution.selected_default_code
            line.product_match.current_cost = float(result.payload.get("standard_price") or line.unit_price_net)
            line.product_match.current_sale_price = float(
                result.payload.get("list_price") or line.suggested_sale_price
            )
            line.product_match.current_stock = 0.0
            line.product_match.confidence = 1.0
            line.stock_after_update = line.quantity
            created_messages.append(
                f"Creé el producto de la línea {line.line_number} con ID {product_id}."
            )

        proposal.needs_user_resolution = _proposal_needs_manual_review(proposal)
        if not created_messages:
            return None, None
        return " ".join(created_messages), None


def _proposal_needs_resolution(proposal: PurchaseInvoiceProposalResult) -> bool:
    return proposal.needs_user_resolution


def _proposal_has_resolution_blockers(proposal: PurchaseInvoiceProposalResult) -> bool:
    if proposal.supplier_resolution and proposal.supplier_resolution.status in {"missing", "new"}:
        return True
    return any(line.product_resolution.status in {"missing", "new"} for line in proposal.lines)


def _apply_resolution_commands(proposal: PurchaseInvoiceProposalResult, normalized: str) -> bool:
    changed = False

    supplier_match = SUPPLIER_ID_RE.search(normalized)
    if supplier_match and proposal.supplier_resolution is not None:
        partner_id = int(supplier_match.group(1))
        candidate = next(
            (item for item in proposal.supplier_resolution.candidates if item.partner_id == partner_id),
            None,
        )
        proposal.supplier_resolution.status = "manual"
        proposal.supplier_resolution.selected_partner_id = partner_id
        proposal.supplier_resolution.selected_display_name = (
            candidate.display_name if candidate else f"Proveedor #{partner_id}"
        )
        proposal.supplier_resolution.selected_vat = candidate.vat if candidate else None
        changed = True

    if SUPPLIER_NEW_RE.search(normalized) and proposal.supplier_resolution is not None:
        proposal.supplier_resolution.status = "new"
        proposal.supplier_resolution.selected_partner_id = None
        proposal.supplier_resolution.selected_display_name = (
            proposal.supplier_resolution.extracted_name or "Proveedor nuevo"
        )
        proposal.supplier_resolution.selected_vat = proposal.supplier_resolution.extracted_vat
        changed = True

    for line_match in LINE_PRODUCT_RE.finditer(normalized):
        line_number = int(line_match.group(1))
        product_id = int(line_match.group(2))
        line = _proposal_line_by_number(proposal.lines, line_number)
        if line is None:
            continue
        candidate = next(
            (item for item in line.product_resolution.candidates if item.product_id == product_id),
            None,
        )
        line.product_resolution.status = "manual"
        line.product_resolution.selected_product_id = product_id
        line.product_resolution.selected_display_name = (
            candidate.display_name if candidate else f"Producto #{product_id}"
        )
        line.product_resolution.selected_default_code = candidate.default_code if candidate else None
        line.product_match.product_id = product_id
        line.product_match.display_name = line.product_resolution.selected_display_name
        line.product_match.default_code = line.product_resolution.selected_default_code
        if candidate is not None:
            line.product_match.current_sale_price = candidate.current_sale_price
            line.product_match.current_cost = candidate.current_cost
            line.product_match.current_stock = candidate.current_stock
            line.product_match.confidence = candidate.confidence
        changed = True

    for line_match in LINE_NEW_RE.finditer(normalized):
        line_number = int(line_match.group(1))
        line = _proposal_line_by_number(proposal.lines, line_number)
        if line is None:
            continue
        line.product_resolution.status = "new"
        line.product_resolution.selected_product_id = None
        line.product_resolution.selected_display_name = line.description
        line.product_resolution.selected_default_code = None
        line.product_match.product_id = None
        line.product_match.display_name = None
        line.product_match.default_code = None
        line.product_match.current_sale_price = None
        line.product_match.current_cost = None
        line.product_match.current_stock = None
        line.product_match.confidence = 0.0
        line.stock_after_update = None
        changed = True

    proposal.needs_user_resolution = _proposal_needs_manual_review(proposal)
    return changed


def _proposal_needs_manual_review(proposal: PurchaseInvoiceProposalResult) -> bool:
    if proposal.supplier_resolution and proposal.supplier_resolution.status in {
        "candidate",
        "missing",
        "new",
    }:
        return True
    return any(
        line.product_resolution.status in {"candidate", "missing", "new"}
        for line in proposal.lines
    )


def _proposal_line_by_number(
    lines: list[PurchaseInvoiceProposalLine],
    line_number: int,
) -> PurchaseInvoiceProposalLine | None:
    return next((line for line in lines if line.line_number == line_number), None)


def _merge_context(
    current: PurchaseChatContext,
    incoming: PurchaseChatContext,
) -> PurchaseChatContext:
    merged = current.model_copy(deep=True)
    for field_name in ("supplier_id", "journal_id", "picking_type_id", "location_id", "location_dest_id"):
        value = getattr(incoming, field_name)
        if value is not None:
            setattr(merged, field_name, value)

    if incoming.create_stock_receipt is not None:
        merged.create_stock_receipt = incoming.create_stock_receipt
    if incoming.markup_percentage is not None:
        merged.markup_percentage = incoming.markup_percentage

    if incoming.supplier_name and incoming.supplier_name.strip():
        merged.supplier_name = incoming.supplier_name.strip()
    if incoming.supplier_vat and incoming.supplier_vat.strip():
        merged.supplier_vat = incoming.supplier_vat.strip()
    return merged


def _sync_context_from_proposal(session: PurchaseChatSession) -> None:
    proposal = session.proposal
    if proposal is None or proposal.supplier_resolution is None:
        return
    if session.context.supplier_id is None and proposal.supplier_resolution.selected_partner_id is not None:
        session.context.supplier_id = proposal.supplier_resolution.selected_partner_id


def _resolution_message(proposal: PurchaseInvoiceProposalResult) -> str:
    pending_lines = _pending_product_lines(proposal)
    supplier_pending = (
        proposal.supplier_resolution is not None
        and proposal.supplier_resolution.status not in {"exact", "manual"}
    )
    pending_targets: list[str] = []
    if supplier_pending:
        pending_targets.append("el proveedor")
    if pending_lines:
        pending_targets.append(
            "la línea pendiente" if len(pending_lines) == 1 else f"las {len(pending_lines)} líneas pendientes"
        )

    parts = [
        f"Leí {proposal.document_type or 'la factura'} {proposal.invoice_number or 'sin número'}.",
        (
            "No queda nada pendiente antes de tocar Odoo."
            if not pending_targets
            else f"Antes de tocar Odoo me falta resolver {' y '.join(pending_targets)}."
        ),
    ]

    supplier_message = _supplier_resolution_message(proposal)
    if supplier_message:
        parts.append(supplier_message)

    if pending_lines:
        parts.append(
            "Líneas pendientes:" if supplier_pending else "El proveedor ya quedó resuelto. Me faltan estas líneas:"
        )
        parts.extend(_product_resolution_message(line) for line in pending_lines)

    parts.append(
        _resolution_help_message(
            proposal=proposal,
            supplier_pending=supplier_pending,
            pending_lines=pending_lines,
        )
    )
    return "\n".join(parts)


def _supplier_resolution_message(proposal: PurchaseInvoiceProposalResult) -> str:
    resolution = proposal.supplier_resolution
    if resolution is None:
        return ""
    if resolution.status in {"exact", "manual"} and resolution.selected_display_name:
        return (
            f"Proveedor resuelto: {resolution.selected_display_name}"
            f"{f' ({resolution.selected_vat})' if resolution.selected_vat else ''}."
        )
    if resolution.status == "new":
        return f"Proveedor marcado como nuevo: {resolution.selected_display_name or 'sin nombre'}."
    if resolution.candidates:
        options = ", ".join(
            f"{candidate.partner_id}:{candidate.display_name}"
            for candidate in resolution.candidates
        )
        return f"Proveedor a revisar: {resolution.extracted_name or 'sin nombre'} -> candidatos {options}."
    return f"Proveedor sin match claro: {resolution.extracted_name or 'sin nombre'}."


def _product_resolution_message(line: PurchaseInvoiceProposalLine) -> str:
    resolution = line.product_resolution
    if resolution.status in {"exact", "manual"} and resolution.selected_display_name:
        return (
            f"- línea {line.line_number}: {line.description} -> {resolution.selected_display_name}"
            f"{f' [{resolution.selected_default_code}]' if resolution.selected_default_code else ''}"
        )
    if resolution.status == "new":
        return f"- línea {line.line_number}: {line.description} -> marcado como producto nuevo"
    if resolution.candidates:
        options = ", ".join(
            f"{candidate.product_id}:{candidate.display_name}"
            for candidate in resolution.candidates
        )
        return f"- línea {line.line_number}: {line.description} -> revisar candidatos {options}"
    return f"- línea {line.line_number}: {line.description} -> sin match claro"


def _pending_product_lines(
    proposal: PurchaseInvoiceProposalResult,
) -> list[PurchaseInvoiceProposalLine]:
    return [
        line
        for line in proposal.lines
        if line.product_resolution.status not in {"exact", "manual"}
    ]


def _resolution_help_message(
    *,
    proposal: PurchaseInvoiceProposalResult,
    supplier_pending: bool,
    pending_lines: list[PurchaseInvoiceProposalLine],
) -> str:
    examples: list[str] = []
    first_line_number = pending_lines[0].line_number if pending_lines else 1

    if supplier_pending:
        examples.extend(["`proveedor 102`", "`proveedor nuevo`", "`crear proveedor`"])

    if pending_lines:
        examples.extend(
            [
                f"`linea {first_line_number} producto 201`",
                f"`linea {first_line_number} nuevo`",
                f"`linea {first_line_number} crear`",
            ]
        )
        if len(pending_lines) > 1:
            examples.append("`crear nuevos`")

    message = (
        "Respondeme con alguna de estas opciones: " + ", ".join(examples) + "."
        if examples
        else "Si está todo bien, seguí con la confirmación final."
    )
    if _proposal_can_accept_current_candidates(proposal):
        return f"{message} Si los candidatos actuales te cierran, también podés responder `si`."
    return message


def _proposal_can_accept_current_candidates(proposal: PurchaseInvoiceProposalResult) -> bool:
    if _proposal_has_resolution_blockers(proposal):
        return False
    return proposal.needs_user_resolution


def _proposal_message(proposal: PurchaseInvoiceProposalResult) -> str:
    supplier_label = proposal.supplier_name or "sin proveedor"
    if proposal.supplier_resolution and proposal.supplier_resolution.selected_display_name:
        supplier_label = proposal.supplier_resolution.selected_display_name

    lines = "\n".join(
        f"- línea {line.line_number}: {line.description}: qty {line.quantity}, costo neto ${line.unit_price_net}, venta sugerida ${line.suggested_sale_price}"
        for line in proposal.lines
    )
    warnings = "\n".join(f"- {warning}" for warning in proposal.warnings) or "- Sin alertas fuertes."
    return (
        f"Revisé {proposal.document_type or 'la factura'} {proposal.invoice_number or 'sin número'} "
        f"del proveedor {supplier_label}.\n"
        f"Fecha: {proposal.invoice_date or 'sin fecha'}.\n"
        f"Totales calculados: neto ${proposal.totals.untaxed}, IVA ${proposal.totals.vat}, total ${proposal.totals.total}.\n"
        f"Líneas:\n{lines}\n"
        f"Alertas:\n{warnings}\n"
        "Si está bien, confirmame y cargo primero la factura de compra en Odoo."
    )


def _proposal_summary(proposal: PurchaseInvoiceProposalResult) -> str:
    supplier_label = proposal.supplier_name or "s/d"
    if proposal.supplier_resolution and proposal.supplier_resolution.selected_display_name:
        supplier_label = proposal.supplier_resolution.selected_display_name
    return (
        f"{proposal.document_type or 'factura'} {proposal.invoice_number or 's/n'} "
        f"proveedor {supplier_label} total {proposal.totals.total}"
    )


def _bill_applied_message(
    *,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
    prefix: str,
    create_stock_receipt: bool,
) -> str:
    operations = ", ".join(operation.model for operation in result.operations) or "sin operaciones"
    warnings = "\n".join(f"- {warning}" for warning in result.warnings) or "- Sin warnings."
    next_step = (
        "Ahora decime si querés generar la recepción de stock en Odoo."
        if create_stock_receipt
        else "Ahora decime si querés actualizar los precios de productos usando el markup propuesto."
    )
    return (
        f"{prefix}\n"
        f"Cargué la factura {proposal.invoice_number or ''} y preparé estas operaciones: {operations}.\n"
        f"Warnings:\n{warnings}\n"
        f"{next_step}"
    )


def _stock_applied_message(*, result: ApplyPurchaseInvoiceProposalResult, prefix: str) -> str:
    stock_moves = [operation for operation in result.operations if operation.model == "stock.picking"]
    warnings = "\n".join(f"- {warning}" for warning in result.warnings) or "- Sin warnings."
    return (
        f"{prefix}\n"
        f"Generé {len(stock_moves)} recepción(es) de stock.\n"
        f"Warnings:\n{warnings}\n"
        "Ahora decime si querés actualizar los precios de productos usando el markup propuesto."
    )


def _price_applied_message(result: ApplyPurchaseInvoiceProposalResult, prefix: str) -> str:
    product_updates = [operation for operation in result.operations if operation.model == "product.template"]
    return (
        f"{prefix}\n"
        f"Actualicé {len(product_updates)} productos con nuevos costos y precios sugeridos. "
        "Si querés seguir con otra factura, mandame una nueva imagen."
    )


def _apply_blocked_message(
    *,
    prefix: str,
    result: ApplyPurchaseInvoiceProposalResult,
    next_step: str,
) -> str:
    warnings = "\n".join(f"- {warning}" for warning in result.warnings) or "- Sin warnings."
    return f"{prefix}\nWarnings:\n{warnings}\n{next_step}"


def _odoo_runtime_error_message(exc: RuntimeError) -> str:
    return str(exc)


def _normalize_resolution_text(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(
        ascii_value.casefold()
        .replace(",", " ")
        .replace(".", " ")
        .replace(":", " ")
        .split()
    )


def _line_numbers_to_create(normalized: str) -> set[int]:
    line_numbers = {int(match.group(1)) for match in LINE_CREATE_RE.finditer(normalized)}
    line_numbers.update(int(match.group(1)) for match in CREATE_LINE_RE.finditer(normalized))
    return line_numbers


def _suggest_product_default_code(line: PurchaseInvoiceProposalLine) -> str | None:
    ascii_value = (
        unicodedata.normalize("NFKD", line.description).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^A-Z0-9]+", "-", ascii_value.upper()).strip("-")
    if not cleaned:
        return None
    if cleaned.isdigit() and len(cleaned) <= 20:
        return cleaned
    base = cleaned[:18]
    return f"AUTO-{base[:13]}" if base else None


def _looks_positive(normalized: str) -> bool:
    return any(
        token in normalized
        for token in ("si", "confirmo", "confirmar", "dale", "ok", "mandale", "avanza")
    )


def _looks_reset(normalized: str) -> bool:
    return any(token in normalized for token in ("reset", "cancelar", "descartar", "no va"))
