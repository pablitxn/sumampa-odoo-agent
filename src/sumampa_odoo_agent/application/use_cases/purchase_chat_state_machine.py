"""Application-level state machine helpers for purchase chat responses."""

from __future__ import annotations

from sumampa_odoo_agent.application.requests.odoo import (
    ApplyPurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
)
from sumampa_odoo_agent.application.requests.purchase_chat import PurchaseChatResponse
from sumampa_odoo_agent.application.use_cases.purchase_chat_resolution import (
    ApplyPurchaseChatResolutionResult,
    proposal_has_resolution_blockers,
)


def response_after_invoice_analysis(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
) -> PurchaseChatResponse:
    if proposal.needs_user_resolution:
        return PurchaseChatResponse(
            session_id=session_id,
            stage="awaiting_resolution",
            assistant_message=resolution_message(proposal),
            proposal=proposal,
        )
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice_confirmation",
        assistant_message=proposal_message(proposal),
        proposal=proposal,
    )


def response_awaiting_invoice(*, session_id: str, assistant_message: str) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice",
        assistant_message=assistant_message,
    )


def response_missing_context(*, session_id: str) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice",
        assistant_message="Perdí el contexto de la factura. Reenviame la imagen y retomamos.",
    )


def response_after_resolution(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    resolution: ApplyPurchaseChatResolutionResult,
) -> PurchaseChatResponse:
    if resolution.reset_requested:
        return PurchaseChatResponse(
            session_id=session_id,
            stage="awaiting_invoice",
            assistant_message="Listo, descarto esta factura. Cuando quieras mandame otra.",
        )

    if resolution.error_message is not None:
        return PurchaseChatResponse(
            session_id=session_id,
            stage="awaiting_resolution",
            assistant_message=f"{resolution.error_message}\n{resolution_message(proposal)}",
            proposal=proposal,
        )

    if resolution.ready_for_confirmation:
        prefix = (
            "Tomo la resolución actual como válida."
            if looks_like_explicit_accept(resolution)
            else "Registré esas resoluciones."
        )
        summary = f"{resolution.created_summary}\n" if resolution.created_summary else ""
        return PurchaseChatResponse(
            session_id=session_id,
            stage="awaiting_invoice_confirmation",
            assistant_message=f"{summary}{prefix}\n{proposal_message(proposal)}",
            proposal=proposal,
        )

    if resolution.has_blockers and (resolution.changed or resolution.created_summary or looks_like_explicit_accept(resolution)):
        summary = f"{resolution.created_summary}\n" if resolution.created_summary else ""
        prefix = (
            "Todavía quedan cosas por resolver antes de cargar la factura."
            if looks_like_explicit_accept(resolution)
            else "Registré esos cambios, pero todavía quedan items para revisar."
        )
        return PurchaseChatResponse(
            session_id=session_id,
            stage="awaiting_resolution",
            assistant_message=f"{summary}{prefix}\n{resolution_message(proposal)}",
            proposal=proposal,
        )

    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_resolution",
        assistant_message=f"No te seguí del todo.\n{resolution_message(proposal)}",
        proposal=proposal,
    )


def response_invoice_rejected(*, session_id: str, assistant_message: str) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice",
        assistant_message=assistant_message,
    )


def response_invoice_runtime_error(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    exc: RuntimeError,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice_confirmation",
        assistant_message=f"No pude cargar la factura en Odoo todavía.\n{exc}",
        proposal=proposal,
    )


def response_invoice_blocked(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_invoice_confirmation",
        assistant_message=apply_blocked_message(
            prefix="Todavía no pude cargar la factura en Odoo.",
            result=result,
            next_step=(
                "Revisá los warnings, ajustá el contexto si hace falta y "
                "después volvé a confirmarme la factura."
            ),
        ),
        proposal=proposal,
        last_apply_result=result,
    )


def response_invoice_applied(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
    assistant_message: str,
    create_stock_receipt: bool,
) -> PurchaseChatResponse:
    next_stage = "awaiting_stock_confirmation" if create_stock_receipt else "awaiting_price_confirmation"
    return PurchaseChatResponse(
        session_id=session_id,
        stage=next_stage,
        assistant_message=bill_applied_message(
            proposal=proposal,
            result=result,
            prefix=assistant_message,
            create_stock_receipt=create_stock_receipt,
        ),
        proposal=proposal,
        last_apply_result=result,
    )


def response_stock_runtime_error(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
    exc: RuntimeError,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_stock_confirmation",
        assistant_message=f"No pude generar la recepción de stock en Odoo todavía.\n{exc}",
        proposal=proposal,
        last_apply_result=last_apply_result,
    )


