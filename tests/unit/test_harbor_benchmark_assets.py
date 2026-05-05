from __future__ import annotations

import importlib.util
import json
import os
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from scripts.phoenix_eval_utils import SCORE_NAMES, numeric_reward_payload
from scripts.run_harbor_benchmarks import _container_reachable_url, _harbor_run_command

BENCHMARK_ROOT = Path(__file__).resolve().parents[2] / "benchmarks/harbor/sumampa-odoo-fullstack"
TASK_ROOTS = tuple(sorted(path for path in BENCHMARK_ROOT.iterdir() if path.is_dir()))
EXPECTED_SCENARIOS = {
    "search-seeded-supplier",
    "search-seeded-customer",
    "search-seeded-product",
    "validate-invoice-draft",
    "argentina-fiscal-warning",
    "validate-delivery-draft",
    "safe-create-product",
    "attachment-assisted-product-search",
}
EXPECTED_REWARD_KEYS = set(SCORE_NAMES)


def test_harbor_task_layout_and_metadata() -> None:
    assert {path.name for path in TASK_ROOTS} == EXPECTED_SCENARIOS

    for task_root in TASK_ROOTS:
        assert (task_root / "instruction.md").exists()
        assert (task_root / "environment/Dockerfile").exists()
        assert (task_root / "environment/docker-compose.yaml").exists()
        assert (task_root / "solution/solve.sh").exists()
        assert (task_root / "tests/test.sh").exists()
        assert (task_root / "tests/verify.py").exists()
        assert os.access(task_root / "solution/solve.sh", os.X_OK)
        assert os.access(task_root / "tests/test.sh", os.X_OK)

        task = tomllib.loads((task_root / "task.toml").read_text(encoding="utf-8"))
        assert task["task"]["name"] == f"sumampa/odoo-fullstack-{task_root.name}"
        assert task["environment"]["workdir"] == "/app"
        assert task["verifier"]["env"]["SUMAMPA_API_BASE_URL"] == "http://sumampa-app:8000"
        assert task["verifier"]["env"]["HARBOR_TASK_ID"] == task["task"]["name"]
        assert "LLM_JUDGE_MODEL" in task["verifier"]["env"]
        assert "ODOO_BASE_URL" in task["verifier"]["env"]


def test_harbor_compose_declares_required_sidecars() -> None:
    for task_root in TASK_ROOTS:
        compose = (task_root / "environment/docker-compose.yaml").read_text(encoding="utf-8")

        assert "sumampa-app:" in compose
        assert "odoo19:" in compose
        assert "odoo-postgres:" in compose
        assert "PHOENIX_COLLECTOR_ENDPOINT" in compose
        assert f"HARBOR_TASK_ID: sumampa/odoo-fullstack-{task_root.name}" in compose


def test_harbor_fixtures_and_reward_schema_are_numeric() -> None:
    for task_root in TASK_ROOTS:
        request = json.loads((task_root / "tests/fixtures/request.json").read_text(encoding="utf-8"))
        expected = json.loads((task_root / "tests/fixtures/expected.json").read_text(encoding="utf-8"))
        verifier = _load_verifier_module(task_root)

        reward = verifier._empty_reward(error=1.0)

        assert request["conversation_id"] == f"harbor-{task_root.name}"
        assert request["context"]["scenario"] == task_root.name
        assert expected["priority"] in {"p0", "p1", "p2"}
        assert isinstance(expected["llm_judge_required"], bool)
        assert isinstance(expected["required_terms"], list)
        assert set(reward) == EXPECTED_REWARD_KEYS
        assert numeric_reward_payload(reward) == reward
        assert all(isinstance(value, int | float) for value in reward.values())


def test_harbor_verifier_matches_user_facing_aliases_and_formatted_ids() -> None:
    verifier = _load_verifier_module(BENCHMARK_ROOT / "search-seeded-customer")

    assert verifier._contains_all("CUIT 30-00000000-0", ["30000000000"]) == 1.0
    assert (
        verifier._contains_all(
            "Missing required data: Operation type and Source location.",
            ["picking_type_id|operation type", "location_id|source location"],
        )
        == 1.0
    )


def test_harbor_reward_schema_rejects_non_numeric_values() -> None:
    reward: dict[str, object] = {name: 1.0 for name in SCORE_NAMES}
    reward["task_success"] = "1.0"

    try:
        numeric_reward_payload(reward)
    except TypeError as exc:
        assert "task_success" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("numeric_reward_payload accepted a string score")


def test_harbor_wrapper_runs_non_interactively(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_help(cwd: Path) -> str:
        del cwd
        return "--yes\n--jobs-dir\n"

    monkeypatch.setattr("scripts.run_harbor_benchmarks._harbor_run_help", fake_help)

    command = _harbor_run_command(
        dataset_path=BENCHMARK_ROOT,
        agent="oracle",
        model="gpt-5.4-mini",
        artifacts_dir=tmp_path,
        cwd=BENCHMARK_ROOT,
    )

    assert "--yes" in command
    assert command[command.index("--jobs-dir") + 1] == str(tmp_path)


def test_harbor_wrapper_rewrites_local_phoenix_urls_for_task_containers() -> None:
    assert _container_reachable_url("http://localhost:6006/v1/traces") == (
        "http://host.docker.internal:6006/v1/traces"
    )
    assert _container_reachable_url("http://127.0.0.1:6006") == (
        "http://host.docker.internal:6006"
    )
    assert _container_reachable_url("http://phoenix:6006") == "http://phoenix:6006"


def _load_verifier_module(task_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"sumampa_harbor_verify_{task_root.name.replace('-', '_')}",
        task_root / "tests/verify.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
