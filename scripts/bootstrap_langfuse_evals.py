"""Create baseline Langfuse datasets and score configs for Sumampa evals."""

from __future__ import annotations

import argparse
import os
from typing import Any

from langfuse import Langfuse

from sumampa_odoo_agent.config import AppSettings, load_settings

DATASETS: tuple[dict[str, Any], ...] = (
    {
        "name": "sumampa/dev/conversation-turns",
        "description": "Curated real and synthetic WhatsApp-style turns for conversational quality.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "conversation"},
    },
    {
        "name": "sumampa/dev/odoo-ops",
        "description": "Odoo operation tasks with deterministic dry-run expected outcomes.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "odoo"},
    },
    {
        "name": "sumampa/dev/regression-failures",
        "description": "Production or development failures promoted into regression evals.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "regression"},
    },
)

SCORE_CONFIGS: tuple[dict[str, Any], ...] = (
    {
        "name": "task_success",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "Whether the agent completed the user-visible task.",
    },
    {
        "name": "odoo_payload_valid",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "Whether Odoo payloads satisfy the expected schema and safety checks.",
    },
    {
        "name": "grounded_in_tool_result",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "Whether the response is grounded in observed Odoo/tool results.",
    },
    {
        "name": "missing_data_handled",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "Whether the agent asks for or explains missing required data.",
    },
    {
        "name": "communication_quality",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "Concise, clear Spanish response quality for WhatsApp operators.",
    },
    {
        "name": "needs_human_review",
        "data_type": "BOOLEAN",
        "description": "Whether the result should be read by a human before trusting the score.",
    },
    {
        "name": "latency_ms",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "description": "End-to-end task latency in milliseconds.",
    },
    {
        "name": "error",
        "data_type": "NUMERIC",
        "min_value": 0.0,
        "max_value": 1.0,
        "description": "1 when the turn or eval item raised an exception, otherwise 0.",
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=None, help="ORCHID_ENV-compatible config environment")
    args = parser.parse_args()

    settings = load_settings(env=args.env)
    client = _build_langfuse_client(settings)

    for dataset in DATASETS:
        _create_dataset(client, dataset)
    for score_config in SCORE_CONFIGS:
        _create_score_config(client, score_config)
    client.flush()


def _create_dataset(client: Langfuse, dataset: dict[str, Any]) -> None:
    try:
        client.create_dataset(**dataset)
        print(f"created dataset {dataset['name']}")
    except Exception as exc:
        print(f"dataset {dataset['name']} skipped or failed: {exc}")


def _create_score_config(client: Langfuse, score_config: dict[str, Any]) -> None:
    try:
        client.api.score_configs.create(**score_config)
        print(f"created score config {score_config['name']}")
    except Exception as exc:
        print(f"score config {score_config['name']} skipped or failed: {exc}")


def _build_langfuse_client(settings: AppSettings) -> Langfuse:
    return Langfuse(
        public_key=os.environ.get(settings.observability.public_key_env_var),
        secret_key=os.environ.get(settings.observability.secret_key_env_var),
        base_url=settings.observability.base_url,
        environment=settings.observability.environment,
    )


if __name__ == "__main__":
    main()
