from __future__ import annotations

import json
import os
import time
import traceback
import urllib.error
import urllib.request
import xmlrpc.client
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
    _write_json(CORRELATION_PATH, _correlation_metadata(request_payload, expected))

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
    odoo_assertion_score = _odoo_assertions_score(expected)
    llm_judge_score = _llm_judge_score(
        request_payload=request_payload,
        response_payload=response_payload,
        expected=expected,
        assistant_text=assistant_text,
    )
    communication_score = _communication_quality(assistant_text)
    task_success = min(
        http_ok,
        response_shape,
        required_ok,
        float(forbidden_ok),
        latency_score,
        odoo_assertion_score,
    )

    _log(
        f"status={status_code} latency_ms={latency_ms:0.1f} "
        f"task_success={task_success} llm_judge_pass={llm_judge_score} "
        f"assistant_text={assistant_text[:500]!r}"
    )
    return {
        "task_success": task_success,
        "odoo_payload_valid": min(response_shape, odoo_assertion_score),
        "grounded_in_tool_result": required_ok,
        "missing_data_handled": missing_score,
        "communication_quality": communication_score,
        "needs_human_review": float(
            min(task_success, communication_score, missing_score, llm_judge_score) < 0.75
        ),
        "latency_ms": float(latency_ms),
        "error": 0.0 if http_ok else 1.0,
        "llm_judge_pass": llm_judge_score,
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


def _odoo_assertions_score(expected: dict[str, Any]) -> float:
    assertions = expected.get("odoo_assertions", [])
    if not isinstance(assertions, list) or not assertions:
        return 1.0

    base_url = os.environ.get("ODOO_BASE_URL", "http://odoo19:8069").rstrip("/")
    database = os.environ.get("ODOO_DATABASE", "sumampa_integration")
    username = os.environ.get("ODOO_USERNAME", "admin")
    password = os.environ.get("ODOO_PASSWORD", "admin")
    results: list[dict[str, Any]] = []
    try:
        common_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/common", allow_none=True)
        uid = common_proxy.authenticate(database, username, password, {})
        if not isinstance(uid, int) or uid <= 0:
            raise RuntimeError("Could not authenticate to Odoo for verifier assertions.")
        object_proxy = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object", allow_none=True)
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            model = str(assertion.get("model") or "")
            domain = assertion.get("domain", [])
            fields = assertion.get("fields", ["display_name"])
            min_count = int(assertion.get("min_count", 1))
            if not model or not isinstance(domain, list) or not isinstance(fields, list):
                results.append({"assertion": assertion, "passed": False, "error": "invalid shape"})
                continue
            rows = object_proxy.execute_kw(
                database,
                uid,
                password,
                model,
                "search_read",
                [domain],
                {"fields": [str(field) for field in fields], "limit": max(min_count, 1)},
            )
            passed = isinstance(rows, list) and len(rows) >= min_count
            results.append(
                {
                    "model": model,
                    "domain": domain,
                    "min_count": min_count,
                    "row_count": len(rows) if isinstance(rows, list) else 0,
                    "rows": rows if isinstance(rows, list) else [],
                    "passed": passed,
                }
            )
    except Exception as exc:
        _write_json(
            ARTIFACT_DIR / "odoo_assertions_error.json",
            {"error": f"{exc.__class__.__name__}: {exc}", "traceback": traceback.format_exc()},
        )
        _log(f"odoo assertion check failed: {exc.__class__.__name__}: {exc}")
        return 0.0

    _write_json(ARTIFACT_DIR / "odoo_assertions.json", results)
    return float(bool(results) and all(bool(result.get("passed")) for result in results))


def _llm_judge_score(
    *,
    request_payload: dict[str, Any],
    response_payload: Any,
    expected: dict[str, Any],
    assistant_text: str,
) -> float:
    if not bool(expected.get("llm_judge_required", False)):
        return 1.0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _write_json(ARTIFACT_DIR / "llm_judge.json", {"error": "OPENAI_API_KEY is not configured"})
        _log("llm judge required but OPENAI_API_KEY is not configured")
        return 0.0

    model = (
        os.environ.get("LLM_JUDGE_MODEL")
        or os.environ.get("OPENAI_EVAL_MODEL")
        or os.environ.get("AGENT_MODEL")
        or "gpt-5.4-mini"
    )
    judge_request = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Judge this Sumampa Odoo assistant response for release gating. "
                    "Return JSON only with keys llm_judge_pass, needs_human_review, "
                    "task_success, grounded_in_tool_result, communication_quality, comment. "
                    "llm_judge_pass must be 1 only if the answer is grounded in the Odoo task, "
                    "safe, concise, and operationally correct.\n\n"
                    f"Request: {json.dumps(request_payload, sort_keys=True)}\n"
                    f"Expected: {json.dumps(expected, sort_keys=True)}\n"
                    f"Response: {json.dumps(response_payload, sort_keys=True)}\n"
                    f"Assistant text: {assistant_text}"
                ),
            }
        ],
        "response_format": {"type": "json_object"},
    }
    http_request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(judge_request).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        judge_payload = json.loads(content)
        _write_json(
            ARTIFACT_DIR / "llm_judge.json",
            {"model": model, "judge": judge_payload},
        )
    except Exception as exc:
        _write_json(
            ARTIFACT_DIR / "llm_judge.json",
            {"model": model, "error": f"{exc.__class__.__name__}: {exc}"},
        )
        _log(f"llm judge failed: {exc.__class__.__name__}: {exc}")
        return 0.0

    score_value = judge_payload.get("llm_judge_pass")
    if isinstance(score_value, bool):
        return 1.0 if score_value else 0.0
    if isinstance(score_value, int | float):
        return 1.0 if float(score_value) >= 1.0 else 0.0
    return 0.0


def _correlation_metadata(
    request_payload: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    context = _request_context(request_payload)
    return {
        "harbor.job_id": os.environ.get("HARBOR_JOB_ID") or os.environ.get("HARBOR_TRIAL_ID"),
        "harbor.task_id": os.environ.get("HARBOR_TASK_ID"),
        "git.sha": os.environ.get("GIT_SHA"),
        "agent_model": os.environ.get("AGENT_MODEL"),
        "dataset": "sumampa-odoo-fullstack",
        "phoenix.project_name": os.environ.get("PHOENIX_PROJECT_NAME"),
        "conversation_id": request_payload.get("conversation_id"),
        "scenario": context.get("scenario"),
        "priority": expected.get("priority"),
        "llm_judge_required": bool(expected.get("llm_judge_required", False)),
        "human_review_status": expected.get("human_review_status"),
        "eval_tags": request_payload.get("eval_tags", []),
    }


def _request_context(request_payload: dict[str, Any]) -> dict[str, Any]:
    context = request_payload.get("context")
    return context if isinstance(context, dict) else {}


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
        "llm_judge_pass": 0.0,
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
