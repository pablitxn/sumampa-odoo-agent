"""Run local Harbor full-stack benchmarks and upload rewards to Phoenix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts.curate_phoenix_datasets import _span_row_to_trace
    from scripts.phoenix_eval_utils import build_phoenix_client
else:
    try:
        from scripts.curate_phoenix_datasets import _span_row_to_trace
        from scripts.phoenix_eval_utils import build_phoenix_client
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from curate_phoenix_datasets import _span_row_to_trace
        from phoenix_eval_utils import build_phoenix_client

from sumampa_odoo_agent.config import load_settings

DEFAULT_DATASET_PATH = Path("benchmarks/harbor/sumampa-odoo-fullstack")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--agent", default=os.environ.get("HARBOR_AGENT", "oracle"))
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--image", default=None)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-phoenix", action="store_true")
    parser.add_argument("--no-upload-phoenix", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("benchmark_runs/harbor"))
    parser.add_argument("--phoenix-base-url", default=os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006"))
    parser.add_argument(
        "--phoenix-collector-endpoint",
        default=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"),
    )
    parser.add_argument("--phoenix-project-name", default=os.environ.get("PHOENIX_PROJECT_NAME", "sumampa-odoo-agent"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    git_sha = _git_sha(repo_root)
    image = args.image or f"sumampa-odoo-agent:harbor-{git_sha}"
    run_dir = (repo_root / args.artifacts_dir / git_sha).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_build:
        _run(["docker", "build", "-t", image, "."], cwd=repo_root)
    if not args.skip_phoenix:
        _run(["docker", "compose", "--profile", "observability", "up", "-d", "phoenix"], cwd=repo_root)
        _wait_for_http(args.phoenix_base_url)

    harbor_env = os.environ.copy()
    harbor_env.update(
        {
            "SUMAMPA_APP_IMAGE": image,
            "GIT_SHA": git_sha,
            "AGENT_MODEL": args.model,
            "PHOENIX_BASE_URL": args.phoenix_base_url,
            "PHOENIX_COLLECTOR_ENDPOINT": args.phoenix_collector_endpoint,
            "PHOENIX_PROJECT_NAME": args.phoenix_project_name,
        }
    )
    harbor_cmd = _harbor_run_command(
        dataset_path=(repo_root / args.path).resolve(),
        agent=args.agent,
        model=args.model,
        artifacts_dir=run_dir,
        cwd=repo_root,
    )
    run_started_at = datetime.now(UTC)
    _run(harbor_cmd, cwd=repo_root, env=harbor_env)

    reward_paths = sorted(run_dir.rglob("reward.json"))
    if reward_paths:
        _write_reward_index(run_dir, reward_paths)
    if reward_paths and not args.no_upload_phoenix:
        _upload_rewards_to_phoenix(
            reward_paths,
            base_url=args.phoenix_base_url,
            project_name=args.phoenix_project_name,
            run_started_at=run_started_at,
        )
    print(f"Harbor run complete. Artifacts root: {run_dir}")


def _harbor_run_command(
    *,
    dataset_path: Path,
    agent: str,
    model: str,
    artifacts_dir: Path,
    cwd: Path,
) -> list[str]:
    cmd = ["harbor", "run", "-p", str(dataset_path), "-a", agent, "-m", model, "--env", "docker"]
    help_text = _harbor_run_help(cwd)
    if "--jobs-dir" in help_text:
        cmd.extend(["--jobs-dir", str(artifacts_dir)])
    elif "--output-dir" in help_text:
        cmd.extend(["--output-dir", str(artifacts_dir)])
    return cmd


def _harbor_run_help(cwd: Path) -> str:
    result = subprocess.run(
        ["harbor", "run", "--help"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return f"{result.stdout}\n{result.stderr}"


def _upload_rewards_to_phoenix(
    reward_paths: list[Path],
    *,
    base_url: str,
    project_name: str,
    run_started_at: datetime,
) -> None:
    settings = load_settings()
    settings = settings.model_copy(
        update={
            "observability": settings.observability.model_copy(
                update={"base_url": base_url, "project_name": project_name}
            )
        }
    )
    client = build_phoenix_client(settings)
    for reward_path in reward_paths:
        rewards = _read_json(reward_path)
        correlation = _read_correlation(reward_path)
        span_id = _find_conversation_span_id(
            client,
            project_name=project_name,
            conversation_id=str(correlation.get("conversation_id") or ""),
            run_started_at=run_started_at,
        )
        if not span_id:
            print(f"reward {reward_path} has no matching Phoenix span; skipping upload")
            continue
        for name, value in rewards.items():
            if not isinstance(value, int | float):
                continue
            metadata = {
                **correlation,
                "harbor.reward_path": str(reward_path),
                "source": "harbor",
            }
            client.spans.add_span_annotation(
                span_id=span_id,
                annotation_name=str(name),
                annotator_kind="CODE",
                score=float(value),
                explanation=f"Imported from Harbor reward {reward_path.name}.",
                metadata=metadata,
                sync=True,
            )
        print(f"uploaded Harbor rewards from {reward_path} to Phoenix span {span_id}")


def _find_conversation_span_id(
    client: Any,
    *,
    project_name: str,
    conversation_id: str,
    run_started_at: datetime,
) -> str | None:
    if not conversation_id:
        return None
    spans_df = client.spans.get_spans_dataframe(
        project_identifier=project_name,
        limit=500,
        root_spans_only=False,
        start_time=run_started_at,
    )
    matching_spans: list[dict[str, Any]] = []
    for _, row in spans_df.iterrows():
        span = _span_row_to_trace(row.to_dict())
        if span.get("session_id") == conversation_id and span.get("name") == "conversation.turn":
            matching_spans.append(span)
    matching_spans.sort(key=lambda span: str(span.get("timestamp") or ""))
    if not matching_spans:
        return None
    return str(matching_spans[-1].get("span_id") or "")


def _write_reward_index(run_dir: Path, reward_paths: list[Path]) -> None:
    index = [
        {
            "reward_path": str(path),
            "reward": _read_json(path),
            "correlation": _read_correlation(path),
        }
        for path in reward_paths
    ]
    (run_dir / "reward-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _read_correlation(reward_path: Path) -> dict[str, Any]:
    for candidate in (
        reward_path.with_name("correlation.json"),
        reward_path.parent / "correlation.json",
        reward_path.parent.parent / "verifier" / "correlation.json",
    ):
        if candidate.exists():
            value = _read_json(candidate)
            return value if isinstance(value, dict) else {}
    return {}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_sha(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _wait_for_http(url: str) -> None:
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"Phoenix did not become healthy at {url}: {last_error}")


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


if __name__ == "__main__":
    main()
