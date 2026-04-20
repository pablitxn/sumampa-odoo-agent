"""Generate structured extraction snapshots from real purchase invoice fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from sumampa_odoo_agent.application.requests.odoo import AnalyzePurchaseInvoiceCommand
from sumampa_odoo_agent.infrastructure.extraction.service import OpenAIPurchaseInvoiceExtractor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "purchase_invoices"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "tests" / "integration" / "fixtures" / "purchase_invoice_extractions"
)


def _load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help="Directorio con imagenes de facturas.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directorio donde guardar snapshots JSON.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ORCHID_INVOICE_EXTRACTION_MODEL", "gpt-5.4"),
        help="Modelo de OpenAI para structured extraction.",
    )
    return parser


async def generate_snapshots(*, fixtures_dir: Path, output_dir: Path, model: str) -> None:
    _load_project_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY es obligatoria para generar snapshots.")

    extractor = OpenAIPurchaseInvoiceExtractor(
        model=model,
        api_key_env_var="OPENAI_API_KEY",
    )
    fixture_paths = _prepare_snapshot_paths(fixtures_dir=fixtures_dir, output_dir=output_dir)

    for fixture_path in fixture_paths:
        result = await extractor.extract(
            AnalyzePurchaseInvoiceCommand(
                filename=fixture_path.name,
                content_type="image/jpeg",
                image_bytes=_read_fixture_bytes(fixture_path),
            )
        )
        snapshot_path = output_dir / f"{fixture_path.stem}.json"
        _write_snapshot(
            snapshot_path,
            json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n",
        )
        print(f"snapshot generado: {snapshot_path}")


def _prepare_snapshot_paths(*, fixtures_dir: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return sorted(fixtures_dir.glob("*.jp*g"))


def _read_fixture_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _write_snapshot(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(
        generate_snapshots(
            fixtures_dir=args.fixtures_dir,
            output_dir=args.output_dir,
            model=args.model,
        )
    )


if __name__ == "__main__":
    main()
