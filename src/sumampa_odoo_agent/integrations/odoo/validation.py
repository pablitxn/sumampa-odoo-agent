"""Validation helpers shared by Odoo gateway implementations."""

from __future__ import annotations

from sumampa_odoo_agent.services.models.odoo import (
    ArgentinaInvoiceValidationInput,
    DeliveryValidationInput,
    InvoiceValidationInput,
    OdooIntegrationMode,
    OdooValidationIssue,
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

    warnings: list[OdooValidationIssue] = []
    if draft.move_type != "out_invoice":
        warnings.append(
            _validation_issue(
                "unexpected_move_type",
                expected_move_type="out_invoice",
                actual_move_type=draft.move_type,
            )
        )

    return OdooValidationResult(
        mode=mode,
        operation="invoice",
        ok=not missing,
        missing_fields=missing,
        warnings=warnings,
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

    warnings: list[OdooValidationIssue] = []
    if draft.wsfe_service and draft.wsfe_service.casefold() != "wsfev1":
        warnings.append(
            _validation_issue(
                "unexpected_wsfe_service",
                expected_wsfe_service="wsfev1",
                actual_wsfe_service=draft.wsfe_service,
            )
        )

    expected_letter = _expected_ar_document_letter(
        emitter_taxpayer_type=draft.emitter_taxpayer_type,
        partner_taxpayer_type=draft.partner_taxpayer_type,
    )
    if expected_letter and draft.document_letter and draft.document_letter.upper() != expected_letter:
        warnings.append(
            _validation_issue(
                "document_letter_mismatch",
                expected_letter=expected_letter,
                actual_document_letter=draft.document_letter.upper(),
            )
        )
    if expected_letter and not draft.document_letter:
        warnings.append(
            _validation_issue(
                "document_letter_missing",
                expected_letter=expected_letter,
            )
        )
    if not draft.partner_vat and not draft.partner_doc_type:
        warnings.append(
            _validation_issue(
                "partner_tax_id_or_doc_type_missing",
                required_any=["partner_vat", "partner_doc_type"],
            )
        )
    if not draft.email_to:
        warnings.append(_validation_issue("email_to_missing", field="email_to"))

    return OdooValidationResult(
        mode=mode,
        operation="argentina_invoice",
        ok=not missing,
        missing_fields=missing,
        warnings=warnings,
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
    )


def _validation_issue(code: str, **details: object) -> OdooValidationIssue:
    return OdooValidationIssue(code=code, details=dict(details))


def _expected_ar_document_letter(
    *,
    emitter_taxpayer_type: str | None,
    partner_taxpayer_type: str | None,
) -> str | None:
    emitter = (emitter_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    partner = (partner_taxpayer_type or "").strip().replace("_", " ").replace("-", " ").casefold()
    if not emitter:
        return None
    if "simplified regime" in emitter or "monotax" in emitter:
        return "C"
    if "registered taxpayer" in emitter or emitter == "registered":
        if "registered taxpayer" in partner or partner == "registered":
            return "A"
        if partner:
            return "B"
        return None
    return None
