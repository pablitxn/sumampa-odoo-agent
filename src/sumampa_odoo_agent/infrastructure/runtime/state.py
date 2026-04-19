"""Runtime startup/shutdown lifecycle."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sumampa_odoo_agent.infrastructure.runtime.container import (
    ApplicationContainer,
    build_container,
)
from sumampa_odoo_agent.infrastructure.runtime.modules import (
    ModuleMetadata,
    load_enabled_modules,
    load_module_manifest,
    resolve_enabled_modules,
)
from sumampa_odoo_agent.infrastructure.runtime.settings import AppSettings, load_settings

CONFIG_DIR = Path("config")
DEFAULT_ENV = "development"


@dataclass(slots=True)
class RuntimeState:
    """Active runtime state."""

    settings: AppSettings
    enabled_modules: frozenset[str]
    module_manifest: dict[str, ModuleMetadata]
    container: ApplicationContainer
    environment: str


class _RuntimeHolder:
    state: RuntimeState | None = None


def resolve_environment(env: str | None = None) -> str:
    """Resolve target environment using ORCHID_ENV fallback."""
    if env:
        return env
    return os.environ.get("ORCHID_ENV", DEFAULT_ENV)


async def startup_runtime(*, env: str | None = None) -> RuntimeState:
    """Initialize settings, resources and container once."""
    existing = _RuntimeHolder.state
    if existing is not None:
        return existing

    environment = resolve_environment(env)
    settings = load_settings(config_dir=CONFIG_DIR, env=environment)

    module_manifest = load_module_manifest()
    selected_modules = load_enabled_modules()
    enabled_modules = resolve_enabled_modules(selected_modules, module_manifest)

    container = await build_container(
        settings=settings,
        enabled_modules=enabled_modules,
        module_manifest=module_manifest,
    )

    state = RuntimeState(
        settings=settings,
        enabled_modules=enabled_modules,
        module_manifest=module_manifest,
        container=container,
        environment=environment,
    )
    _RuntimeHolder.state = state
    return state


async def shutdown_runtime() -> None:
    """Shutdown resources and clear runtime holder."""
    state = _RuntimeHolder.state
    _RuntimeHolder.state = None
    if state is None:
        return


def get_runtime_state() -> RuntimeState:
    """Return active runtime state."""
    state = _RuntimeHolder.state
    if state is None:
        msg = "Runtime is not initialized. Call startup_runtime() first."
        raise RuntimeError(msg)
    return state


def get_runtime_container() -> ApplicationContainer:
    """Return application container from active runtime."""
    return get_runtime_state().container


def reset_runtime_state_for_tests() -> None:
    """Reset state holder for isolated tests."""
    _RuntimeHolder.state = None
