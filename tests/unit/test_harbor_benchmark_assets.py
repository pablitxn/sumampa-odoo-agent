from __future__ import annotations

import importlib.util
import json
import os
import tomllib
from pathlib import Path
from types import ModuleType

TASK_ROOT = (
    Path(__file__).resolve().parents[2]
    / "benchmarks/harbor/sumampa-odoo-fullstack/search-seeded-supplier"
)
EXPECTED_REWARD_KEYS = {
    "task_success",
    "odoo_payload_valid",
    "grounded_in_tool_result",
    "missing_data_handled",
    "communication_quality",
    "needs_human_review",
    "latency_ms",
    "error",
}


def test_harbor_task_layout_and_metadata() -> None:
    assert (TASK_ROOT / "instruction.md").exists()
    assert (TASK_ROOT / "environment/Dockerfile").exists()
    assert (TASK_ROOT / "environment/docker-compose.yaml").exists()
    assert (TASK_ROOT / "solution/solve.sh").exists()
    assert (TASK_ROOT / "tests/test.sh").exists()
    assert (TASK_ROOT / "tests/verify.py").exists()
    assert os.access(TASK_ROOT / "solution/solve.sh", os.X_OK)
    assert os.access(TASK_ROOT / "tests/test.sh", os.X_OK)

    task = tomllib.loads((TASK_ROOT / "task.toml").read_text(encoding="utf-8"))
    assert task["task"]["name"] == "sumampa/odoo-fullstack-search-seeded-supplier"
    assert task["environment"]["workdir"] == "/app"
    assert task["verifier"]["env"]["SUMAMPA_API_BASE_URL"] == "http://sumampa-app:8000"


def test_harbor_compose_declares_required_sidecars() -> None:
    compose = (TASK_ROOT / "environment/docker-compose.yaml").read_text(encoding="utf-8")

    assert "sumampa-app:" in compose
    assert "odoo19:" in compose
    assert "odoo-postgres:" in compose
    assert "PHOENIX_COLLECTOR_ENDPOINT" in compose


def test_harbor_fixtures_and_reward_schema_are_numeric() -> None:
    request = json.loads((TASK_ROOT / "tests/fixtures/request.json").read_text(encoding="utf-8"))
    expected = json.loads((TASK_ROOT / "tests/fixtures/expected.json").read_text(encoding="utf-8"))
    verifier = _load_verifier_module()

    reward = verifier._empty_reward(error=1.0)

    assert request["conversation_id"] == "harbor-search-seeded-supplier"
    assert "JAMBO" in request["text"]
    assert expected["required_terms"] == ["JAMBO", "30644193078"]
    assert set(reward) == EXPECTED_REWARD_KEYS
    assert all(isinstance(value, int | float) for value in reward.values())


def _load_verifier_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sumampa_harbor_verify",
        TASK_ROOT / "tests/verify.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
