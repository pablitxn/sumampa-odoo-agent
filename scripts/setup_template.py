#!/usr/bin/env python3
"""Interactive setup script for selecting/removing template modules.

This script reads `template/module-manifest.json`, asks which optional modules
should be enabled, resolves dependencies, writes `config/enabled_modules.json`,
and can optionally remove paths for disabled modules.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_PATH = Path("template/module-manifest.json")
ENABLED_MODULES_PATH = Path("config/enabled_modules.json")
APPSETTINGS_PATH = Path("config/appsettings.json")
DOCKER_COMPOSE_PATH = Path("docker-compose.yml")

RESOURCE_KEYS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "postgres": ("postgres",),
    "redis": ("redis",),
    "blob": ("minio", "r2", "multi_bucket"),
    "mongodb": ("mongodb",),
    "qdrant": ("qdrant",),
    "rabbitmq": ("rabbitmq",),
}

RESOURCE_DEFAULTS: dict[str, dict[str, Any] | None] = {
    "postgres": {
        "dsn": '',
        "min_pool_size": 1,
        "max_pool_size": 10,
        "command_timeout_seconds": 30.0,
    },
    "redis": {
        "url": "redis://localhost:6379/0",
        "key_prefix": "sumampa_odoo_agent",
        "default_ttl_seconds": 3600,
        "decode_responses": True,
    },
    "minio": {
        "endpoint": "localhost:9000",
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "bucket": "sumampa-odoo-agent",
        "create_bucket_if_missing": True,
        "secure": False,
    },
    "r2": None,
    "multi_bucket": None,
    "mongodb": {
        "uri": "mongodb://localhost:27017",
        "database": "sumampa_odoo_agent",
        "server_selection_timeout_ms": 2000,
        "connect_timeout_ms": 2000,
        "ping_timeout_seconds": 2.0,
    },
    "qdrant": {
        "host": "localhost",
        "port": 6333,
        "grpc_port": 6334,
        "use_ssl": False,
        "timeout_seconds": 10.0,
        "prefer_grpc": False,
        "collection_prefix": "sumampa_odoo_agent",
    },
    "rabbitmq": {
        "url": "amqp://guest:guest@localhost:5672/",
        "prefetch_count": 50,
        "connect_timeout_seconds": 10.0,
        "heartbeat_seconds": 60,
        "publisher_confirms": True,
    },
}

OBSERVABILITY_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "sample_rate": 1.0,
    "langfuse": {"enabled": False},
}

MODULE_IMPORT_CHECKS: dict[str, tuple[str, ...]] = {
    "postgres": ("asyncpg",),
    "redis": ("redis.asyncio",),
    "blob": ("minio",),
    "mongodb": ("motor.motor_asyncio",),
    "qdrant": ("qdrant_client",),
    "rabbitmq": ("aio_pika",),
    "observability": (
        "prometheus_client",
        "opentelemetry.sdk",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        "langfuse",
    ),
}

MODULE_INSTALL_HINTS: dict[str, str] = {
    "postgres": "uv sync --extra db (or --extra sql)",
    "redis": "uv sync --extra db (or --extra redis)",
    "blob": "uv sync --extra blob",
    "mongodb": "uv sync --extra db (or --extra mongodb)",
    "qdrant": "uv sync --extra db (or --extra qdrant)",
    "rabbitmq": "uv sync --extra db (or --extra rabbitmq)",
    "observability": "uv sync --extra observability",
}

DOCKER_SERVICE_SNIPPETS: dict[str, list[str]] = {
    "postgres": [
        "  postgres:",
        "    image: postgres:16",
        "    container_name: sumampa-odoo-agent-postgres",
        "    environment:",
        "      POSTGRES_DB: ${POSTGRES_DB:-sumampa_odoo_agent}",
        "      POSTGRES_USER: ${POSTGRES_USER:-orchid}",
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-orchid}",
        "    ports:",
        '      - "5432:5432"',
        "    volumes:",
        "      - postgres_data:/var/lib/postgresql/data",
        "    healthcheck:",
        '      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-orchid} -d ${POSTGRES_DB:-sumampa_odoo_agent}"]',
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 10",
    ],
    "redis": [
        "  redis:",
        "    image: redis:7",
        "    container_name: sumampa-odoo-agent-redis",
        "    ports:",
        '      - "6379:6379"',
        '    command: ["redis-server", "--appendonly", "yes"]',
        "    volumes:",
        "      - redis_data:/data",
        "    healthcheck:",
        '      test: ["CMD", "redis-cli", "ping"]',
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 10",
    ],
    "mongodb": [
        "  mongodb:",
        "    image: mongo:7",
        "    container_name: sumampa-odoo-agent-mongodb",
        "    ports:",
        '      - "27017:27017"',
        "    volumes:",
        "      - mongodb_data:/data/db",
    ],
    "qdrant": [
        "  qdrant:",
        "    image: qdrant/qdrant:v1.13.2",
        "    container_name: sumampa-odoo-agent-qdrant",
        "    ports:",
        '      - "6333:6333"',
        '      - "6334:6334"',
        "    volumes:",
        "      - qdrant_data:/qdrant/storage",
    ],
    "rabbitmq": [
        "  rabbitmq:",
        "    image: rabbitmq:3.13-management",
        "    container_name: sumampa-odoo-agent-rabbitmq",
        "    ports:",
        '      - "5672:5672"',
        '      - "15672:15672"',
        "    volumes:",
        "      - rabbitmq_data:/var/lib/rabbitmq",
        "    healthcheck:",
        '      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]',
        "      interval: 10s",
        "      timeout: 5s",
        "      retries: 10",
    ],
    "blob": [
        "  minio:",
        "    image: minio/minio:RELEASE.2025-01-20T14-49-07Z",
        "    container_name: sumampa-odoo-agent-minio",
        "    command: server /data --console-address ':9001'",
        "    environment:",
        "      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minioadmin}",
        "      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-minioadmin}",
        "    ports:",
        '      - "9000:9000"',
        '      - "9001:9001"',
        "    volumes:",
        "      - minio_data:/data",
    ],
}

DOCKER_VOLUME_NAMES_BY_MODULE: dict[str, tuple[str, ...]] = {
    "postgres": ("postgres_data",),
    "redis": ("redis_data",),
    "mongodb": ("mongodb_data",),
    "qdrant": ("qdrant_data",),
    "rabbitmq": ("rabbitmq_data",),
    "blob": ("minio_data",),
}

DOCKER_MODULE_ORDER: tuple[str, ...] = (
    "postgres",
    "redis",
    "mongodb",
    "qdrant",
    "rabbitmq",
    "blob",
)


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    name: str
    required: bool
    description: str
    depends_on: tuple[str, ...]
    prune_paths: tuple[str, ...]


def _normalize_prune_paths(module_name: str, raw_paths: Any) -> tuple[str, ...]:
    if raw_paths is None:
        return ()
    if not isinstance(raw_paths, list):
        raise ValueError(
            f"Invalid manifest: module '{module_name}' has non-list prune_paths"
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(
                f"Invalid manifest: module '{module_name}' has invalid prune path '{raw_path}'"
            )
        candidate = str(PurePosixPath(raw_path.strip().replace("\\", "/")))
        pure_path = PurePosixPath(candidate)
        if candidate == "." or pure_path.is_absolute():
            raise ValueError(
                f"Invalid manifest: module '{module_name}' has absolute/invalid prune path '{raw_path}'"
            )
        if any(part == ".." for part in pure_path.parts):
            raise ValueError(
                f"Invalid manifest: module '{module_name}' prune path escapes repository '{raw_path}'"
            )
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return tuple(normalized)


def _resource_default(key: str) -> dict[str, Any] | None:
    return deepcopy(RESOURCE_DEFAULTS.get(key))


def _resource_value_for_selected(resources: dict[str, Any], key: str) -> Any:
    existing = resources.get(key)
    if existing is not None:
        return existing
    return _resource_default(key)


def _sync_observability_config(enabled_modules: set[str], data: dict[str, Any]) -> None:
    existing = data.get("observability")
    existing_dict = existing if isinstance(existing, dict) else {}

    merged = deepcopy(OBSERVABILITY_DEFAULTS)
    merged.update(existing_dict)

    existing_langfuse = existing_dict.get("langfuse")
    merged_langfuse = deepcopy(OBSERVABILITY_DEFAULTS["langfuse"])
    if isinstance(existing_langfuse, dict):
        merged_langfuse.update(existing_langfuse)
    merged["langfuse"] = merged_langfuse

    if "observability" not in enabled_modules:
        merged["enabled"] = False
        merged_langfuse["enabled"] = False

    data["observability"] = merged


def find_missing_optional_dependencies(
    enabled_modules: set[str],
) -> dict[str, tuple[str, ...]]:
    missing: dict[str, tuple[str, ...]] = {}

    def _is_import_available(import_path: str) -> bool:
        try:
            return find_spec(import_path) is not None
        except ModuleNotFoundError:
            return False

    for module_name in sorted(enabled_modules):
        import_paths = MODULE_IMPORT_CHECKS.get(module_name, ())
        missing_for_module = tuple(
            path
            for path in import_paths
            if not _is_import_available(path)
        )
        if missing_for_module:
            missing[module_name] = missing_for_module
    return missing


def print_dependency_diagnostics(
    missing_dependencies: dict[str, tuple[str, ...]],
    *,
    strict: bool,
) -> bool:
    if not missing_dependencies:
        return False

    print("")
    print("Dependency checks:")
    for module_name in sorted(missing_dependencies):
        missing_imports = ", ".join(missing_dependencies[module_name])
        install_hint = MODULE_INSTALL_HINTS.get(module_name)
        print(f"  - {module_name}: missing imports [{missing_imports}]")
        if install_hint:
            print(f"    install hint: {install_hint}")

    if strict:
        print("")
        print("Error: missing optional dependencies with --strict-deps enabled.")
        return True

    print("")
    print("Warning: continue anyway (use --strict-deps to fail fast).")
    return False


def load_manifest(path: Path) -> dict[str, ModuleDefinition]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    modules = raw.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise ValueError("Invalid manifest: missing non-empty 'modules' object")

    parsed: dict[str, ModuleDefinition] = {}
    claimed_prune_paths: dict[str, str] = {}
    for module_name, payload in modules.items():
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid manifest entry for module: {module_name}")

        depends_on = payload.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise ValueError(
                f"Invalid manifest: module '{module_name}' has non-list depends_on"
            )
        parsed_dependencies = tuple(str(item).strip() for item in depends_on)
        if any(not item for item in parsed_dependencies):
            raise ValueError(
                f"Invalid manifest: module '{module_name}' has empty dependency name"
            )

        prune_paths = _normalize_prune_paths(
            module_name,
            payload.get("prune_paths", []),
        )
        required = bool(payload.get("required", False))
        if required and prune_paths:
            raise ValueError(
                f"Invalid manifest: required module '{module_name}' cannot define prune_paths"
            )

        for prune_path in prune_paths:
            owner = claimed_prune_paths.get(prune_path)
            if owner is not None:
                raise ValueError(
                    "Invalid manifest: duplicate prune path "
                    f"'{prune_path}' in modules '{owner}' and '{module_name}'"
                )
            claimed_prune_paths[prune_path] = module_name

        parsed[module_name] = ModuleDefinition(
            name=module_name,
            required=required,
            description=str(payload.get("description", "")),
            depends_on=parsed_dependencies,
            prune_paths=prune_paths,
        )

    for module in parsed.values():
        for dependency in module.depends_on:
            if dependency not in parsed:
                raise ValueError(
                    f"Module '{module.name}' depends on unknown module '{dependency}'"
                )

    return parsed


def parse_modules_argument(raw: str | None, available: set[str]) -> set[str]:
    if raw is None:
        return set()
    selected = {token.strip() for token in raw.split(",") if token.strip()}
    unknown = selected - available
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown modules in --modules: {unknown_list}")
    return selected


def resolve_dependencies(
    selected: set[str], definitions: dict[str, ModuleDefinition]
) -> set[str]:
    resolved = set(selected)
    changed = True
    while changed:
        changed = False
        for module_name in list(resolved):
            for dep in definitions[module_name].depends_on:
                if dep not in resolved:
                    resolved.add(dep)
                    changed = True
    return resolved


def interactive_select(definitions: dict[str, ModuleDefinition]) -> set[str]:
    selected = {
        name
        for name, module in definitions.items()
        if module.required
    }
    optional = [name for name, module in definitions.items() if not module.required]

    print("Template setup: seleccion de modulos opcionales")
    for module_name in sorted(optional):
        module = definitions[module_name]
        prompt = f"Enable '{module_name}'? [y/N]: "
        answer = input(prompt).strip().lower()
        if answer in {"y", "yes", "s", "si"}:
            selected.add(module_name)
            print(f"  + {module_name}: {module.description}")
        else:
            print(f"  - {module_name}")

    return selected


def remove_path(path: Path, *, dry_run: bool) -> str:
    if not path.exists():
        return f"skip (missing): {path}"
    if dry_run:
        return f"would remove: {path}"
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return f"removed: {path}"


def prune_disabled_modules(
    disabled_modules: set[str],
    definitions: dict[str, ModuleDefinition],
    *,
    dry_run: bool,
) -> list[str]:
    actions: list[str] = []
    for module_name in sorted(disabled_modules):
        for raw_path in definitions[module_name].prune_paths:
            target = Path(raw_path)
            actions.append(remove_path(target, dry_run=dry_run))
    return actions


def write_enabled_modules(enabled: set[str], output_path: Path, *, dry_run: bool) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "enabled_modules": sorted(enabled),
    }

    if dry_run:
        print(f"[dry-run] would write {output_path}:")
        print(json.dumps(payload, indent=2))
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote: {output_path}")


def sync_appsettings_resources(
    enabled_modules: set[str],
    *,
    appsettings_path: Path,
    dry_run: bool,
) -> None:
    if not appsettings_path.exists():
        print(f"skip sync appsettings (missing): {appsettings_path}")
        return

    data = json.loads(appsettings_path.read_text(encoding="utf-8"))
    resources = data.get("resources")
    if not isinstance(resources, dict):
        resources = {}
        data["resources"] = resources

    managed_keys = {
        key for keys in RESOURCE_KEYS_BY_MODULE.values() for key in keys
    }
    selected_keys = {
        key
        for module_name in enabled_modules
        for key in RESOURCE_KEYS_BY_MODULE.get(module_name, ())
    }

    preserved = {k: v for k, v in resources.items() if k not in managed_keys}
    selected: dict[str, Any] = {}
    managed_order = tuple(
        dict.fromkeys(
            key
            for keys in RESOURCE_KEYS_BY_MODULE.values()
            for key in keys
        )
    )
    for key in managed_order:
        if key not in selected_keys:
            continue
        selected[key] = _resource_value_for_selected(resources, key)

    data["resources"] = {**preserved, **selected}
    _sync_observability_config(enabled_modules, data)

    if dry_run:
        selected_keys_list = ", ".join(sorted(selected)) if selected else "none"
        print(
            f"[dry-run] would sync resources/observability in {appsettings_path} "
            f"(resources: {selected_keys_list})"
        )
        return

    appsettings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Synced resources/observability in: {appsettings_path}")


def build_docker_compose(enabled_modules: set[str]) -> str:
    active_modules = [
        module_name
        for module_name in DOCKER_MODULE_ORDER
        if module_name in enabled_modules
    ]
    if not active_modules:
        return "services: {}\nvolumes: {}\n"

    lines: list[str] = ["services:"]
    for module_name in active_modules:
        lines.extend(DOCKER_SERVICE_SNIPPETS[module_name])
        lines.append("")
    if lines[-1] == "":
        lines.pop()

    volume_names: list[str] = []
    seen_volumes: set[str] = set()
    for module_name in active_modules:
        for volume_name in DOCKER_VOLUME_NAMES_BY_MODULE.get(module_name, ()):
            if volume_name in seen_volumes:
                continue
            seen_volumes.add(volume_name)
            volume_names.append(volume_name)

    if not volume_names:
        lines.append("volumes: {}")
        return "\n".join(lines) + "\n"

    lines.append("volumes:")
    for volume_name in volume_names:
        lines.append(f"  {volume_name}:")

    return "\n".join(lines) + "\n"


def sync_docker_compose(
    enabled_modules: set[str],
    *,
    compose_path: Path,
    dry_run: bool,
) -> None:
    content = build_docker_compose(enabled_modules)
    if dry_run:
        print(f"[dry-run] would sync {compose_path}")
        return
    compose_path.write_text(content, encoding="utf-8")
    print(f"Synced: {compose_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select template modules and optionally prune disabled modules.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help=f"Path to module manifest (default: {MANIFEST_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ENABLED_MODULES_PATH,
        help=f"Path to enabled modules file (default: {ENABLED_MODULES_PATH})",
    )
    parser.add_argument(
        "--modules",
        type=str,
        default=None,
        help="Comma-separated modules to enable (optional modules only, required modules are always included).",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove declared paths for disabled modules.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing/deleting files.",
    )
    parser.add_argument(
        "--no-sync-config",
        action="store_true",
        help="Do not sync config/appsettings.json resources with selected modules.",
    )
    parser.add_argument(
        "--no-sync-compose",
        action="store_true",
        help="Do not rewrite docker-compose.yml based on selected modules.",
    )
    parser.add_argument(
        "--strict-deps",
        action="store_true",
        help="Fail if optional Python dependencies for selected modules are missing.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    definitions = load_manifest(args.manifest)
    all_modules = set(definitions)
    required_modules = {name for name, module in definitions.items() if module.required}

    try:
        selected_by_flag = parse_modules_argument(args.modules, all_modules)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.modules is None:
        selected = interactive_select(definitions)
    else:
        selected = required_modules | selected_by_flag

    enabled = resolve_dependencies(selected, definitions)
    disabled = all_modules - enabled

    print("")
    print("Enabled modules:")
    for module_name in sorted(enabled):
        print(f"  - {module_name}")

    print("")
    print("Disabled modules:")
    for module_name in sorted(disabled):
        print(f"  - {module_name}")

    missing_dependencies = find_missing_optional_dependencies(enabled)
    should_fail = print_dependency_diagnostics(
        missing_dependencies,
        strict=args.strict_deps,
    )
    if should_fail:
        return 2

    print("")
    write_enabled_modules(enabled, args.output, dry_run=args.dry_run)

    if not args.no_sync_config:
        sync_appsettings_resources(
            enabled,
            appsettings_path=APPSETTINGS_PATH,
            dry_run=args.dry_run,
        )

    if not args.no_sync_compose:
        sync_docker_compose(
            enabled,
            compose_path=DOCKER_COMPOSE_PATH,
            dry_run=args.dry_run,
        )

    if args.prune:
        print("")
        print("Prune actions:")
        for action in prune_disabled_modules(disabled, definitions, dry_run=args.dry_run):
            print(f"  - {action}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
