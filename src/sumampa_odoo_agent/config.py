"""Application settings and environment resolution."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

DEFAULT_ENV = "development"
DEFAULT_CONFIG_DIR = Path("config")

OdooMode = Literal["dry-run", "jsonrpc"]
AgentMode = Literal["disabled", "openai"]
SessionStoreMode = Literal["memory", "hybrid"]
LoggingFormat = Literal["json", "text"]


@dataclass(frozen=True, slots=True)
class EnvOverride:
    env_var: str
    path: tuple[str, str]
    coerce: Callable[[str], object] = str


class ServiceSettings(BaseModel):
    name: str
    version: str
    host: str = "0.0.0.0"
    port: int = 8000


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: LoggingFormat = "json"


class OdooSettings(BaseModel):
    mode: OdooMode = "dry-run"
    base_url: str = "http://localhost:8069"
    database: str = "odoo"
    username: str = "admin"
    password: str = ""
    timeout_seconds: float = 15.0


class AgentSettings(BaseModel):
    mode: AgentMode = "disabled"
    model: str = "gpt-5.4-mini"
    api_key_env_var: str = "OPENAI_API_KEY"
    base_url: str | None = None
    system_prompt_override: str | None = None


class SessionStoreSettings(BaseModel):
    mode: SessionStoreMode = "memory"
    postgres_dsn: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_ttl_seconds: int = Field(default=86400, ge=60)
    redis_key_prefix: str = "sumampa:session"


class AppSettings(BaseModel):
    service: ServiceSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    odoo: OdooSettings = Field(default_factory=OdooSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    session_store: SessionStoreSettings = Field(default_factory=SessionStoreSettings)


_ENV_OVERRIDES: tuple[EnvOverride, ...] = (
    EnvOverride("ORCHID_AGENT_MODE", ("agent", "mode")),
    EnvOverride("ORCHID_AGENT_SYSTEM_PROMPT_OVERRIDE", ("agent", "system_prompt_override")),
    EnvOverride("ORCHID_ODOO_MODE", ("odoo", "mode")),
    EnvOverride("ORCHID_ODOO_BASE_URL", ("odoo", "base_url")),
    EnvOverride("ORCHID_ODOO_DATABASE", ("odoo", "database")),
    EnvOverride("ORCHID_ODOO_USERNAME", ("odoo", "username")),
    EnvOverride("ORCHID_ODOO_PASSWORD", ("odoo", "password")),
    EnvOverride("ORCHID_ODOO_TIMEOUT_SECONDS", ("odoo", "timeout_seconds"), float),
    EnvOverride("ORCHID_SESSION_STORE_MODE", ("session_store", "mode")),
    EnvOverride("ORCHID_SESSION_STORE_POSTGRES_DSN", ("session_store", "postgres_dsn")),
    EnvOverride("ORCHID_SESSION_STORE_REDIS_URL", ("session_store", "redis_url")),
    EnvOverride("ORCHID_SESSION_STORE_REDIS_TTL_SECONDS", ("session_store", "redis_ttl_seconds"), int),
    EnvOverride("ORCHID_SESSION_STORE_REDIS_KEY_PREFIX", ("session_store", "redis_key_prefix")),
)


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

    for override in _ENV_OVERRIDES:
        raw_value = os.environ.get(override.env_var)
        if raw_value:
            section, field_name = override.path
            section_updates = cast(dict[str, Any], updates.setdefault(section, {}))
            section_updates[field_name] = override.coerce(raw_value)

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
