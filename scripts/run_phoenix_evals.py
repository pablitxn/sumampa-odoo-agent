"""Run Sumampa agent evals from a Phoenix dataset."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from scripts.phoenix_eval_utils import (
        P0_P1_PRIORITIES,
        build_llm_rubric_eval,
        build_phoenix_client,
        conversation_quality_eval,
        deterministic_eval,
    )
else:
    try:
        from scripts.phoenix_eval_utils import (
            P0_P1_PRIORITIES,
            build_llm_rubric_eval,
            build_phoenix_client,
            conversation_quality_eval,
            deterministic_eval,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from phoenix_eval_utils import (
            P0_P1_PRIORITIES,
            build_llm_rubric_eval,
            build_phoenix_client,
            conversation_quality_eval,
            deterministic_eval,
        )

from sumampa_odoo_agent.config import (
    AppSettings,
    AttachmentStoreMode,
    OdooMode,
    SessionStoreMode,
    load_settings,
)
from sumampa_odoo_agent.integrations.telemetry import bootstrap_telemetry
from sumampa_odoo_agent.services import build_app_services
from sumampa_odoo_agent.services.conversation import ConversationTurnInput
from sumampa_odoo_agent.services.demo_sales import DemoSalesTurnInput
from sumampa_odoo_agent.services.models.attachments import AttachmentSource


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_name")
    parser.add_argument("--env", default=None, help="PYTHON_ENV-compatible config environment")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--description", default="Sumampa Odoo agent regression eval")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--odoo-mode",
        choices=("dry-run", "jsonrpc"),
        default="dry-run",
        help="Odoo mode used by eval task execution. Defaults to dry-run for safe local repeats.",
    )
    parser.add_argument(
        "--session-store-mode",
        choices=("memory", "hybrid"),
        default="memory",
        help="Session store mode used by eval task execution.",
    )
    parser.add_argument(
        "--attachment-store-mode",
        choices=("memory", "s3"),
        default="memory",
        help="Attachment store mode used by eval task execution.",
    )
    parser.add_argument("--llm-judge-model", default=os.environ.get("OPENAI_EVAL_MODEL"))
    parser.add_argument(
        "--require-llm-judge-for-p0-p1",
        action="store_true",
        help="Fail argument parsing unless an LLM judge model is configured for P0/P1 examples.",
    )
    parser.add_argument(
        "--llm-judge-priority",
        action="append",
        dest="llm_judge_priorities",
        default=[],
        help="Priority label that requires llm_judge_pass in judge metadata. Repeatable.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.require_llm_judge_for_p0_p1 and not args.llm_judge_model:
        parser.error("--require-llm-judge-for-p0-p1 requires --llm-judge-model or OPENAI_EVAL_MODEL")

    settings = _eval_settings(
        load_settings(env=args.env),
        odoo_mode=args.odoo_mode,
        session_store_mode=args.session_store_mode,
        attachment_store_mode=args.attachment_store_mode,
    )
    client = build_phoenix_client(settings)
    dataset = client.datasets.get_dataset(dataset=args.dataset_name)
    evaluators: list[Any] = [deterministic_eval, conversation_quality_eval]
    required_priorities = tuple(args.llm_judge_priorities) or (
        P0_P1_PRIORITIES if args.require_llm_judge_for_p0_p1 else ()
    )
    if args.llm_judge_model:
        evaluators.append(
            build_llm_rubric_eval(
                args.llm_judge_model,
                required_priorities=required_priorities,
            )
        )

    result = client.experiments.run_experiment(
        dataset=dataset,
        task=lambda item: _run_item_sync(settings, item),
        evaluators=evaluators,
        experiment_name=args.run_name or f"{args.dataset_name}/agent",
        experiment_description=args.description,
        experiment_metadata={
            "agent_mode": settings.agent.mode,
            "agent_model": settings.agent.model,
            "odoo_mode": settings.odoo.mode,
            "llm_judge_model": args.llm_judge_model,
            "llm_judge_required_priorities": list(required_priorities),
        },
        repetitions=max(args.repetitions, 1),
        dry_run=args.dry_run,
    )
    print(result)


def _run_item_sync(settings: AppSettings, item: Any) -> dict[str, Any]:
    """Bridge the async app runtime into Phoenix client's synchronous experiment runner."""

    return asyncio.run(_run_item(settings, item))


