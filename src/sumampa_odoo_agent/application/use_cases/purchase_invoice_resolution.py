"""Use case for resolving extracted purchase invoices against Odoo candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sumampa_odoo_agent.application.requests.odoo import (
    PurchaseInvoiceProductCandidate,
    PurchaseInvoiceProductMatch,
    PurchaseInvoiceProductResolution,
    PurchaseInvoiceProposalLine,
    PurchaseInvoiceProposalResult,
    PurchaseInvoiceProposalTotals,
    PurchaseInvoiceSupplierCandidate,
    PurchaseInvoiceSupplierResolution,
)


@dataclass(slots=True)
class ResolvePurchaseInvoiceEntitiesInput:
    mode: str
    extracted: Any
    markup_percentage: float
    partners: list[dict[str, Any]]
    products: list[dict[str, Any]]
    stock_by_product_id: dict[int, float]
    supplier_vat: str | None


class ResolvePurchaseInvoiceEntitiesUseCase:
    """Resolve supplier/products and build a proposal from extracted invoice data."""

    def run(
        self,
        request: ResolvePurchaseInvoiceEntitiesInput,
    ) -> PurchaseInvoiceProposalResult:
        proposal_lines: list[PurchaseInvoiceProposalLine] = []
        warnings: list[str] = []
        untaxed = 0.0
        vat_total = 0.0
        resolved_supplier_vat = request.supplier_vat or request.extracted.supplier_vat
        supplier_resolution = _resolve_supplier(
            supplier_name=request.extracted.supplier_name,
            supplier_vat=resolved_supplier_vat,
            partners=request.partners,
        )

        if supplier_resolution.status == "candidate":
            warnings.append("El proveedor requiere confirmacion humana antes de cargar la factura.")
        if supplier_resolution.status == "missing":
            warnings.append("No se encontro un proveedor claro en Odoo para esta factura.")

        for line_number, raw_line in enumerate(request.extracted.lines, start=1):
            quantity = float(raw_line.quantity)
            unit_price_gross = float(raw_line.unit_price_gross)
            vat_rate = float(raw_line.vat_rate)
            unit_price_net = round_money(unit_price_gross / (1 + (vat_rate / 100)))
            subtotal_net = round_money(unit_price_net * quantity)
            subtotal_vat = round_money((unit_price_gross - unit_price_net) * quantity)
            subtotal_gross = round_money(unit_price_gross * quantity)

            product_candidates = _build_product_candidates(
                str(raw_line.description),
                request.products,
                request.stock_by_product_id,
            )
            product_resolution = _resolve_product(product_candidates)
            product_match = _product_match_from_resolution(product_resolution)

            if product_resolution.status == "candidate":
                warnings.append(
                    f"La linea {line_number} requiere confirmar producto en Odoo: '{raw_line.description}'."
                )
            if product_resolution.status == "missing":
                warnings.append(f"No se encontro match claro en Odoo para '{raw_line.description}'.")

            stock_after_update = None
            if product_match.product_id is not None and product_match.current_stock is not None:
                stock_after_update = round_money(product_match.current_stock + quantity)

            proposal_lines.append(
                PurchaseInvoiceProposalLine(
                    line_number=line_number,
                    description=str(raw_line.description),
                    quantity=quantity,
                    unit_price_gross=unit_price_gross,
                    vat_rate=vat_rate,
                    unit_price_net=unit_price_net,
                    subtotal_net=subtotal_net,
                    subtotal_vat=subtotal_vat,
                    subtotal_gross=subtotal_gross,
                    product_match=product_match,
                    product_resolution=product_resolution,
                    suggested_sale_price=round_money(
                        unit_price_net * (1 + (request.markup_percentage / 100))
                    ),
                    suggested_markup_percentage=request.markup_percentage,
                    stock_after_update=stock_after_update,
                )
            )
            untaxed += subtotal_net
            vat_total += subtotal_vat

        needs_user_resolution = supplier_resolution.status in {"candidate", "missing"} or any(
            line.product_resolution.status in {"candidate", "missing"} for line in proposal_lines
        )

        return PurchaseInvoiceProposalResult(
            mode=request.mode,
            supplier_name=request.extracted.supplier_name,
            supplier_vat=resolved_supplier_vat,
            supplier_resolution=supplier_resolution,
            invoice_number=request.extracted.invoice_number,
            invoice_date=normalize_invoice_date(request.extracted.invoice_date),
            document_type=request.extracted.document_type,
            currency=str(request.extracted.currency or "ARS"),
            extracted_totals=build_extracted_totals(request.extracted),
            markup_percentage=request.markup_percentage,
            lines=proposal_lines,
            totals=PurchaseInvoiceProposalTotals(
                untaxed=round_money(untaxed),
                vat=round_money(vat_total),
                total=round_money(untaxed + vat_total),
            ),
            needs_user_resolution=needs_user_resolution,
            warnings=warnings + proposal_total_warnings(request.extracted, untaxed, vat_total),
            assumptions=[
                "La propuesta comercial calcula el nuevo precio sobre costo neto sin IVA.",
                "La extraccion principal puede correr con GPT-5.4 usando salida estructurada.",
                "La interfaz del extractor queda desacoplada para reemplazarla mas adelante por OCR barato si conviene.",
                "La resolucion de proveedor y productos se hace contra Odoo con candidatos y confirmacion humana.",
            ],
        )


def normalize_product_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "display_name": str(row.get("display_name") or row.get("name") or row["id"]),
        "default_code": row.get("default_code"),
        "list_price": float(row.get("list_price") or 0.0),
        "standard_price": float(row.get("standard_price") or 0.0),
        "supplier_aliases": list(row.get("supplier_aliases") or []),
    }


def normalize_partner_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "display_name": str(row.get("display_name") or row.get("name") or row["id"]),
        "vat": row.get("vat"),
        "email": row.get("email"),
        "supplier_aliases": list(row.get("supplier_aliases") or []),
        "supplier_alias_vats": list(row.get("supplier_alias_vats") or []),
    }


def normalize_text(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    return " ".join(part for part in normalized.split() if part)


def normalize_invoice_date(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    candidate_values = (raw, re.sub(r"[./\s]+", "-", raw))
    candidate_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
    )
    for candidate in candidate_values:
        for fmt in candidate_formats:
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return raw


def normalize_vat(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def round_money(value: float) -> float:
    return round(value + 1e-9, 2)


def build_extracted_totals(extracted: Any) -> PurchaseInvoiceProposalTotals | None:
    if (
        extracted.subtotal_untaxed is None
        and extracted.total_vat is None
        and extracted.total_amount is None
    ):
        return None
    return PurchaseInvoiceProposalTotals(
        untaxed=round_money(float(extracted.subtotal_untaxed or 0.0)),
        vat=round_money(float(extracted.total_vat or 0.0)),
        total=round_money(float(extracted.total_amount or 0.0)),
    )


def proposal_total_warnings(extracted: Any, untaxed: float, vat_total: float) -> list[str]:
    warnings: list[str] = []
    extracted_totals = build_extracted_totals(extracted)
    if extracted_totals is None:
        return warnings
    if abs(extracted_totals.untaxed - round_money(untaxed)) > 1.0:
        warnings.append("El subtotal neto extraido no coincide con la suma de lineas.")
    if abs(extracted_totals.vat - round_money(vat_total)) > 1.0:
        warnings.append("El IVA total extraido no coincide con la suma de lineas.")
    if abs(extracted_totals.total - round_money(untaxed + vat_total)) > 1.0:
        warnings.append("El total extraido no coincide con la suma de lineas.")
    return warnings


def _resolve_supplier(
    *,
    supplier_name: str | None,
    supplier_vat: str | None,
    partners: list[dict[str, Any]],
) -> PurchaseInvoiceSupplierResolution:
    candidates = _build_supplier_candidates(
        supplier_name=supplier_name,
        supplier_vat=supplier_vat,
        partners=partners,
    )
    top_candidate = candidates[0] if candidates else None
    if top_candidate is None:
        return PurchaseInvoiceSupplierResolution(
            status="missing",
            extracted_name=supplier_name,
            extracted_vat=supplier_vat,
            candidates=[],
        )

    status = "candidate"
    if top_candidate.reason == "vat_exact" or top_candidate.confidence >= 0.92:
        status = "exact"

    return PurchaseInvoiceSupplierResolution(
        status=status,
        selected_partner_id=top_candidate.partner_id,
        selected_display_name=top_candidate.display_name,
        selected_vat=top_candidate.vat,
        extracted_name=supplier_name,
        extracted_vat=supplier_vat,
        candidates=candidates,
    )


def _build_supplier_candidates(
    *,
    supplier_name: str | None,
    supplier_vat: str | None,
    partners: list[dict[str, Any]],
) -> list[PurchaseInvoiceSupplierCandidate]:
    ranked: list[PurchaseInvoiceSupplierCandidate] = []
    for partner in partners:
        confidence, reason = _supplier_confidence(
            supplier_name=supplier_name,
            supplier_vat=supplier_vat,
            partner=partner,
        )
        if confidence <= 0:
            continue
        ranked.append(
            PurchaseInvoiceSupplierCandidate(
                partner_id=int(partner["id"]),
                display_name=str(partner["display_name"]),
                vat=partner.get("vat"),
                email=partner.get("email"),
                confidence=confidence,
                reason=reason,
            )
        )
    ranked.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return ranked[:3]


def _supplier_confidence(
    *,
    supplier_name: str | None,
    supplier_vat: str | None,
    partner: dict[str, Any],
) -> tuple[float, str | None]:
    normalized_supplier_vat = normalize_vat(supplier_vat)
    normalized_partner_vat = normalize_vat(partner.get("vat"))
    if normalized_supplier_vat and normalized_partner_vat and normalized_supplier_vat == normalized_partner_vat:
        return 1.0, "vat_exact"

    alias_vats = {normalize_vat(value) for value in partner.get("supplier_alias_vats", [])}
    if normalized_supplier_vat and normalized_supplier_vat in alias_vats:
        return 0.99, "memory_vat"

    alias_names = {
        normalize_text(value) for value in partner.get("supplier_aliases", []) if normalize_text(value)
    }
    normalized_supplier_name = normalize_text(supplier_name or "")
    if normalized_supplier_name and normalized_supplier_name in alias_names:
        return 0.98, "memory_alias"

    if supplier_name:
        name_confidence = _token_overlap_confidence(
            supplier_name,
            str(partner.get("display_name") or ""),
        )
        if name_confidence > 0:
            return name_confidence, "name_overlap"

    return 0.0, None


def _build_product_candidates(
    description: str,
    products: list[dict[str, Any]],
    stock_by_product_id: dict[int, float],
) -> list[PurchaseInvoiceProductCandidate]:
    ranked: list[PurchaseInvoiceProductCandidate] = []
    for product in products:
        confidence = _match_confidence(description, product)
        if confidence <= 0:
            continue
        ranked.append(
            PurchaseInvoiceProductCandidate(
                product_id=int(product["id"]),
                display_name=str(product["display_name"]),
                default_code=product.get("default_code"),
                current_sale_price=product.get("list_price"),
                current_cost=product.get("standard_price"),
                current_stock=stock_by_product_id.get(int(product["id"])),
                confidence=confidence,
                reason="name_overlap",
            )
        )
    ranked.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return ranked[:3]


def _resolve_product(
    candidates: list[PurchaseInvoiceProductCandidate],
) -> PurchaseInvoiceProductResolution:
    top_candidate = candidates[0] if candidates else None
    if top_candidate is None:
        return PurchaseInvoiceProductResolution(status="missing", candidates=[])

    status = "candidate"
    if top_candidate.confidence >= 0.92:
        status = "exact"

    return PurchaseInvoiceProductResolution(
        status=status,
        selected_product_id=top_candidate.product_id,
        selected_display_name=top_candidate.display_name,
        selected_default_code=top_candidate.default_code,
        candidates=candidates,
    )


def _match_confidence(description: str, product: dict[str, Any] | None) -> float:
    if not product:
        return 0.0
    aliases = " ".join(str(alias) for alias in product.get("supplier_aliases", []))
    return _token_overlap_confidence(
        description,
        (
            f"{product.get('display_name') or ''} "
            f"{product.get('default_code') or ''} "
            f"{aliases}"
        ),
    )


def _product_match_from_resolution(
    resolution: PurchaseInvoiceProductResolution,
) -> PurchaseInvoiceProductMatch:
    top_candidate = resolution.candidates[0] if resolution.candidates else None
    if top_candidate is None:
        return PurchaseInvoiceProductMatch()
    return PurchaseInvoiceProductMatch(
        product_id=resolution.selected_product_id,
        display_name=resolution.selected_display_name,
        default_code=resolution.selected_default_code,
        current_sale_price=top_candidate.current_sale_price,
        current_cost=top_candidate.current_cost,
        current_stock=top_candidate.current_stock,
        confidence=top_candidate.confidence,
    )


def _token_overlap_confidence(source: str, target: str) -> float:
    source_tokens = set(normalize_text(source).split())
    target_tokens = set(normalize_text(target).split())
    if not source_tokens or not target_tokens:
        return 0.0
    overlap = len(source_tokens & target_tokens)
    return min(1.0, overlap / max(1, len(source_tokens)))
