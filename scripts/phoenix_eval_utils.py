"""Shared Phoenix dataset and evaluation helpers for Sumampa."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from openai import AsyncOpenAI

from sumampa_odoo_agent.config import AppSettings

DATASETS: tuple[dict[str, Any], ...] = (
    {
        "name": "sumampa/dev/conversation-turns",
        "description": "Curated real and synthetic WhatsApp-style turns for conversational quality.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "conversation"},
    },
    {
        "name": "sumampa/dev/odoo-ops",
        "description": "Odoo operation tasks with deterministic expected outcomes.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "odoo"},
    },
    {
        "name": "sumampa/dev/regression-failures",
        "description": "Production or development failures promoted into regression evals.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "regression"},
    },
    {
        "name": "sumampa/dev/fullstack-gate",
        "description": "Harbor-backed full-stack gate slice for release and nightly evidence.",
        "metadata": {"domain": "sumampa", "stage": "dev", "kind": "harbor"},
    },
)

SCORE_NAMES: tuple[str, ...] = (
    "task_success",
    "odoo_payload_valid",
    "grounded_in_tool_result",
    "missing_data_handled",
    "communication_quality",
    "needs_human_review",
    "latency_ms",
    "error",
    "llm_judge_pass",
)

P0_P1_PRIORITIES: tuple[str, ...] = ("p0", "p1")

SCORE_DEFAULTS: dict[str, float] = {
    "task_success": 0.0,
    "odoo_payload_valid": 0.0,
    "grounded_in_tool_result": 0.0,
    "missing_data_handled": 0.0,
    "communication_quality": 0.0,
    "needs_human_review": 1.0,
    "latency_ms": 0.0,
    "error": 1.0,
    "llm_judge_pass": 0.0,
}


def build_phoenix_client(settings: AppSettings) -> Any:
    from phoenix.client import Client

    api_key = os.environ.get(settings.observability.api_key_env_var) or None
    return Client(base_url=settings.observability.base_url, api_key=api_key)


def deterministic_eval(
    *,
    input: Any,
    output: Any,
    expected: Any = None,
    expected_output: Any = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    del input, metadata, kwargs
    output_payload = output if isinstance(output, dict) else {}
    expected_payload = _expected_payload(expected=expected, expected_output=expected_output)
    assistant_text = str(output_payload.get("assistant_text") or "")
    error = output_payload.get("error")
    required_substrings = [
        str(item).casefold() for item in expected_payload.get("required_substrings", [])
    ]
    forbidden_substrings = [
        str(item).casefold() for item in expected_payload.get("forbidden_substrings", [])
    ]
    normalized_text = assistant_text.casefold()
    required_ok = all(item in normalized_text for item in required_substrings)
    forbidden_ok = not any(item in normalized_text for item in forbidden_substrings)
    task_success = float(not error and required_ok and forbidden_ok)
    return [
        score("task_success", task_success, explanation="Matched deterministic text constraints."),
        score(
            "odoo_payload_valid",
            0.0 if error else 1.0,
            explanation="Runtime completed without schema or validation exception.",
        ),
        score(
            "latency_ms",
            float(output_payload.get("latency_ms") or 0),
            explanation="End-to-end eval item latency.",
        ),
        score(
            "error",
            1.0 if error else 0.0,
            explanation=str(error or "No exception raised."),
        ),
    ]


def conversation_quality_eval(
    *,
    input: Any,
    output: Any,
    expected: Any = None,
    expected_output: Any = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    del input, metadata, kwargs
    output_payload = output if isinstance(output, dict) else {}
    expected_payload = _expected_payload(expected=expected, expected_output=expected_output)
    assistant_text = str(output_payload.get("assistant_text") or "")
    normalized_text = assistant_text.casefold()
    missing_fields = [str(item).casefold() for item in expected_payload.get("missing_fields", [])]
    grounded_terms = [str(item).casefold() for item in expected_payload.get("grounded_terms", [])]
    missing_data_score = (
        float(all(field in normalized_text for field in missing_fields))
        if missing_fields
        else 1.0
    )
    grounded_score = (
        float(all(term in normalized_text for term in grounded_terms)) if grounded_terms else 0.5
    )
    communication_score = heuristic_spanish_whatsapp_quality(assistant_text)
    needs_review = min(missing_data_score, grounded_score, communication_score) < 0.75
    return [
        score(
            "grounded_in_tool_result",
            grounded_score,
            explanation="Heuristic check against expected grounded terms.",
        ),
        score(
            "missing_data_handled",
            missing_data_score,
            explanation="Heuristic check that missing fields are requested or mentioned.",
        ),
        score(
            "communication_quality",
            communication_score,
            explanation="Heuristic Spanish WhatsApp quality score.",
        ),
        score(
            "needs_human_review",
            1.0 if needs_review else 0.0,
            label=str(needs_review).lower(),
            explanation="True when heuristic quality signal is low or ambiguous.",
        ),
    ]


def build_llm_rubric_eval(
    model: str,
    *,
    required_priorities: tuple[str, ...] = P0_P1_PRIORITIES,
) -> Any:
    client = AsyncOpenAI()

    async def llm_rubric_eval(
        *,
        input: Any,
        output: Any,
        expected: Any = None,
        expected_output: Any = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del kwargs
        priority = metadata_priority(metadata)
        judge_required = priority in {item.casefold() for item in required_priorities}
        prompt = (
            "Grade this Spanish WhatsApp Odoo assistant output from 0.0 to 1.0 on "
            "task completion, groundedness, missing-data handling, and concise operational clarity. "
            "Return JSON with keys task_success, grounded_in_tool_result, missing_data_handled, "
            "communication_quality, needs_human_review, llm_judge_pass, comment.\n"
            "The llm_judge_pass key must be 1.0 only when the output is grounded, operationally "
            "correct, concise, and safe to accept without human intervention.\n\n"
            f"Input: {input}\nExpected: {expected or expected_output}\n"
            f"Metadata: {metadata}\nOutput: {output}"
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"

        try:
            scores = json.loads(content)
        except json.JSONDecodeError:
            return [
                score(
                    "needs_human_review",
                    1.0,
                    label="true",
                    explanation=f"LLM judge returned invalid JSON: {content[:200]}",
                    metadata={
                        "source": "llm_judge",
                        "model": model,
                        "priority": priority,
                        "judge_required": judge_required,
                    },
                ),
                score(
                    "llm_judge_pass",
                    0.0,
                    label="fail",
                    explanation="LLM judge returned invalid JSON.",
                    metadata={
                        "source": "llm_judge",
                        "model": model,
                        "priority": priority,
                        "judge_required": judge_required,
                    },
                ),
            ]
        comment = str(scores.get("comment") or scores.get("reasoning") or "LLM rubric score.")
        pass_score = llm_judge_pass_score(scores, judge_required=judge_required)
        judge_metadata = {
            "source": "llm_judge",
            "model": model,
            "priority": priority,
            "judge_required": judge_required,
            "judge_reasoning": comment,
        }
        return [
            score(
                "task_success",
                bounded_float(scores.get("task_success", 0.0)),
                explanation=comment,
                metadata=judge_metadata,
            ),
            score(
                "grounded_in_tool_result",
                bounded_float(scores.get("grounded_in_tool_result", 0.0)),
                explanation="LLM rubric score.",
                metadata=judge_metadata,
            ),
            score(
                "missing_data_handled",
                bounded_float(scores.get("missing_data_handled", 0.0)),
                explanation="LLM rubric score.",
                metadata=judge_metadata,
            ),
            score(
                "communication_quality",
                bounded_float(scores.get("communication_quality", 0.0)),
                explanation="LLM rubric score.",
                metadata=judge_metadata,
            ),
            score(
                "needs_human_review",
                1.0 if bool(scores.get("needs_human_review", True)) else 0.0,
                label=str(bool(scores.get("needs_human_review", True))).lower(),
                explanation=comment,
                metadata=judge_metadata,
            ),
            score(
                "llm_judge_pass",
                pass_score,
                label="pass" if pass_score >= 1.0 else "fail",
                explanation=comment,
                metadata=judge_metadata,
            ),
        ]

    return llm_rubric_eval


def score(
    name: str,
    value: float,
    *,
    label: str | None = None,
    explanation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if name not in SCORE_NAMES:
        raise ValueError(f"Unknown eval score name: {name}")
    return {
        "name": name,
        "score": float(value),
        "label": label,
        "explanation": explanation,
        "metadata": metadata or {},
    }


def numeric_reward_payload(
    values: Mapping[str, Any] | None = None,
    *,
    defaults: Mapping[str, float] | None = None,
) -> dict[str, float]:
    payload = dict(values or {})
    extra_keys = sorted(set(payload) - set(SCORE_NAMES))
    if extra_keys:
        raise ValueError(f"Unknown reward keys: {', '.join(extra_keys)}")

    base_defaults = dict(SCORE_DEFAULTS if defaults is None else defaults)
    normalized: dict[str, float] = {}
    for name in SCORE_NAMES:
        value = payload.get(name, base_defaults.get(name, 0.0))
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"Reward {name!r} must be numeric, got {type(value).__name__}")
        normalized[name] = float(value)
    return normalized


def metadata_priority(metadata: Mapping[str, Any] | None) -> str:
    if not isinstance(metadata, Mapping):
        return ""
    priority = metadata.get("priority") or metadata.get("severity")
    if isinstance(priority, str):
        return priority.strip().casefold()

    source_metadata = metadata.get("source_metadata")
    if isinstance(source_metadata, Mapping):
        source_priority = source_metadata.get("priority") or source_metadata.get("severity")
        if isinstance(source_priority, str):
            return source_priority.strip().casefold()
    return ""


def priority_requires_llm_judge(
    metadata: Mapping[str, Any] | None,
    *,
    required_priorities: tuple[str, ...] = P0_P1_PRIORITIES,
) -> bool:
    priority = metadata_priority(metadata)
    return bool(priority and priority in {item.casefold() for item in required_priorities})


def llm_judge_pass_score(scores: Mapping[str, Any], *, judge_required: bool) -> float:
    explicit_score = scores.get("llm_judge_pass")
    if isinstance(explicit_score, bool):
        return 1.0 if explicit_score else 0.0
    if isinstance(explicit_score, int | float):
        return 1.0 if float(explicit_score) >= 1.0 else 0.0
    if not judge_required:
        return 1.0

    rubric_scores = [
        bounded_float(scores.get("task_success", 0.0)),
        bounded_float(scores.get("grounded_in_tool_result", 0.0)),
        bounded_float(scores.get("missing_data_handled", 0.0)),
        bounded_float(scores.get("communication_quality", 0.0)),
    ]
    needs_review = bool(scores.get("needs_human_review", True))
    return 1.0 if min(rubric_scores) >= 0.8 and not needs_review else 0.0


def bounded_float(value: Any) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(float(value), 1.0))


def heuristic_spanish_whatsapp_quality(text: str) -> float:
    if not text.strip():
        return 0.0
    quality_score = 1.0
    if len(text) > 1200:
        quality_score -= 0.25
    if "traceback" in text.casefold() or "exception" in text.casefold():
        quality_score -= 0.5
    if "?" in text or "¿" in text:
        quality_score += 0.05
    return max(0.0, min(quality_score, 1.0))


def _expected_payload(*, expected: Any, expected_output: Any) -> dict[str, Any]:
    value = expected if expected is not None else expected_output
    return value if isinstance(value, dict) else {}