async def _run_item(settings: AppSettings, item: Any) -> dict[str, Any]:
    item_input = _item_input(item)
    start = time.perf_counter()
    telemetry_runtime = bootstrap_telemetry(settings)
    services = await build_app_services(
        settings,
        telemetry_observability=telemetry_runtime.observability,
        metrics=telemetry_runtime.metrics,
    )
    try:
        if _is_demo_sales_item(item_input):
            demo_result = await services.demo_sales.run_turn(
                DemoSalesTurnInput(
                    conversation_id=str(item_input.get("conversation_id") or f"eval-{uuid4()}"),
                    channel=str(item_input.get("channel") or "whatsapp"),
                    user_id=str(item_input.get("user_id") or "eval-user"),
                    text=str(item_input.get("text") or ""),
                    scenario_id=str(item_input.get("scenario_id")),
                    scenario_params=_scenario_params(item_input),
                    context=_eval_context(item_input),
                    eval_tags=_string_list(item_input.get("eval_tags")),
                )
            )
            return {
                "assistant_text": "\n".join(demo_result.messages),
                "conversation_id": demo_result.conversation_id,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": None,
                "scenario": demo_result.scenario,
                "state_after_turn": demo_result.trace_output.get("state_after_turn"),
                "tool_calls": demo_result.trace_output.get("tool_calls", []),
                "state_mutations": demo_result.trace_output.get("state_mutations", []),
                "transcript_after_turn": demo_result.trace_output.get(
                    "transcript_after_turn",
                    [],
                ),
            }
        conversation_result = await services.conversation.run_turn(
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
            "assistant_text": conversation_result.assistant_text,
            "conversation_id": conversation_result.conversation_id,
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
        await telemetry_runtime.aclose()


def _eval_settings(
    settings: AppSettings,
    *,
    odoo_mode: OdooMode = "dry-run",
    session_store_mode: SessionStoreMode = "memory",
    attachment_store_mode: AttachmentStoreMode = "memory",
) -> AppSettings:
    return settings.model_copy(
        update={
            "odoo": settings.odoo.model_copy(update={"mode": odoo_mode}),
            "session_store": settings.session_store.model_copy(update={"mode": session_store_mode}),
            "attachments": settings.attachments.model_copy(
                update={"store_mode": attachment_store_mode}
            ),
        }
    )


def _item_input(item: Any) -> dict[str, Any]:
    value = _get_attr(item, "input", _get_attr(item, "inputs", item))
    return dict(value) if isinstance(value, dict) else {"text": str(value)}


def _eval_context(item_input: dict[str, Any]) -> dict[str, Any]:
    raw_context = item_input.get("context")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    attachment_manifests = item_input.get("attachment_manifests")
    if isinstance(attachment_manifests, list) and attachment_manifests:
        context["attachment_manifests"] = attachment_manifests
    for key in (
        "initial_state",
        "state_before_turn",
        "transcript_before_turn",
        "transcript_current_turn",
        "scenario_version",
        "scenario_params",
    ):
        if key in item_input:
            context[key] = item_input[key]
    return context


def _is_demo_sales_item(item_input: dict[str, Any]) -> bool:
    return isinstance(item_input.get("scenario_id"), str) and bool(item_input["scenario_id"])


def _scenario_params(item_input: dict[str, Any]) -> dict[str, str]:
    raw_params = item_input.get("scenario_params")
    if not isinstance(raw_params, dict):
        return {}
    return {str(key): str(value) for key, value in raw_params.items()}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    return [str(item) for item in raw_values if str(item).strip()]


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


if __name__ == "__main__":
    main()
