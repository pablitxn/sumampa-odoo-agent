"""Reset and reseed the local Odoo 19 integration stack."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ODOO_COMPOSE_PROFILE = "odoo"
ODOO_SERVICES = ("odoo19", "odoo-postgres")
ODOO_VOLUMES = ("odoo19_postgres_data", "odoo19_data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--soft",
        action="store_true",
        help="Do not remove volumes; only bootstrap the current stack again.",
    )
    parser.add_argument(
        "--skip-describe",
        action="store_true",
        help="Do not print the final seeded environment summary.",
    )
    args = parser.parse_args()

    if not args.soft:
        _run(_compose("rm", "--stop", "--force", "--volumes", *ODOO_SERVICES))
        _remove_odoo_volumes()

    if not args.soft:
        _run(_compose("up", "-d", "odoo19"))

    _run([sys.executable, str(REPO_ROOT / "scripts" / "bootstrap_odoo_integration.py")])

    if not args.skip_describe:
        _run([sys.executable, str(REPO_ROOT / "scripts" / "describe_odoo_integration.py")])

    return 0


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "--profile", ODOO_COMPOSE_PROFILE, *args]


def _remove_odoo_volumes() -> None:
    project_name = _compose_project_name()
    for volume in ODOO_VOLUMES:
        _run(["docker", "volume", "rm", "--force", f"{project_name}_{volume}"], check=False)


def _compose_project_name() -> str:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    payload = json.loads(result.stdout)
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("Could not resolve docker compose project name")
    return name


def _run(command: list[str], *, check: bool = True) -> None:
    print(f"$ {shlex.join(command)}")
    subprocess.run(command, cwd=REPO_ROOT, check=check, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
