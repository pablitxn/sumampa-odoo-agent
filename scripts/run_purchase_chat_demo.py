"""Reset local Odoo integration data and launch the purchase chat demo."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESET_SCRIPT = REPO_ROOT / "scripts" / "reset_odoo_integration.py"
DEMO_URL = "http://127.0.0.1:8000/demo/purchase-invoices"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-reset",
        action="store_true",
        help="No reiniciar ni reseedear Odoo; sólo levantar la API demo.",
    )
    parser.add_argument(
        "--soft-reset",
        action="store_true",
        help="Rebootstrapear el stack actual sin bajar volúmenes.",
    )
    parser.add_argument(
        "--preserve-memory",
        action="store_true",
        help="Conservar la memoria local de resoluciones humanas.",
    )
    parser.add_argument(
        "--session-store-mode",
        default="memory",
        choices=("memory", "hybrid"),
        help="Modo de persistencia de sesiones para la API demo.",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Levantar la API sin autoreload.",
    )
    args = parser.parse_args()

    if not args.skip_reset:
        reset_command = [sys.executable, str(RESET_SCRIPT), "--skip-describe"]
        if args.soft_reset:
            reset_command.append("--soft")
        if args.preserve_memory:
            reset_command.append("--preserve-memory")
        _run(reset_command, env=os.environ.copy())

    env = os.environ.copy()
    env["ORCHID_ENV"] = "integration"
    env.setdefault("ORCHID_SESSION_STORE_MODE", args.session_store_mode)
    env["PYTHONPATH"] = _pythonpath_with_src(env.get("PYTHONPATH"))

    print(f"Demo lista en {DEMO_URL}")
    print("Cortá con Ctrl+C cuando termines.")

    command = [sys.executable, "-m", "sumampa_odoo_agent.main"]
    if not args.no_reload:
        command.append("--reload")
    return subprocess.run(command, cwd=REPO_ROOT, env=env, check=False).returncode


def _run(command: list[str], *, env: dict[str, str]) -> None:
    print(f"$ {shlex.join(command)}")
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=env)


def _pythonpath_with_src(current: str | None) -> str:
    src_path = str(REPO_ROOT / "src")
    if not current:
        return src_path
    parts = [part for part in current.split(os.pathsep) if part]
    if src_path in parts:
        return current
    return os.pathsep.join([src_path, *parts])


if __name__ == "__main__":
    raise SystemExit(main())
