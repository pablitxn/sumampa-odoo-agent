from __future__ import annotations

import json
import os
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LOG_ROOT = Path("/logs")
VERIFIER_DIR = LOG_ROOT / "verifier"
ARTIFACT_DIR = LOG_ROOT / "artifacts"
REQUEST_PATH = Path("/tests/fixtures/request.json")
EXPECTED_PATH = Path("/tests/fixtures/expected.json")
REWARD_PATH = VERIFIER_DIR / "reward.json"
CORRELATION_PATH = VERIFIER_DIR / "correlation.json"
VERIFIER_LOG_PATH = VERIFIER_DIR / "verifier.log"


def main() -> int:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        reward = _run_verifier()
    except Exception as exc:
        _write_json(ARTIFACT_DIR / "verifier_exception.json", {"error": traceback.format_exc()})
        reward = _empty_reward(error=1.0)
        _log(f"verifier failed: {exc.__class__.__name__}: {exc}")
    _write_json(REWARD_PATH, reward)
    return 0


def _run_verifier() -> dict[str, float]:
    request_payload = _read_json(REQUEST_PATH)
    expected = _read_json(EXPECTED_PATH)
    base_url = os.environ.get("SUMAMPA_API_BASE_URL", "http://sumampa-app:8000").rstrip("/")
    _write_json(ARTIFACT_DIR / "request.json", request_payload)
    _write_json(CORRELATION_PATH, _correlation_metadata(request_payload))

    wait_started = time.perf_counter()
    _wait_for_app(base_url)
    started = time.perf_counter()
    status_code, response_payload = _post_json(f"{base_url}/api/v1/messages", request_payload)
    latency_ms = (time.perf_counter() - started) * 1000
    _write_json(
        ARTIFACT_DIR / "response.json",
        {
            "status_code": status_code,
            "latency_ms": latency_ms,
            "payload": response_payload,
            "wait_ms": (started - wait_started) * 1000,
        },
    )

    assistant_text = _assistant_text(response_payload)
    http_ok = float(status_code == 200)
    response_shape = float(bool(assistant_text))
    required_terms = [str(term) for term in expected.get("required_terms", [])]
    forbidden_terms = [str(term) for term in expected.get("forbidden_terms", [])]
    required_ok = _contains_all(assistant_text, required_terms)
    forbidden_ok = not _contains_any(assistant_text, forbidden_terms)
    missing_score = _missing_data_score(assistant_text, expected.get("missing_fields", []))
    latency_score = float(latency_ms <= float(expected.get("max_latency_ms", 120000)))
    communication_score = _communication_quality(assistant_text)
    task_success = min(http_ok, response_shape, required_ok, float(forbidden_ok), latency_score)

    _log(
        f"status={status_code} latency_ms={latency_ms:0.1f} "
        f"task_success={task_success} assistant_text={assistant_text[:500]!r}"
    )
    return {
        "task_success": task_success,
        "odoo_payload_valid": response_shape,
        "grounded_in_tool_result": required_ok,
        "missing_data_handled": missing_score,
        "communication_quality": communication_score,
        "needs_human_review": float(min(task_success, communication_score, missing_score) < 0.75),
        "latency_ms": float(latency_ms),
        "error": 0.0 if http_ok else 1.0,
    }


def _wait_for_app(base_url: str) -> None:
    deadline = time.monotonic() + 180
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
        time.sleep(2)
    raise RuntimeError(f"Sumampa API did not become healthy at {base_url}: {last_error}")


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw_body": body}
        return exc.code, payload


def _assistant_text(response_payload: Any) -> str:
    if not isinstance(response_payload, dict):
        return ""
    messages = response_payload.get("messages")
    if not isinstance(messages, list):
        return ""
    return " ".join(
        str(message.get("text") or "")
        for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
    ).strip()


def _missing_data_score(text: str, missing_fields: Any) -> float:
    fields = [str(field) for field in missing_fields] if isinstance(missing_fields, list) else []
    if not fields:
        return 1.0
    return _contains_all(text, fields)


def _communication_quality(text: str) -> float:
    if not text:
        return 0.0
    score = 1.0
    normalized = text.casefold()
    if len(text) > 1200:
        score -= 0.25
    if "traceback" in normalized or "exception" in normalized:
        score -= 0.5
    if any(word in normalized for word in ("listo", "encontre", "encontré", "necesito")):
        score += 0.05
    return max(0.0, min(score, 1.0))


def _contains_all(text: str, terms: list[str]) -> float:
    normalized = text.casefold()
    return float(all(term.casefold() in normalized for term in terms))


def _contains_any(text: str, terms: list[str]) -> bool:
    normalized = text.casefold()
    return any(term.casefold() in normalized for term in terms)


def _correlation_metadata(request_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "harbor.job_id": os.environ.get("HARBOR_JOB_ID") or os.environ.get("HARBOR_TRIAL_ID"),
        "harbor.task_id": os.environ.get("HARBOR_TASK_ID"),
        "git.sha": os.environ.get("GIT_SHA"),
        "agent_model": os.environ.get("AGENT_MODEL"),
        "dataset": "sumampa-odoo-fullstack",
        "phoenix.project_name": os.environ.get("PHOENIX_PROJECT_NAME"),
        "conversation_id": request_payload.get("conversation_id"),
        "eval_tags": request_payload.get("eval_tags", []),
    }


def _empty_reward(*, error: float) -> dict[str, float]:
    return {
        "task_success": 0.0,
        "odoo_payload_valid": 0.0,
        "grounded_in_tool_result": 0.0,
        "missing_data_handled": 0.0,
        "communication_quality": 0.0,
        "needs_human_review": 1.0,
        "latency_ms": 0.0,
        "error": float(error),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _log(message: str) -> None:
    with VERIFIER_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