def response_stock_blocked(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_stock_confirmation",
        assistant_message=apply_blocked_message(
            prefix="Todavía no pude generar la recepción de stock.",
            result=result,
            next_step=(
                "Revisá los warnings, ajustá el contexto si hace falta y "
                "después volvé a confirmarme la recepción."
            ),
        ),
        proposal=proposal,
        last_apply_result=result,
    )


def response_stock_applied(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
    assistant_message: str,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_price_confirmation",
        assistant_message=stock_applied_message(result=result, prefix=assistant_message),
        proposal=proposal,
        last_apply_result=result,
    )


def response_stock_rejected(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    assistant_message: str,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_price_confirmation",
        assistant_message=(
            f"{assistant_message}\n"
            "Ahora decime si querés actualizar los precios de productos usando el markup propuesto."
        ),
        proposal=proposal,
        last_apply_result=last_apply_result,
    )


def response_price_runtime_error(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
    exc: RuntimeError,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_price_confirmation",
        assistant_message=f"No pude actualizar los precios en Odoo todavía.\n{exc}",
        proposal=proposal,
        last_apply_result=last_apply_result,
    )


def response_price_blocked(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="awaiting_price_confirmation",
        assistant_message=apply_blocked_message(
            prefix="Todavía no pude actualizar los precios.",
            result=result,
            next_step=(
                "Revisá los warnings y, si sigue teniendo sentido, "
                "confirmame de nuevo la actualización."
            ),
        ),
        proposal=proposal,
        last_apply_result=result,
    )


def response_price_applied(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    result: ApplyPurchaseInvoiceProposalResult,
    assistant_message: str,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="completed",
        assistant_message=price_applied_message(result, assistant_message),
        proposal=proposal,
        last_apply_result=result,
    )


def response_price_rejected(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult,
    assistant_message: str,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="completed",
        assistant_message=assistant_message,
        proposal=proposal,
        last_apply_result=last_apply_result,
    )


def response_completed_existing_flow(
    *,
    session_id: str,
    proposal: PurchaseInvoiceProposalResult | None,
    last_apply_result: ApplyPurchaseInvoiceProposalResult | None,
) -> PurchaseChatResponse:
    return PurchaseChatResponse(
        session_id=session_id,
        stage="completed",
        assistant_message="Este flujo ya terminó. Si querés arrancar otra factura, mandame una nueva imagen.",
        proposal=proposal,
        last_apply_result=last_apply_result,
    )


def looks_like_explicit_accept(resolution: ApplyPurchaseChatResolutionResult) -> bool:
    return resolution.normalized_message in {"si", "confirmo", "confirmar", "dale", "ok", "mandale", "avanza"}


def resolution_message(proposal: PurchaseInvoiceProposalResult) -> str:
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


def proposal_message(proposal: PurchaseInvoiceProposalResult) -> str:
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


def proposal_summary(proposal: PurchaseInvoiceProposalResult) -> str:
    supplier_label = proposal.supplier_name or "s/d"
    if proposal.supplier_resolution and proposal.supplier_resolution.selected_display_name:
        supplier_label = proposal.supplier_resolution.selected_display_name
    return (
        f"{proposal.document_type or 'factura'} {proposal.invoice_number or 's/n'} "
        f"proveedor {supplier_label} total {proposal.totals.total}"
    )


def bill_applied_message(
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


def stock_applied_message(*, result: ApplyPurchaseInvoiceProposalResult, prefix: str) -> str:
    stock_moves = [operation for operation in result.operations if operation.model == "stock.picking"]
    warnings = "\n".join(f"- {warning}" for warning in result.warnings) or "- Sin warnings."
    return (
        f"{prefix}\n"
        f"Generé {len(stock_moves)} recepción(es) de stock.\n"
        f"Warnings:\n{warnings}\n"
        "Ahora decime si querés actualizar los precios de productos usando el markup propuesto."
    )


def price_applied_message(result: ApplyPurchaseInvoiceProposalResult, prefix: str) -> str:
    product_updates = [operation for operation in result.operations if operation.model == "product.template"]
    return (
        f"{prefix}\n"
        f"Actualicé {len(product_updates)} productos con nuevos costos y precios sugeridos. "
        "Si querés seguir con otra factura, mandame una nueva imagen."
    )


def apply_blocked_message(
    *,
    prefix: str,
    result: ApplyPurchaseInvoiceProposalResult,
    next_step: str,
) -> str:
    warnings = "\n".join(f"- {warning}" for warning in result.warnings) or "- Sin warnings."
    return f"{prefix}\nWarnings:\n{warnings}\n{next_step}"


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
    if proposal_has_resolution_blockers(proposal):
        return False
    return proposal.needs_user_resolution
