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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--soft",
        action="store_true",
        help="No bajar volúmenes; sólo rebootstrapear el stack actual.",
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

    if not args.soft:
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])

    _run([sys.executable, str(REPO_ROOT / "scripts" / "bootstrap_odoo_integration.py")])

    if not args.skip_describe:
        _run([sys.executable, str(REPO_ROOT / "scripts" / "describe_odoo_integration.py")])

    return 0


def _run(command: list[str]) -> None:
    print(f"$ {shlex.join(command)}")
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
