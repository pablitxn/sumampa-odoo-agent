"""Unit tests for settings validation and environment overrides."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from sumampa_odoo_agent.config import AppSettings, load_settings, resolve_environment


def _write_base_config(config_dir: Path) -> None:
    config_dir.mkdir()
    (config_dir / "appsettings.json").write_text(
        json.dumps(
            {
                "service": {"name": "sumampa-test", "version": "0.1.0"},
                "odoo": {"mode": "dry-run", "timeout_seconds": 15.0},
                "agent": {"mode": "disabled"},
                "session_store": {"mode": "memory"},
            }
        ),
        encoding="utf-8",
    )


def test_settings_reject_unknown_modes() -> None:
    with pytest.raises(PydanticValidationError):
        AppSettings.model_validate(
            {
                "service": {"name": "sumampa-test", "version": "0.1.0"},
                "odoo": {"mode": "xmlrpc"},
            }
        )


def test_resolve_environment_uses_python_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHON_ENV", "integration")

    assert resolve_environment() == "integration"


def test_load_settings_applies_declarative_environment_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _write_base_config(config_dir)

    monkeypatch.setenv("ODOO_MODE", "jsonrpc")
    monkeypatch.setenv("ODOO_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("SESSION_STORE_MODE", "hybrid")
    monkeypatch.setenv("SESSION_STORE_REDIS_TTL_SECONDS", "120")
    monkeypatch.setenv("OBSERVABILITY_MODE", "phoenix")
    monkeypatch.setenv("OBSERVABILITY_SAMPLE_RATE", "0.5")
    monkeypatch.setenv("OBSERVABILITY_FLUSH_ON_SHUTDOWN", "false")
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://phoenix.local:6006")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix.local:6006/v1/traces")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "sumampa-test")
    monkeypatch.setenv("PHOENIX_API_KEY_ENV_VAR", "SUMAMPA_PHOENIX_API_KEY")
    monkeypatch.setenv("TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_SERVICE_NAME", "sumampa-odoo-agent")
    monkeypatch.setenv("TELEMETRY_ENVIRONMENT", "production")
    monkeypatch.setenv("TELEMETRY_CLUSTER", "production")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.orchid-labs.xyz:443")

    settings = load_settings(config_dir=config_dir, env="test")

    assert settings.odoo.mode == "jsonrpc"
    assert settings.odoo.timeout_seconds == 7.5
    assert settings.session_store.mode == "hybrid"
    assert settings.session_store.redis_ttl_seconds == 120
    assert settings.observability.mode == "phoenix"
    assert settings.observability.sample_rate == 0.5
    assert settings.observability.flush_on_shutdown is False
    assert settings.observability.base_url == "http://phoenix.local:6006"
    assert settings.observability.collector_endpoint == "http://phoenix.local:6006/v1/traces"
    assert settings.observability.project_name == "sumampa-test"
    assert settings.observability.api_key_env_var == "SUMAMPA_PHOENIX_API_KEY"
    assert settings.telemetry.enabled is True
    assert settings.telemetry.service_name == "sumampa-odoo-agent"
    assert settings.telemetry.environment == "production"
    assert settings.telemetry.cluster == "production"
    assert settings.telemetry.otlp_endpoint == "https://otel.orchid-labs.xyz:443"


def test_settings_reject_langfuse_mode() -> None:
    with pytest.raises(PydanticValidationError):
        AppSettings.model_validate(
            {
                "service": {"name": "sumampa-test", "version": "0.1.0"},
                "observability": {"mode": "langfuse"},
            }
        )
