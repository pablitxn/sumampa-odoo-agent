"""Persistent memory for human-confirmed supplier and product resolutions."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sumampa_odoo_agent.services.models.odoo import PurchaseInvoiceProposalResult

DEFAULT_MEMORY_PATH = Path(".data/purchase_resolution_memory.json")


class PurchaseResolutionMemoryStore:
    """Small file-backed store for aliases confirmed by humans."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._payload: dict[str, list[dict[str, Any]]] = {
            "suppliers": [],
            "products": [],
        }
        if self._path is not None and self._path.exists():
            self._payload = json.loads(self._path.read_text(encoding="utf-8"))

    @classmethod
    def from_env(cls) -> PurchaseResolutionMemoryStore:
        raw_path = os.environ.get("ORCHID_PURCHASE_RESOLUTION_MEMORY_PATH")
        if raw_path:
            return cls(Path(raw_path))
        return cls(DEFAULT_MEMORY_PATH)

    def supplier_hints(
        self,
        *,
        supplier_name: str | None,
        supplier_vat: str | None,
    ) -> dict[int, dict[str, list[str]]]:
        normalized_name = _normalize_text(supplier_name or "")
        normalized_vat = _normalize_vat(supplier_vat or "")
        hints: dict[int, dict[str, list[str]]] = {}
        for entry in self._payload["suppliers"]:
            if not _supplier_entry_matches(
                entry=entry,
                normalized_name=normalized_name,
                normalized_vat=normalized_vat,
            ):
                continue
            partner_id = int(entry["partner_id"])
            supplier_bucket = hints.setdefault(partner_id, {"names": [], "vats": []})
            alias_name = str(entry.get("supplier_name") or "").strip()
            alias_vat = str(entry.get("supplier_vat") or "").strip()
            if alias_name and alias_name not in supplier_bucket["names"]:
                supplier_bucket["names"].append(alias_name)
            if alias_vat and alias_vat not in supplier_bucket["vats"]:
                supplier_bucket["vats"].append(alias_vat)
        return hints

    def product_hints(
        self,
        *,
        supplier_name: str | None,
        supplier_vat: str | None,
        description: str,
    ) -> dict[int, list[str]]:
        normalized_supplier_name = _normalize_text(supplier_name or "")
        normalized_supplier_vat = _normalize_vat(supplier_vat or "")
        normalized_description = _normalize_text(description)
        hints: dict[int, list[str]] = {}
        for entry in self._payload["products"]:
            if _normalize_text(entry.get("line_description") or "") != normalized_description:
                continue
            entry_name = _normalize_text(entry.get("supplier_name") or "")
            entry_vat = _normalize_vat(entry.get("supplier_vat") or "")
            if normalized_supplier_vat and entry_vat and entry_vat != normalized_supplier_vat:
                continue
            if normalized_supplier_name and entry_name and entry_name != normalized_supplier_name:
                continue
            product_id = int(entry["product_id"])
            bucket = hints.setdefault(product_id, [])
            alias = str(entry.get("line_description") or "").strip()
            if alias and alias not in bucket:
                bucket.append(alias)
        return hints

    def remember_proposal(self, proposal: PurchaseInvoiceProposalResult) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        supplier_resolution = proposal.supplier_resolution
        if supplier_resolution and supplier_resolution.selected_partner_id is not None:
            changed = self._remember_supplier_alias(
                partner_id=supplier_resolution.selected_partner_id,
                display_name=supplier_resolution.selected_display_name,
                vat=supplier_resolution.selected_vat,
                supplier_name=supplier_resolution.extracted_name,
                supplier_vat=supplier_resolution.extracted_vat,
            )
            if changed:
                operations.append(
                    {
                        "action": "remember",
                        "model": "purchase.resolution.supplier_alias",
                        "record_id": supplier_resolution.selected_partner_id,
                        "payload": {
                            "supplier_name": supplier_resolution.extracted_name,
                            "supplier_vat": supplier_resolution.extracted_vat,
                        },
                    }
                )

        for line in proposal.lines:
            product_resolution = line.product_resolution
            if product_resolution.selected_product_id is None:
                continue
            changed = self._remember_product_alias(
                product_id=product_resolution.selected_product_id,
                display_name=product_resolution.selected_display_name,
                default_code=product_resolution.selected_default_code,
                supplier_name=supplier_resolution.extracted_name if supplier_resolution else proposal.supplier_name,
                supplier_vat=supplier_resolution.extracted_vat if supplier_resolution else proposal.supplier_vat,
                line_description=line.description,
            )
            if changed:
                operations.append(
                    {
                        "action": "remember",
                        "model": "purchase.resolution.product_alias",
                        "record_id": product_resolution.selected_product_id,
                        "payload": {
                            "supplier_name": supplier_resolution.extracted_name
                            if supplier_resolution
                            else proposal.supplier_name,
                            "supplier_vat": supplier_resolution.extracted_vat
                            if supplier_resolution
                            else proposal.supplier_vat,
                            "line_description": line.description,
                        },
                    }
                )

        if operations:
            self._persist()
        return operations

    def _remember_supplier_alias(
        self,
        *,
        partner_id: int,
        display_name: str | None,
        vat: str | None,
        supplier_name: str | None,
        supplier_vat: str | None,
    ) -> bool:
        if not supplier_name and not supplier_vat:
            return False
        entry = {
            "partner_id": partner_id,
            "display_name": display_name,
            "vat": vat,
            "supplier_name": supplier_name,
            "supplier_vat": supplier_vat,
        }
        return self._upsert(
            bucket="suppliers",
            identity=(
                partner_id,
                _normalize_text(supplier_name or ""),
                _normalize_vat(supplier_vat or ""),
            ),
            entry=entry,
        )

    def _remember_product_alias(
        self,
        *,
        product_id: int,
        display_name: str | None,
        default_code: str | None,
        supplier_name: str | None,
        supplier_vat: str | None,
        line_description: str,
    ) -> bool:
        if not line_description:
            return False
        entry = {
            "product_id": product_id,
            "display_name": display_name,
            "default_code": default_code,
            "supplier_name": supplier_name,
            "supplier_vat": supplier_vat,
            "line_description": line_description,
        }
        return self._upsert(
            bucket="products",
            identity=(
                product_id,
                _normalize_text(supplier_name or ""),
                _normalize_vat(supplier_vat or ""),
                _normalize_text(line_description),
            ),
            entry=entry,
        )

    def _upsert(
        self,
        *,
        bucket: str,
        identity: tuple[Any, ...],
        entry: dict[str, Any],
    ) -> bool:
        rows = self._payload[bucket]
        for index, row in enumerate(rows):
            row_identity: tuple[Any, ...]
            if bucket == "suppliers":
                row_identity = (
                    int(row["partner_id"]),
                    _normalize_text(row.get("supplier_name") or ""),
                    _normalize_vat(row.get("supplier_vat") or ""),
                )
            else:
                row_identity = (
                    int(row["product_id"]),
                    _normalize_text(row.get("supplier_name") or ""),
                    _normalize_vat(row.get("supplier_vat") or ""),
                    _normalize_text(row.get("line_description") or ""),
                )
            if row_identity != identity:
                continue
            if row == entry:
                return False
            rows[index] = entry
            return True
        rows.append(entry)
        return True

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _supplier_entry_matches(
    *,
    entry: dict[str, Any],
    normalized_name: str,
    normalized_vat: str,
) -> bool:
    entry_name = _normalize_text(entry.get("supplier_name") or "")
    entry_vat = _normalize_vat(entry.get("supplier_vat") or "")
    if normalized_vat and entry_vat and entry_vat == normalized_vat:
        return True
    if normalized_name and entry_name and entry_name == normalized_name:
        return True
    return False


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    return " ".join(part for part in normalized.split() if part)


def _normalize_vat(value: str) -> str:
    return "".join(char for char in value if char.isdigit())
