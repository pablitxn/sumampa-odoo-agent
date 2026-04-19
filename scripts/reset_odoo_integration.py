"""Reset and reseed the local Odoo 19 integration stack."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.odoo19.yml"
DEFAULT_MEMORY_PATH = REPO_ROOT / ".data" / "purchase_resolution_memory.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--soft",
        action="store_true",
        help="No bajar volúmenes; sólo rebootstrapear el stack actual.",
    )
    parser.add_argument(
        "--preserve-memory",
        action="store_true",
        help="No borrar la memoria local de resoluciones humanas.",
    )
    parser.add_argument(
        "--skip-describe",
        action="store_true",
        help="No imprimir el resumen final del entorno seedado.",
    )
    args = parser.parse_args()

    if not args.soft:
        _run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "down",
                "-v",
                "--remove-orphans",
            ]
        )

    if not args.preserve_memory:
        memory_path = _resolution_memory_path()
        if memory_path.exists():
            memory_path.unlink()
            _prune_empty_parents(memory_path.parent)

    if not args.soft:
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])

    _run([sys.executable, str(REPO_ROOT / "scripts" / "bootstrap_odoo_integration.py")])

    if not args.skip_describe:
        _run([sys.executable, str(REPO_ROOT / "scripts" / "describe_odoo_integration.py")])

    return 0


def _run(command: list[str]) -> None:
    print(f"$ {shlex.join(command)}")
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=os.environ.copy())


def _resolution_memory_path() -> Path:
    raw_path = os.environ.get("ORCHID_PURCHASE_RESOLUTION_MEMORY_PATH")
    if not raw_path:
        return DEFAULT_MEMORY_PATH
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _prune_empty_parents(path: Path) -> None:
    current = path
    while current != REPO_ROOT and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


if __name__ == "__main__":
    raise SystemExit(main())
