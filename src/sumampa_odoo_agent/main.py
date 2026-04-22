"""Service entrypoint for the HTTP API."""

from __future__ import annotations

import argparse

import uvicorn

from sumampa_odoo_agent.config import load_settings, resolve_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sumampa Odoo Agent service")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn autoreload in API mode",
    )
    return parser


def run_api(reload: bool) -> None:
    environment = resolve_environment()
    settings = load_settings(env=environment)
    uvicorn.run(
        "sumampa_odoo_agent.api.main:app",
        host=settings.service.host,
        port=settings.service.port,
        reload=reload,
    )


def main() -> None:
    args = build_parser().parse_args()
    run_api(reload=args.reload)


if __name__ == "__main__":
    main()
