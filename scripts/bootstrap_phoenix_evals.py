"""Create baseline Phoenix datasets for Sumampa evals."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.phoenix_eval_utils import DATASETS, build_phoenix_client
else:
    try:
        from scripts.phoenix_eval_utils import DATASETS, build_phoenix_client
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from phoenix_eval_utils import DATASETS, build_phoenix_client

from sumampa_odoo_agent.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=None, help="PYTHON_ENV-compatible config environment")
    args = parser.parse_args()

    settings = load_settings(env=args.env)
    client = build_phoenix_client(settings)
    for dataset in DATASETS:
        try:
            client.datasets.create_dataset(
                name=str(dataset["name"]),
                dataset_description=str(dataset["description"]),
                inputs=[],
                outputs=[],
                metadata=[],
            )
            print(f"created dataset {dataset['name']}")
        except Exception as exc:
            print(f"dataset {dataset['name']} skipped or failed: {exc}")


if __name__ == "__main__":
    main()
