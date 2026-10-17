"""Private credentials are checked only when a live backend is selected."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

import pytest

from sumampa_odoo_agent.config import AppSettings, load_settings
from sumampa_odoo_agent.integrations.odoo.factory import build_odoo_gateway
from sumampa_odoo_agent.integrations.sessions.factory import build_session_store
from sumampa_odoo_agent.services.errors import ConfigurationError


def settings() -> AppSettings:
    return load_settings(config_dir=Path("config"), env="local")


@pytest.mark.asyncio
async def test_memory_sessions_do_not_need_database_credentials() -> None:
    value = settings()
    value.session_store.mode = "memory"
    value.session_store.postgres_dsn = ""
    assert await build_session_store(value) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["", "   "])
async def test_hybrid_rejects_missing_private_dsn(missing: str) -> None:
    value = settings()
    value.session_store.mode = "hybrid"
    value.session_store.postgres_dsn = missing
    with pytest.raises(ConfigurationError, match="SESSION_STORE_POSTGRES_DSN"):
        await build_session_store(value)


def test_dry_run_does_not_need_odoo_credentials() -> None:
    value = settings()
    value.odoo.mode = "dry-run"
    value.odoo.password = ""
    assert build_odoo_gateway(value) is not None


@pytest.mark.parametrize("missing", ["", "   "])
def test_jsonrpc_rejects_missing_private_password(missing: str) -> None:
    value = settings()
    value.odoo.mode = "jsonrpc"
    value.odoo.password = missing
    with pytest.raises(ConfigurationError, match="ODOO_USERNAME"):
        build_odoo_gateway(value)


def test_private_env_overrides_resolve_after_base_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = secrets.token_urlsafe(24) + "@:/?#"
    dsn = f"postgresql+asyncpg://private:{quote(password, safe='')}@localhost/private"
    monkeypatch.setenv("SESSION_STORE_POSTGRES_DSN", dsn)
    monkeypatch.setenv("ODOO_PASSWORD", password)
    value = settings()
    assert value.session_store.postgres_dsn == dsn
    assert value.odoo.password == password


def test_base_configuration_has_no_reusable_credentials() -> None:
    value = settings()
    assert value.session_store.postgres_dsn == ""
    assert value.odoo.password == ""
    assert not value.attachments.access_key
    assert not value.attachments.secret_key
