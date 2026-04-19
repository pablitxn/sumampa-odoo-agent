"""Load versioned message catalogs from the application package."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

MESSAGE_SPECS_ROOT = Path(__file__).resolve().parent


def resolve_message_catalog_path(catalog_path: str) -> Path:
    candidate = (MESSAGE_SPECS_ROOT / catalog_path).resolve()
    if not str(candidate).startswith(str(MESSAGE_SPECS_ROOT)):
        raise ValueError(f"Invalid message catalog path outside root: {catalog_path}")
    if not candidate.exists():
        raise FileNotFoundError(f"Missing message catalog: {catalog_path}")
    return candidate


@cache
def load_message_catalog(catalog_path: str) -> dict[str, str]:
    payload = json.loads(resolve_message_catalog_path(catalog_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Message catalog must be a JSON object: {catalog_path}")
    return {str(key): str(value) for key, value in payload.items()}


def render_message(catalog_path: str, key: str, **context: object) -> str:
    catalog = load_message_catalog(catalog_path)
    if key not in catalog:
        raise KeyError(f"Missing message key '{key}' in catalog '{catalog_path}'")
    return catalog[key].format(**context)
