"""Payload builders for Odoo create operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sumampa_odoo_agent.services.models.odoo import (
    DeliveryInput,
    DeliveryMoveInput,
    InvoiceInput,
)


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
