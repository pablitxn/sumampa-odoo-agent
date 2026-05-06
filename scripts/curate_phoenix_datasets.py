"""Promote Phoenix conversation spans into curated dataset examples."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts.phoenix_eval_utils import build_phoenix_client
else:
    try:
        from scripts.phoenix_eval_utils import build_phoenix_client
    except ModuleNotFoundError:  # pragma: no cover - direct script execution
        from phoenix_eval_utils import build_phoenix_client

from sumampa_odoo_agent.config import load_settings

DATASET_READY_TAG = "eval:dataset-ready"
DEMO_SALES_INPUT_KEYS = (
    "scenario_id",
    "scenario_version",
    "scenario_params",
    "initial_state",
    "state_before_turn",
    "transcript_before_turn",
    "transcript_current_turn",
    "eval_tags",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_name", help="Target Phoenix dataset name")
    parser.add_argument("--env", default=None, help="PYTHON_ENV-compatible config environment")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--tag", action="append", dest="tags", default=[])
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="Allow curation without eval:dataset-ready. Intended only for local synthetic data.",
    )
    parser.add_argument("--from-timestamp", type=_parse_datetime, default=None)
    parser.add_argument("--to-timestamp", type=_parse_datetime, default=None)
    parser.add_argument(
        "--use-output-as-expected",
        action="store_true",
        help="Use span output as expected output for already-reviewed spans.",
    )
    args = parser.parse_args()
    curation_error = validate_curation_tags(args.tags, allow_unreviewed=args.allow_unreviewed)
    if curation_error:
        parser.error(curation_error)

    settings = load_settings(env=args.env)
    client = build_phoenix_client(settings)
    spans = _fetch_spans(
        client,
        project_name=settings.observability.project_name,
        limit=args.limit,
        from_timestamp=args.from_timestamp,
        to_timestamp=args.to_timestamp,
    )
    conversation_spans = [
        span
        for span in spans
        if span.get("name") in {"conversation.turn", "conversation.tags"}
        and _matches_session(span, args.session_id)
        and _matches_tags(span, args.tags)
    ]

    created = 0
    for span in conversation_spans:
        item = _dataset_item_from_trace(
            span,
            spans=spans,
            use_output_as_expected=args.use_output_as_expected,
        )
        try:
            client.datasets.add_examples_to_dataset(
                dataset=args.dataset_name,
                inputs=[item["input"]],
                outputs=[item["expected_output"] or {}],
                metadata=[item["metadata"]],
            )
            created += 1
            print(f"created item from trace {item['source_trace_id']}")
        except Exception as exc:
            print(f"trace {item['source_trace_id']} skipped or failed: {exc}")

    print(f"created {created} dataset items in {args.dataset_name}")


def _fetch_spans(
    client: Any,
    *,
    project_name: str,
    limit: int,
    from_timestamp: datetime | None,
    to_timestamp: datetime | None,
) -> list[dict[str, Any]]:
    spans_df = client.spans.get_spans_dataframe(
        project_identifier=project_name,
        limit=limit,
        start_time=from_timestamp,
        end_time=to_timestamp,
    )
    return [_span_row_to_trace(row.to_dict()) for _, row in spans_df.iterrows()]


def validate_curation_tags(tags: list[str], *, allow_unreviewed: bool) -> str | None:
    if DATASET_READY_TAG in tags or allow_unreviewed:
        return None
    return f"dataset curation requires --tag {DATASET_READY_TAG} unless --allow-unreviewed is set"


def _dataset_item_from_trace(
    trace: Any,
    *,
    use_output_as_expected: bool,
    spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trace_id = str(_get_attr(trace, "trace_id", "") or _get_attr(trace, "id", ""))
    trace_input = _get_attr(trace, "input", None)
    trace_output = _get_attr(trace, "output", None)
    metadata = _get_attr(trace, "metadata", {}) or {}
    tags = _get_attr(trace, "tags", []) or []
    attachment_manifests = _attachment_manifests_from_trace(trace, spans=spans or [])
    expected_output = trace_output if use_output_as_expected else None
    candidate_output = trace_output if isinstance(trace_output, dict) else {}
    return {
        "id": trace_id or None,
        "input": _normalize_conversation_input(
            trace_input,
            trace=trace,
            attachment_manifests=attachment_manifests,
        ),
        "expected_output": expected_output,
        "metadata": {
            "source": "phoenix_trace",
            "source_trace_id": trace_id,
            "source_span_id": _get_attr(trace, "span_id", None),
            "source_session_id": _get_attr(trace, "session_id", None),
            "source_user_id": _get_attr(trace, "user_id", None),
            "source_tags": tags,
            "source_metadata": metadata,
            "attachment_manifests": attachment_manifests,
            "requires_expected_output_review": not use_output_as_expected,
            "candidate_output": trace_output if not use_output_as_expected else None,
            "tool_ledger": candidate_output.get("tool_calls", []),
            "state_mutations": candidate_output.get("state_mutations", []),
            "transcript_after_turn": candidate_output.get("transcript_after_turn", []),
            "rubric": {
                "task_success": "The assistant completes or correctly blocks the requested Odoo task.",
                "grounded_in_tool_result": "Claims about Odoo records are supported by tool output.",
                "missing_data_handled": "Missing required fields are requested explicitly.",
                "communication_quality": "Spanish WhatsApp reply is clear, concise, and operational.",
            },
        },
        "source_trace_id": trace_id or None,
    }


def _normalize_conversation_input(
    trace_input: Any,
    *,
    trace: Any,
    attachment_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(trace_input, dict):
        return {
            "conversation_id": _trace_conversation_id(trace),
            "channel": _trace_channel(trace),
            "user_id": str(_get_attr(trace, "user_id", None) or "curated-user"),
            "text": str(trace_input or ""),
            "context": {},
            "attachments": [],
            "attachment_manifests": attachment_manifests,
        }
    trace_attachments = [
        attachment for attachment in trace_input.get("attachments", []) if isinstance(attachment, dict)
    ]
    attachments = [
        attachment
        for attachment in trace_attachments
        if attachment.get("content_base64") or attachment.get("download_url")
    ]
    normalized = {
        "conversation_id": str(trace_input.get("conversation_id") or _trace_conversation_id(trace)),
        "channel": str(trace_input.get("channel") or _trace_channel(trace)),
        "user_id": str(trace_input.get("user_id") or _get_attr(trace, "user_id", None) or "curated-user"),
        "text": str(trace_input.get("text") or ""),
        "context": trace_input.get("context") if isinstance(trace_input.get("context"), dict) else {},
        "attachments": attachments,
        "attachment_placeholders": trace_attachments,
        "attachment_manifests": attachment_manifests,
    }
    _copy_demo_sales_trace_fields(trace_input, normalized)
    return normalized


def _copy_demo_sales_trace_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in DEMO_SALES_INPUT_KEYS:
        if key in source:
            target[key] = source[key]
    scenario = source.get("scenario")
    if isinstance(scenario, dict):
        if "scenario_id" in scenario:
            target.setdefault("scenario_id", scenario["scenario_id"])
        if "scenario_version" in scenario:
            target.setdefault("scenario_version", scenario["scenario_version"])
        if "params" in scenario:
            target.setdefault("scenario_params", scenario["params"])
    if "mock_state" in source:
        target.setdefault("state_before_turn", source["mock_state"])


def _attachment_manifests_from_trace(
    trace: Any,
    *,
    spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trace_id = _get_attr(trace, "trace_id", None) or _get_attr(trace, "id", None)
    manifests: list[dict[str, Any]] = []
    for span in spans:
        if span.get("trace_id") != trace_id or span.get("name") != "attachments.prepare":
            continue
        output = _jsonish(span.get("output"))
        if not isinstance(output, dict):
            continue
        for attachment in _as_list(output.get("attachments", [])):
            if isinstance(attachment, dict):
                manifests.append(attachment)
    return manifests


def _span_row_to_trace(row: dict[str, Any]) -> dict[str, Any]:
    attrs = _attributes_from_row(row)
    metadata = _jsonish(attrs.get("metadata")) or {}
    input_payload = _jsonish(attrs.get("input.value"))
    output_payload = _jsonish(attrs.get("output.value"))
    tags = _jsonish(attrs.get("tag.tags"))
    return {
        "id": _clean(row.get("context.trace_id") or row.get("trace_id")),
        "trace_id": _clean(row.get("context.trace_id") or row.get("trace_id")),
        "span_id": _clean(row.get("context.span_id") or row.get("span_id")),
        "parent_id": _clean(row.get("parent_id") or row.get("parent.span_id")),
        "name": _clean(row.get("name")),
        "timestamp": _clean(row.get("start_time") or row.get("startTime")),
        "session_id": _clean(attrs.get("session.id") or attrs.get("sumampa.transport.conversation_id")),
        "user_id": _clean(attrs.get("user.id") or attrs.get("enduser.id")),
        "input": input_payload,
        "output": output_payload,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "tags": tags if isinstance(tags, list) else _split_csv(attrs.get("sumampa.tags")),
    }


def _attributes_from_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for key, value in row.items():
        clean_value = _clean(value)
        if clean_value is None:
            continue
        if key.startswith("attributes."):
            attrs[key.removeprefix("attributes.")] = clean_value
        elif key in {
            "input.value",
            "output.value",
            "metadata",
            "tag.tags",
            "session.id",
            "user.id",
            "enduser.id",
            "sumampa.tags",
        }:
            attrs[key] = clean_value
    return attrs


def _matches_session(trace: dict[str, Any], session_id: str | None) -> bool:
    return session_id is None or trace.get("session_id") == session_id


def _matches_tags(trace: dict[str, Any], tags: list[str]) -> bool:
    if not tags:
        return True
    trace_tags = _as_list(trace.get("tags"))
    return all(tag in trace_tags for tag in tags)


def _trace_conversation_id(trace: Any) -> str:
    metadata = _jsonish(_get_attr(trace, "metadata", {}) or {})
    trace_input = _jsonish(_get_attr(trace, "input", None))
    return str(
        _get_attr(trace, "session_id", None)
        or (metadata.get("transport.conversation_id") if isinstance(metadata, dict) else None)
        or (trace_input.get("conversation_id") if isinstance(trace_input, dict) else None)
        or "curated-trace"
    )


def _trace_channel(trace: Any) -> str:
    metadata = _jsonish(_get_attr(trace, "metadata", {}) or {})
    return str(metadata.get("transport.channel") if isinstance(metadata, dict) else "whatsapp")


def _jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _split_csv(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        return value
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    main()
