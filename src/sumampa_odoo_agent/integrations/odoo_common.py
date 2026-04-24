"""Shared helpers for Odoo gateway implementations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sumampa_odoo_agent.services.message_specs import render_message
from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryInput,
    DeliveryMoveInput,
    DeliveryValidationInput,
    InvoiceInput,
    InvoiceValidationInput,
    OdooIntegrationMode,
    OdooSearchHit,
    OdooValidationResult,
)


def validate_invoice_draft(
    *,
    mode: OdooIntegrationMode,
    draft: InvoiceValidationInput,
) -> OdooValidationResult:
    missing: list[str] = []
    if not draft.partner_id:
        missing.append("partner_id")
    if not draft.journal_id:
        missing.append("journal_id")
    if draft.line_count <= 0:
        missing.append("lines")

    warnings: list[str] = []
    if draft.move_type != "out_invoice":
        warnings.append(_odoo_validation_message("move_type_actual", move_type=draft.move_type))

    return OdooValidationResult(
        mode=mode,
        operation="invoice",
        ok=not missing,
        missing_fields=missing,
        warnings=warnings,
        suggested_actions=_invoice_actions(missing),
    )


def validate_argentina_invoice_draft(
    *,
    mode: OdooIntegrationMode,
    draft: ArgentinaInvoiceValidationInput,
) -> OdooValidationResult:
    missing: list[str] = []
    if not draft.emitter_vat:
        missing.append("emitter_vat")
    if not draft.emitter_taxpayer_type:
        missing.append("emitter_taxpayer_type")
    if not draft.point_of_sale:
        missing.append("point_of_sale")
    if not draft.partner_name:
        missing.append("partner_name")
    if draft.line_count <= 0:
        missing.append("lines")

    warnings: list[str] = []
    if draft.wsfe_service and draft.wsfe_service.casefold() != "wsfev1":
        warnings.append(
            _odoo_validation_message(
                "wsfe_service_actual",
                wsfe_service=draft.wsfe_service,
            )
        )

    expected_letter = _expected_ar_document_letter(
        emitter_taxpayer_type=draft.emitter_taxpayer_type,
        partner_taxpayer_type=draft.partner_taxpayer_type,
    )
    if expected_letter and draft.document_letter and draft.document_letter.upper() != expected_letter:
        warnings.append(
            _odoo_validation_message(
                "document_letter_mismatch",
                expected_letter=expected_letter,
                document_letter=draft.document_letter.upper(),
            )
        )
    if expected_letter and not draft.document_letter:
        warnings.append(
            _odoo_validation_message(
                "document_letter_missing",
                expected_letter=expected_letter,
            )
        )
    if not draft.partner_vat and not draft.partner_doc_type:
        warnings.append(_odoo_validation_message("partner_tax_id_or_doc_type_missing"))
    if not draft.email_to:
        warnings.append(_odoo_validation_message("email_to_missing"))

    return OdooValidationResult(
        mode=mode,
        operation="argentina_invoice",
        ok=not missing,
        missing_fields=missing,
        warnings=warnings,
        suggested_actions=_argentina_invoice_actions(missing, expected_letter),
    )


def validate_delivery_draft(
    *,
    mode: OdooIntegrationMode,
    draft: DeliveryValidationInput,
) -> OdooValidationResult:
    missing: list[str] = []
    if not draft.partner_id:
        missing.append("partner_id")
    if not draft.picking_type_id:
        missing.append("picking_type_id")
    if not draft.location_id:
        missing.append("location_id")
    if not draft.location_dest_id:
        missing.append("location_dest_id")
    if draft.move_count <= 0:
        missing.append("moves")

    return OdooValidationResult(
        mode=mode,
        operation="delivery",
        ok=not missing,
        missing_fields=missing,
        warnings=[],
        suggested_actions=_delivery_actions(missing),
    )


def filter_hits(
    rows: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    extra_keys: tuple[str, ...],
) -> list[OdooSearchHit]:
    needle = query.casefold()
    hits: list[OdooSearchHit] = []
    for row in rows:
        searchable = [str(row.get("display_name", "")), *[str(row.get(key, "")) for key in extra_keys]]
        if not any(needle in value.casefold() for value in searchable):
            continue
        hits.append(
            OdooSearchHit(
                id=int(row["id"]),
                display_name=str(row["display_name"]),
                extra={key: row.get(key) for key in extra_keys},
            )
        )
        if len(hits) >= limit:
            break
    return hits


def delivery_move_payload(
    *,
    move: DeliveryMoveInput,
    metadata: dict[str, int | None],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": metadata.get("product_variant_id") or move.product_id,
        "product_uom_qty": move.quantity,
        "name": move.name or f"Move {move.product_id}",
    }
    if metadata.get("uom_id") is not None:
        payload["product_uom"] = metadata["uom_id"]
    return payload


def invoice_payload(invoice: InvoiceInput) -> dict[str, Any]:
    payload = invoice.model_dump(exclude_none=True, exclude={"lines"})
    payload["invoice_line_ids"] = [
        (
            0,
            0,
            {
                "product_id": line.product_id,
                "quantity": line.quantity,
                "price_unit": line.price_unit,
                "name": line.name,
            },
        )
        for line in invoice.lines
    ]
    return payload


def delivery_payload(
    delivery: DeliveryInput,
    *,
    metadata: Mapping[int, Mapping[str, int | None]] | None = None,
) -> dict[str, Any]:
    resolved_metadata = metadata or {}
    payload = delivery.model_dump(exclude_none=True, exclude={"moves"})
    payload["move_ids"] = [
        (
            0,
            0,
            delivery_move_payload(
                move=move,
                metadata=dict(resolved_metadata.get(move.product_id, {})),
            ),
        )
        for move in delivery.moves
    ]
    return payload


def normalize_odoo_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
        return {"id": value[0], "name": value[1]}
    return value


def _odoo_validation_message(key: str, **context: object) -> str:
    return render_message("odoo_validation.json", key, **context)


def _invoice_actions(missing: list[str]) -> list[str]:
    actions = []
    if "partner_id" in missing:
        actions.append("Buscar el partner con search_partners antes de facturar.")
    if "journal_id" in missing:
        actions.append("Resolver el diario con search_journals antes de facturar.")
    if "lines" in missing:
        actions.append("Agregar al menos una linea de factura valida.")
    return actions


def _delivery_actions(missing: list[str]) -> list[str]:
    actions = []
    if "partner_id" in missing:
        actions.append("Buscar el cliente con search_partners.")
    if "picking_type_id" in missing:
        actions.append("Resolver el tipo de picking con search_picking_types.")
    if "location_id" in missing or "location_dest_id" in missing:
        actions.append("Resolver ubicaciones con search_locations antes de crear el remito.")
    if "moves" in missing:
        actions.append("Agregar al menos un movimiento de stock.")
    return actions


def _argentina_invoice_actions(missing: list[str], expected_letter: str | None) -> list[str]:
    actions = []
    if "emitter_vat" in missing:
        actions.append("Completar el CUIT del emisor en la company.")
    if "emitter_taxpayer_type" in missing:
        actions.append("Definir la responsabilidad fiscal ARCA/AFIP del emisor.")
    if "point_of_sale" in missing:
        actions.append("Definir un punto de venta exclusivo para WSFE.")
    if "partner_name" in missing:
        actions.append("Completar nombre o razon social del receptor.")
    if "lines" in missing:
        actions.append("Agregar al menos una linea de factura.")
    if expected_letter:
        actions.append(f"Usar letra de comprobante {expected_letter} salvo excepcion fiscal real.")
    actions.append("Verificar que el web service habilitado sea wsfev1.")
    return actions


def _expected_ar_document_letter(
    *,
    emitter_taxpayer_type: str | None,
    partner_taxpayer_type: str | None,
) -> str | None:
    emitter = (emitter_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    partner = (partner_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    if not emitter:
        return None
    if "monotrib" in emitter:
        return "C"
    if "responsable inscripto" in emitter or emitter == "ri":
        if "responsable inscripto" in partner or partner == "ri":
            return "A"
        if partner:
            return "B"
        return None
    return None
