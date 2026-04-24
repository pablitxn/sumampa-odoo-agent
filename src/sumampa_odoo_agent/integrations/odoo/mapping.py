"""Mapping helpers for Odoo wire values."""

from __future__ import annotations

from typing import Any


def normalize_odoo_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
        return {"id": value[0], "name": value[1]}
    return value
