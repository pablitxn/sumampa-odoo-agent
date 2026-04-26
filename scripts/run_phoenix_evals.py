"""Run Sumampa agent evals from a Phoenix dataset."""

from __future__ import annotations

import argparse
import os
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from scripts.phoenix_eval_utils import (
        build_llm_rubric_eval,
        build_phoenix_client,
        conversation_quality_eval,
        deterministic_eval,
    )
else:
    try:
        from scripts.phoenix_eval_utils import (
            build_llm_rubric_eval,
            build_phoenix_client,
            conversation_quality_eval,
            deterministic_eval,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from phoenix_eval_utils import (
            build_llm_rubric_eval,
            build_phoenix_client,
            conversation_quality_eval,
            deterministic_eval,
        )

from sumampa_odoo_agent.config import AppSettings, load_settings
from sumampa_odoo_agent.integrations.telemetry import bootstrap_telemetry
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
    parser.add_argument("--llm-judge-model", default=os.environ.get("OPENAI_EVAL_MODEL"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = _eval_settings(load_settings(env=args.env))
    client = build_phoenix_client(settings)
    dataset = client.datasets.get_dataset(dataset=args.dataset_name)
    evaluators: list[Any] = [deterministic_eval, conversation_quality_eval]
    if args.llm_judge_model:
        evaluators.append(build_llm_rubric_eval(args.llm_judge_model))

    result = client.experiments.run_experiment(
        dataset=dataset,
        task=lambda item: _run_item(settings, item),
        evaluators=evaluators,
        experiment_name=args.run_name or f"{args.dataset_name}/agent",
        experiment_description=args.description,
        experiment_metadata={
            "agent_mode": settings.agent.mode,
            "agent_model": settings.agent.model,
            "odoo_mode": settings.odoo.mode,
        },
        repetitions=max(args.repetitions, 1),
        dry_run=args.dry_run,
    )
    print(result)


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
        await telemetry_runtime.aclose()


def _eval_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "odoo": settings.odoo.model_copy(update={"mode": "dry-run"}),
            "session_store": settings.session_store.model_copy(update={"mode": "memory"}),
            "attachments": settings.attachments.model_copy(update={"store_mode": "memory"}),
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
    return context


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


if __name__ == "__main__":
    main()
