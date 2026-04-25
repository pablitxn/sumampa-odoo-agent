"""Shared fixtures for integration tests."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = Path(__file__).parent
SESSION_STORE_POSTGRES_DSN = os.environ.get("SESSION_STORE_POSTGRES_DSN", "")
SESSION_STORE_REDIS_URL = "redis://127.0.0.1:6379/0"


@pytest.fixture(scope="session")
def odoo19_env() -> dict[str, str]:
    if os.environ.get("RUN_ODOO19_INTEGRATION") != "1":
        pytest.skip("Set RUN_ODOO19_INTEGRATION=1 to run against local Odoo 19.")

    env = os.environ.copy()
    env.setdefault("ODOO_BASE_URL", "http://127.0.0.1:8069")
    env.setdefault("ODOO_DATABASE", "sumampa_integration")
    env.setdefault("ODOO_USERNAME", "admin")
    env.setdefault("ODOO_PASSWORD", "")
    env.setdefault("ODOO_MASTER_PASSWORD", "")
    env.setdefault("ODOO_TIMEOUT_SECONDS", "30")

    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "bootstrap_odoo_integration.py")],
        cwd=PROJECT_ROOT,
        check=True,
        env=env,
    )
    return env


def _wait_for_tcp(host: str, port: int, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(
        f"Could not connect to {host}:{port} within {timeout_seconds}s"
    ) from last_error


@pytest.fixture(scope="session")
def session_store_env() -> dict[str, str]:
    if os.environ.get("RUN_SESSION_STORE_INTEGRATION") != "1":
        pytest.skip("Set RUN_SESSION_STORE_INTEGRATION=1 to run Postgres+Redis integration tests.")

    docker_info = subprocess.run(
        ["docker", "info"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if docker_info.returncode != 0:
        pytest.skip("Docker is not available for session store integration tests.")

    subprocess.run(
        ["docker", "compose", "up", "-d", "postgres", "redis"],
        cwd=PROJECT_ROOT,
        check=True,
    )
    _wait_for_tcp("127.0.0.1", 5432)
    _wait_for_tcp("127.0.0.1", 6379)

    return {
        "postgres_dsn": SESSION_STORE_POSTGRES_DSN,
        "redis_url": SESSION_STORE_REDIS_URL,
    }
