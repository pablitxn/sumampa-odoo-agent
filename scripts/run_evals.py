"""Run Sumampa agent evals from a Langfuse dataset."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any
from uuid import uuid4

from langfuse import Evaluation, Langfuse
from langfuse.experiment import EvaluatorFunction
from openai import AsyncOpenAI

from sumampa_odoo_agent.config import AppSettings, load_settings
from sumampa_odoo_agent.services import build_app_services
from sumampa_odoo_agent.services.conversation import ConversationTurnInput
from sumampa_odoo_agent.services.models.attachments import AttachmentSource


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_name")
    parser.add_argument("--env", default=None, help="PYTHON_ENV-compatible config environment")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--description", default="Sumampa Odoo agent regression eval")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--llm-judge-model", default=os.environ.get("OPENAI_EVAL_MODEL"))
    args = parser.parse_args()

    settings = _eval_settings(load_settings(env=args.env))
    langfuse = _build_langfuse_client(settings)
    dataset = langfuse.get_dataset(args.dataset_name)
    data = _expand_items(dataset.items, repetitions=max(args.repetitions, 1))
    evaluators: list[EvaluatorFunction] = [
        deterministic_eval,
        conversation_quality_eval,
    ]
    if args.llm_judge_model:
        evaluators.append(_build_llm_rubric_eval(args.llm_judge_model))

    result = langfuse.run_experiment(
        name=f"{args.dataset_name}/agent",
        run_name=args.run_name,
        description=args.description,
        data=data,
        task=lambda *, item, **kwargs: _run_item(settings, item),
        evaluators=evaluators,
        max_concurrency=args.max_concurrency,
        metadata={
            "agent_mode": settings.agent.mode,
            "agent_model": settings.agent.model,
            "odoo_mode": settings.odoo.mode,
        },
    )
    print(result.format())
    langfuse.flush()


async def _run_item(settings: AppSettings, item: Any) -> dict[str, Any]:
    item_input = _item_input(item)
    start = time.perf_counter()
    services = await build_app_services(settings)
    try:
        result = await services.conversation.run_turn(
            ConversationTurnInput(
                conversation_id=f"eval-{uuid4()}",
                channel=str(item_input.get("channel") or "whatsapp"),
                user_id=str(item_input.get("user_id") or "eval-user"),
                text=str(item_input.get("text") or ""),
                attachments=[
                    AttachmentSource.model_validate(attachment)
                    for attachment in item_input.get("attachments", [])
                    if isinstance(attachment, dict)
                    and (attachment.get("content_base64") or attachment.get("download_url"))
                ],
                context=_eval_context(item_input),
            )
        )
        return {
            "assistant_text": result.assistant_text,
            "conversation_id": result.conversation_id,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": None,
        }
    except Exception as exc:
        return {
            "assistant_text": "",
            "conversation_id": None,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    finally:
        await services.aclose()


def deterministic_eval(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[Evaluation]:
    del input, metadata, kwargs
    output_payload = output if isinstance(output, dict) else {}
    expected = expected_output if isinstance(expected_output, dict) else {}
    assistant_text = str(output_payload.get("assistant_text") or "")
    error = output_payload.get("error")
    required_substrings = [str(item).casefold() for item in expected.get("required_substrings", [])]
    forbidden_substrings = [str(item).casefold() for item in expected.get("forbidden_substrings", [])]
    normalized_text = assistant_text.casefold()
    required_ok = all(item in normalized_text for item in required_substrings)
    forbidden_ok = not any(item in normalized_text for item in forbidden_substrings)
    task_success = float(not error and required_ok and forbidden_ok)
    return [
        Evaluation(
            name="task_success",
            value=task_success,
            comment="Matched expected deterministic text constraints.",
        ),
        Evaluation(
            name="odoo_payload_valid",
            value=0.0 if error else 1.0,
            comment="Runtime completed without schema or validation exception.",
        ),
        Evaluation(
            name="latency_ms",
            value=float(output_payload.get("latency_ms") or 0),
            comment="End-to-end eval item latency.",
        ),
        Evaluation(
            name="error",
            value=1.0 if error else 0.0,
            comment=str(error or "No exception raised."),
        ),
    ]


def conversation_quality_eval(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[Evaluation]:
    del input, metadata, kwargs
    output_payload = output if isinstance(output, dict) else {}
    expected = expected_output if isinstance(expected_output, dict) else {}
    assistant_text = str(output_payload.get("assistant_text") or "")
    normalized_text = assistant_text.casefold()
    missing_fields = [str(item).casefold() for item in expected.get("missing_fields", [])]
    grounded_terms = [str(item).casefold() for item in expected.get("grounded_terms", [])]
    missing_data_score = (
        float(all(field in normalized_text for field in missing_fields))
        if missing_fields
        else 1.0
    )
    grounded_score = (
        float(all(term in normalized_text for term in grounded_terms))
        if grounded_terms
        else 0.5
    )
    communication_score = _heuristic_spanish_whatsapp_quality(assistant_text)
    needs_review = min(missing_data_score, grounded_score, communication_score) < 0.75
    return [
        Evaluation(
            name="grounded_in_tool_result",
            value=grounded_score,
            comment="Heuristic check against expected grounded terms.",
        ),
        Evaluation(
            name="missing_data_handled",
            value=missing_data_score,
            comment="Heuristic check that missing fields are requested or mentioned.",
        ),
        Evaluation(
            name="communication_quality",
            value=communication_score,
            comment="Heuristic Spanish WhatsApp quality score.",
        ),
        Evaluation(
            name="needs_human_review",
            value=needs_review,
            data_type="BOOLEAN",
            comment="True when heuristic quality signal is low or ambiguous.",
        ),
    ]


def _build_llm_rubric_eval(model: str) -> Any:
    client = AsyncOpenAI()

    async def llm_rubric_eval(
        *,
        input: Any,
        output: Any,
        expected_output: Any = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Evaluation]:
        del kwargs
        prompt = (
            "Grade this Spanish WhatsApp Odoo assistant output from 0.0 to 1.0 on "
            "task completion, groundedness, missing-data handling, and concise operational clarity. "
            "Return JSON with keys task_success, grounded_in_tool_result, missing_data_handled, "
            "communication_quality, needs_human_review, comment.\n\n"
            f"Input: {input}\nExpected: {expected_output}\nMetadata: {metadata}\nOutput: {output}"
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
                Evaluation(
                    name="needs_human_review",
                    value=True,
                    data_type="BOOLEAN",
                    comment=f"LLM judge returned invalid JSON: {content[:200]}",
                )
            ]
        return [
            Evaluation(
                name="task_success",
                value=float(scores.get("task_success", 0.0)),
                comment=str(scores.get("comment", "LLM rubric score.")),
            ),
            Evaluation(
                name="grounded_in_tool_result",
                value=float(scores.get("grounded_in_tool_result", 0.0)),
                comment="LLM rubric score.",
            ),
            Evaluation(
                name="missing_data_handled",
                value=float(scores.get("missing_data_handled", 0.0)),
                comment="LLM rubric score.",
            ),
            Evaluation(
                name="communication_quality",
                value=float(scores.get("communication_quality", 0.0)),
                comment="LLM rubric score.",
            ),
            Evaluation(
                name="needs_human_review",
                value=bool(scores.get("needs_human_review", True)),
                data_type="BOOLEAN",
                comment=str(scores.get("comment", "LLM rubric score.")),
            ),
        ]

    return llm_rubric_eval


def _eval_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "odoo": settings.odoo.model_copy(update={"mode": "dry-run"}),
            "session_store": settings.session_store.model_copy(update={"mode": "memory"}),
            "attachments": settings.attachments.model_copy(update={"store_mode": "memory"}),
        }
    )


def _expand_items(items: list[Any], *, repetitions: int) -> list[Any]:
    if repetitions == 1:
        return items
    expanded: list[Any] = []
    for item in items:
        for repetition in range(repetitions):
            item_input = _item_input(item)
            item_input["eval_repetition"] = repetition + 1
            expanded.append(
                {
                    "input": item_input,
                    "expected_output": _get_attr(item, "expected_output", None),
                    "metadata": {
                        **(_get_attr(item, "metadata", {}) or {}),
                        "eval_repetition": repetition + 1,
                    },
                }
            )
    return expanded


def _item_input(item: Any) -> dict[str, Any]:
    value = _get_attr(item, "input", item)
    return dict(value) if isinstance(value, dict) else {"text": str(value)}


def _eval_context(item_input: dict[str, Any]) -> dict[str, Any]:
    raw_context = item_input.get("context")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    attachment_manifests = item_input.get("attachment_manifests")
    if isinstance(attachment_manifests, list) and attachment_manifests:
        context["attachment_manifests"] = attachment_manifests
    return context


def _build_langfuse_client(settings: AppSettings) -> Langfuse:
    return Langfuse(
        public_key=os.environ.get(settings.observability.public_key_env_var),
        secret_key=os.environ.get(settings.observability.secret_key_env_var),
        base_url=settings.observability.base_url,
        environment=settings.observability.environment,
    )


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _heuristic_spanish_whatsapp_quality(text: str) -> float:
    if not text.strip():
        return 0.0
    score = 1.0
    if len(text) > 1200:
        score -= 0.25
    if "traceback" in text.casefold() or "exception" in text.casefold():
        score -= 0.5
    if "?" in text or "¿" in text:
        score += 0.05
    return max(0.0, min(score, 1.0))


if __name__ == "__main__":
    main()
