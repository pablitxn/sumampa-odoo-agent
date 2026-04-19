"""Shared fixtures for integration tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = Path(__file__).parent
PURCHASE_INVOICE_FIXTURES_DIR = INTEGRATION_ROOT / "fixtures" / "purchase_invoices"
PURCHASE_INVOICE_SNAPSHOTS_DIR = INTEGRATION_ROOT / "fixtures" / "purchase_invoice_extractions"


def _load_api_key_from_project_env() -> str | None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "OPENAI_API_KEY":
            return value.strip().strip("\"'")
    return None


@pytest.fixture(scope="session")
def openai_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or _load_api_key_from_project_env()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY es obligatoria para los tests de integracion con OpenAI."
        )
    os.environ.setdefault("OPENAI_API_KEY", api_key)
    return api_key


@pytest.fixture(scope="session")
def purchase_invoice_fixtures_dir() -> Path:
    return PURCHASE_INVOICE_FIXTURES_DIR


@pytest.fixture(scope="session")
def purchase_invoice_snapshots_dir() -> Path:
    return PURCHASE_INVOICE_SNAPSHOTS_DIR


@pytest.fixture(scope="session")
def odoo19_env() -> dict[str, str]:
    if os.environ.get("RUN_ODOO19_INTEGRATION") != "1":
        pytest.skip("Seteá RUN_ODOO19_INTEGRATION=1 para correr contra Odoo 19 local.")

    env = os.environ.copy()
    env.setdefault("ORCHID_ODOO_BASE_URL", "http://127.0.0.1:8069")
    env.setdefault("ORCHID_ODOO_DATABASE", "sumampa_integration")
    env.setdefault("ORCHID_ODOO_USERNAME", "admin")
    env.setdefault("ORCHID_ODOO_PASSWORD", "admin")
    env.setdefault("ODOO_MASTER_PASSWORD", "")
    env.setdefault("ORCHID_ODOO_TIMEOUT_SECONDS", "30")

    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "bootstrap_odoo_integration.py")],
        cwd=PROJECT_ROOT,
        check=True,
        env=env,
    )
    return env
