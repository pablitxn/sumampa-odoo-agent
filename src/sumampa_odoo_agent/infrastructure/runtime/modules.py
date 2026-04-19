"""Module manifest and enabled-module helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENABLED_MODULES_PATH = Path("config/enabled_modules.json")
MODULE_MANIFEST_PATH = Path("template/module-manifest.json")


MODULE_RESOURCE_MAP: dict[str, tuple[str, ...]] = {
    "core": (),
    "odoo": (),
    "agent": (),
}


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Describes one module declared in manifest."""

    name: str
    description: str
    required: bool
    resources: tuple[str, ...]


def load_module_manifest(path: Path = MODULE_MANIFEST_PATH) -> dict[str, ModuleMetadata]:
    """Load module metadata from `template/module-manifest.json`."""
    env_path = os.environ.get("ORCHID_MODULE_MANIFEST_PATH")
    resolved_path = Path(env_path) if env_path else path
    if not resolved_path.exists():
        return {
            "core": ModuleMetadata(
                name="core",
                description="Base capability set",
                required=True,
                resources=MODULE_RESOURCE_MAP["core"],
            )
        }

    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    modules = data.get("modules", {})
    manifest: dict[str, ModuleMetadata] = {}
    for name, raw in modules.items():
        if not isinstance(raw, dict):
            continue
        manifest[name] = ModuleMetadata(
            name=name,
            description=str(raw.get("description", "")),
            required=bool(raw.get("required", False)),
            resources=MODULE_RESOURCE_MAP.get(name, ()),
        )
    if "core" not in manifest:
        manifest["core"] = ModuleMetadata(
            name="core",
            description="Base capability set",
            required=True,
            resources=MODULE_RESOURCE_MAP["core"],
        )
    return manifest


def load_enabled_modules(path: Path = ENABLED_MODULES_PATH) -> set[str]:
    """Load selected modules from `config/enabled_modules.json`."""
    env_path = os.environ.get("ORCHID_ENABLED_MODULES_PATH")
    resolved_path = Path(env_path) if env_path else path
    if not resolved_path.exists():
        return {"core"}

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    values = payload.get("enabled_modules")
    if not isinstance(values, list):
        return {"core"}
    selected = {str(item) for item in values}
    selected.add("core")
    return selected


def resolve_enabled_modules(
    selected: set[str], manifest: dict[str, ModuleMetadata]
) -> frozenset[str]:
    """Normalize selected modules against manifest and required entries."""
    resolved = set(selected) & set(manifest)
    required = {name for name, module in manifest.items() if module.required}
    resolved |= required
    return frozenset(resolved)


def required_resource_names(enabled_modules: frozenset[str]) -> list[str]:
    """Compute required resource names to be enforced at startup."""
    resources: set[str] = set()
    for module_name in enabled_modules:
        for resource in MODULE_RESOURCE_MAP.get(module_name, ()):
            resources.add(resource)
    return sorted(resources)
