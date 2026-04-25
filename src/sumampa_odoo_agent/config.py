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
AttachmentStoreMode = Literal["memory", "s3"]
LoggingFormat = Literal["json", "text"]
ObservabilityMode = Literal["disabled", "langfuse"]
ObservabilityCaptureMode = Literal["full"]


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


class AttachmentSettings(BaseModel):
    store_mode: AttachmentStoreMode = "s3"
    bucket_name: str = "sumampa-attachments"
    endpoint_url: str = "http://127.0.0.1:9000"
    access_key: str | None = None
    secret_key: str | None = None
    access_key_env_var: str = "ORCHID_ATTACHMENT_STORE_ACCESS_KEY"
    secret_key_env_var: str = "ORCHID_ATTACHMENT_STORE_SECRET_KEY"
    region_name: str = "us-east-1"
    key_prefix: str = "attachments"
    retention_ttl_seconds: int = Field(default=604800, ge=60)
    max_attachment_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_text_chars: int = Field(default=200_000, ge=1)
    max_pdf_pages: int = Field(default=5, ge=1, le=50)


class ObservabilitySettings(BaseModel):
    mode: ObservabilityMode = "disabled"
    environment: str = DEFAULT_ENV
    capture_mode: ObservabilityCaptureMode = "full"
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    public_key_env_var: str = "LANGFUSE_PUBLIC_KEY"
    secret_key_env_var: str = "LANGFUSE_SECRET_KEY"
    base_url: str = "http://localhost:3000"
    flush_on_shutdown: bool = True


class AppSettings(BaseModel):
    service: ServiceSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    odoo: OdooSettings = Field(default_factory=OdooSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    session_store: SessionStoreSettings = Field(default_factory=SessionStoreSettings)
    attachments: AttachmentSettings = Field(default_factory=AttachmentSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


def _coerce_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


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
    EnvOverride("ORCHID_ATTACHMENT_STORE_MODE", ("attachments", "store_mode")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_BUCKET", ("attachments", "bucket_name")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_ENDPOINT_URL", ("attachments", "endpoint_url")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_ACCESS_KEY", ("attachments", "access_key")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_SECRET_KEY", ("attachments", "secret_key")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_ACCESS_KEY_ENV_VAR", ("attachments", "access_key_env_var")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_SECRET_KEY_ENV_VAR", ("attachments", "secret_key_env_var")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_REGION", ("attachments", "region_name")),
    EnvOverride("ORCHID_ATTACHMENT_STORE_KEY_PREFIX", ("attachments", "key_prefix")),
    EnvOverride("ORCHID_ATTACHMENT_RETENTION_TTL_SECONDS", ("attachments", "retention_ttl_seconds"), int),
    EnvOverride("ORCHID_ATTACHMENT_MAX_BYTES", ("attachments", "max_attachment_bytes"), int),
    EnvOverride("ORCHID_ATTACHMENT_MAX_TEXT_CHARS", ("attachments", "max_text_chars"), int),
    EnvOverride("ORCHID_ATTACHMENT_MAX_PDF_PAGES", ("attachments", "max_pdf_pages"), int),
    EnvOverride("ORCHID_OBSERVABILITY_MODE", ("observability", "mode")),
    EnvOverride("ORCHID_OBSERVABILITY_ENVIRONMENT", ("observability", "environment")),
    EnvOverride("ORCHID_OBSERVABILITY_CAPTURE_MODE", ("observability", "capture_mode")),
    EnvOverride("ORCHID_OBSERVABILITY_SAMPLE_RATE", ("observability", "sample_rate"), float),
    EnvOverride("ORCHID_LANGFUSE_PUBLIC_KEY_ENV_VAR", ("observability", "public_key_env_var")),
    EnvOverride("ORCHID_LANGFUSE_SECRET_KEY_ENV_VAR", ("observability", "secret_key_env_var")),
    EnvOverride("ORCHID_LANGFUSE_BASE_URL", ("observability", "base_url")),
    EnvOverride(
        "ORCHID_OBSERVABILITY_FLUSH_ON_SHUTDOWN",
        ("observability", "flush_on_shutdown"),
        _coerce_bool,
    ),
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
