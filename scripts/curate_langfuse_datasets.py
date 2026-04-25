"""Promote Langfuse traces into curated dataset items."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any

from langfuse import Langfuse

from sumampa_odoo_agent.config import AppSettings, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_name", help="Target Langfuse dataset name")
    parser.add_argument("--env", default=None, help="ORCHID_ENV-compatible config environment")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--tag", action="append", dest="tags", default=[])
    parser.add_argument("--from-timestamp", type=_parse_datetime, default=None)
    parser.add_argument("--to-timestamp", type=_parse_datetime, default=None)
    parser.add_argument(
        "--use-output-as-expected",
        action="store_true",
        help="Use trace output as expected output for already-reviewed traces.",
    )
    args = parser.parse_args()

    settings = load_settings(env=args.env)
    client = _build_langfuse_client(settings)

    traces_response = client.api.trace.list(
        limit=args.limit,
        session_id=args.session_id,
        tags=args.tags or None,
        environment=settings.observability.environment,
        from_timestamp=args.from_timestamp,
        to_timestamp=args.to_timestamp,
    )
    traces = _get_attr(traces_response, "data", [])

    created = 0
    for trace in traces:
        trace_id = str(_get_attr(trace, "id", ""))
        detailed_trace = _load_trace_details(client, trace_id) if trace_id else trace
        item = _dataset_item_from_trace(
            detailed_trace or trace,
            use_output_as_expected=args.use_output_as_expected,
        )
        try:
            client.create_dataset_item(dataset_name=args.dataset_name, **item)
            created += 1
            print(f"created item from trace {item['source_trace_id']}")
        except Exception as exc:
            print(f"trace {item['source_trace_id']} skipped or failed: {exc}")

    client.flush()
    print(f"created {created} dataset items in {args.dataset_name}")


def _dataset_item_from_trace(trace: Any, *, use_output_as_expected: bool) -> dict[str, Any]:
    trace_id = str(_get_attr(trace, "id", ""))
    trace_input = _get_attr(trace, "input", None)
    trace_output = _get_attr(trace, "output", None)
    metadata = _get_attr(trace, "metadata", {}) or {}
    tags = _get_attr(trace, "tags", []) or []
    attachment_manifests = _attachment_manifests_from_trace(trace)
    expected_output = trace_output if use_output_as_expected else None
    return {
        "id": trace_id or None,
        "input": _normalize_conversation_input(
            trace_input,
            trace=trace,
            attachment_manifests=attachment_manifests,
        ),
        "expected_output": expected_output,
        "metadata": {
            "source": "langfuse_trace",
            "source_trace_id": trace_id,
            "source_session_id": _get_attr(trace, "session_id", None),
            "source_user_id": _get_attr(trace, "user_id", None),
            "source_tags": tags,
            "source_metadata": metadata,
            "attachment_manifests": attachment_manifests,
            "requires_expected_output_review": not use_output_as_expected,
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
    return {
        "conversation_id": str(trace_input.get("conversation_id") or _trace_conversation_id(trace)),
        "channel": str(trace_input.get("channel") or _trace_channel(trace)),
        "user_id": str(trace_input.get("user_id") or _get_attr(trace, "user_id", None) or "curated-user"),
        "text": str(trace_input.get("text") or ""),
        "context": trace_input.get("context") if isinstance(trace_input.get("context"), dict) else {},
        "attachments": attachments,
        "attachment_placeholders": trace_attachments,
        "attachment_manifests": attachment_manifests,
    }


def _attachment_manifests_from_trace(trace: Any) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for observation in _as_list(_get_attr(trace, "observations", [])):
        if _get_attr(observation, "name", None) != "attachments.prepare":
            continue
        output = _jsonish(_get_attr(observation, "output", None))
        if not isinstance(output, dict):
            continue
        for attachment in _as_list(output.get("attachments", [])):
            if isinstance(attachment, dict):
                manifests.append(attachment)
    return manifests


def _load_trace_details(client: Langfuse, trace_id: str) -> Any | None:
    try:
        return client.api.trace.get(trace_id)
    except Exception as exc:
        print(f"trace {trace_id} detail fetch failed, using list payload: {exc}")
        return None


def _build_langfuse_client(settings: AppSettings) -> Langfuse:
    return Langfuse(
        public_key=os.environ.get(settings.observability.public_key_env_var),
        secret_key=os.environ.get(settings.observability.secret_key_env_var),
        base_url=settings.observability.base_url,
        environment=settings.observability.environment,
    )


def _trace_conversation_id(trace: Any) -> str:
    metadata = _get_attr(trace, "metadata", {}) or {}
    return str(
        _get_attr(trace, "session_id", None)
        or _get_attr(trace, "sessionId", None)
        or metadata.get("transport.conversation_id")
        or "curated-trace"
    )


def _trace_channel(trace: Any) -> str:
    metadata = _get_attr(trace, "metadata", {}) or {}
    return str(metadata.get("transport.channel") or "whatsapp")


def _jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    main()
