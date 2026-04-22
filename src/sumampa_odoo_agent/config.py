"""Application settings and environment resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_ENV = "development"
DEFAULT_CONFIG_DIR = Path("config")


class ServiceSettings(BaseModel):
    name: str
    version: str
    host: str = "0.0.0.0"
    port: int = 8000


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: str = "json"


class OdooSettings(BaseModel):
    mode: str = "dry-run"
    base_url: str = "http://localhost:8069"
    database: str = "odoo"
    username: str = "admin"
    password: str = ""
    timeout_seconds: float = 15.0


class AgentSettings(BaseModel):
    mode: str = "disabled"
    model: str = "gpt-5.4-mini"
    api_key_env_var: str = "OPENAI_API_KEY"
    base_url: str | None = None
    system_prompt_spec: str = "agent/system.md"
    system_prompt_override: str | None = None


class InvoiceExtractionSettings(BaseModel):
    mode: str = "openai"
    model: str = "gpt-5.4"
    api_key_env_var: str = "OPENAI_API_KEY"
    base_url: str | None = None
    max_output_tokens: int = 3000
    prompt_spec: str = "invoice_extraction/purchase_invoice.md"


class SessionStoreSettings(BaseModel):
    mode: str = "memory"
    postgres_dsn: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_ttl_seconds: int = Field(default=86400, ge=60)
    redis_key_prefix: str = "sumampa:session"


class AppSettings(BaseModel):
    service: ServiceSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    odoo: OdooSettings = Field(default_factory=OdooSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    invoice_extraction: InvoiceExtractionSettings = Field(default_factory=InvoiceExtractionSettings)
    session_store: SessionStoreSettings = Field(default_factory=SessionStoreSettings)


def resolve_environment(env: str | None = None) -> str:
    """Resolve target environment using `ORCHID_ENV` as fallback."""

    if env:
        return env
    return os.environ.get("ORCHID_ENV", DEFAULT_ENV)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
            continue
        merged[key] = value
    return merged


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _apply_env_overrides(settings: AppSettings) -> AppSettings:
    updates: dict[str, Any] = {}

    invoice_mode = os.environ.get("ORCHID_INVOICE_EXTRACTION_MODE")
    if invoice_mode:
        updates.setdefault("invoice_extraction", {})["mode"] = invoice_mode

    invoice_model = os.environ.get("ORCHID_INVOICE_EXTRACTION_MODEL")
    if invoice_model:
        updates.setdefault("invoice_extraction", {})["model"] = invoice_model

    agent_mode = os.environ.get("ORCHID_AGENT_MODE")
    if agent_mode:
        updates.setdefault("agent", {})["mode"] = agent_mode

    agent_system_prompt_spec = os.environ.get("ORCHID_AGENT_SYSTEM_PROMPT_SPEC")
    if agent_system_prompt_spec:
        updates.setdefault("agent", {})["system_prompt_spec"] = agent_system_prompt_spec

    agent_system_prompt_override = os.environ.get("ORCHID_AGENT_SYSTEM_PROMPT_OVERRIDE")
    if agent_system_prompt_override:
        updates.setdefault("agent", {})["system_prompt_override"] = agent_system_prompt_override

    invoice_prompt_spec = os.environ.get("ORCHID_INVOICE_EXTRACTION_PROMPT_SPEC")
    if invoice_prompt_spec:
        updates.setdefault("invoice_extraction", {})["prompt_spec"] = invoice_prompt_spec

    odoo_mode = os.environ.get("ORCHID_ODOO_MODE")
    if odoo_mode:
        updates.setdefault("odoo", {})["mode"] = odoo_mode

    odoo_base_url = os.environ.get("ORCHID_ODOO_BASE_URL")
    if odoo_base_url:
        updates.setdefault("odoo", {})["base_url"] = odoo_base_url

    odoo_database = os.environ.get("ORCHID_ODOO_DATABASE")
    if odoo_database:
        updates.setdefault("odoo", {})["database"] = odoo_database

    odoo_username = os.environ.get("ORCHID_ODOO_USERNAME")
    if odoo_username:
        updates.setdefault("odoo", {})["username"] = odoo_username

    odoo_password = os.environ.get("ORCHID_ODOO_PASSWORD")
    if odoo_password:
        updates.setdefault("odoo", {})["password"] = odoo_password

    odoo_timeout_seconds = os.environ.get("ORCHID_ODOO_TIMEOUT_SECONDS")
    if odoo_timeout_seconds:
        updates.setdefault("odoo", {})["timeout_seconds"] = float(odoo_timeout_seconds)

    session_store_mode = os.environ.get("ORCHID_SESSION_STORE_MODE")
    if session_store_mode:
        updates.setdefault("session_store", {})["mode"] = session_store_mode

    session_store_postgres_dsn = os.environ.get("ORCHID_SESSION_STORE_POSTGRES_DSN")
    if session_store_postgres_dsn:
        updates.setdefault("session_store", {})["postgres_dsn"] = session_store_postgres_dsn

    session_store_redis_url = os.environ.get("ORCHID_SESSION_STORE_REDIS_URL")
    if session_store_redis_url:
        updates.setdefault("session_store", {})["redis_url"] = session_store_redis_url

    session_store_redis_ttl = os.environ.get("ORCHID_SESSION_STORE_REDIS_TTL_SECONDS")
    if session_store_redis_ttl:
        updates.setdefault("session_store", {})["redis_ttl_seconds"] = int(session_store_redis_ttl)

    session_store_redis_prefix = os.environ.get("ORCHID_SESSION_STORE_REDIS_KEY_PREFIX")
    if session_store_redis_prefix:
        updates.setdefault("session_store", {})["redis_key_prefix"] = session_store_redis_prefix

    if not updates:
        return settings
    return AppSettings.model_validate(_deep_merge(settings.model_dump(), updates))


def load_settings(
    *,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    env: str | None = None,
) -> AppSettings:
    """Load app settings from JSON files plus environment overrides."""

    _load_env_file(config_dir.parent / ".env")
    environment = resolve_environment(env)
    base_path = config_dir / "appsettings.json"
    env_path = config_dir / f"appsettings.{environment}.json"
    payload = json.loads(base_path.read_text(encoding="utf-8"))
    if env_path.exists():
        payload = _deep_merge(payload, json.loads(env_path.read_text(encoding="utf-8")))
    settings = AppSettings.model_validate(payload)
    return _apply_env_overrides(settings)
