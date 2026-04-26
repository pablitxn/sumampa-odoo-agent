"""Export tagged Langfuse conversations with optional Postgres session enrichment."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from langfuse import Langfuse

from sumampa_odoo_agent.config import AppSettings, load_settings
from sumampa_odoo_agent.integrations.agent.service import AGENT_SESSION_NAMESPACE
from sumampa_odoo_agent.integrations.sessions.postgres import PostgresSessionStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=None, help="PYTHON_ENV-compatible config environment")
    parser.add_argument("--tag", action="append", dest="tags", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--from-timestamp", type=_parse_datetime, default=None)
    parser.add_argument("--to-timestamp", type=_parse_datetime, default=None)
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--no-postgres", action="store_true")
    parser.add_argument("--include-session-payload", action="store_true")
    parser.add_argument("--json-array", action="store_true")
    args = parser.parse_args()

    settings = load_settings(env=args.env)
    client = _build_langfuse_client(settings)
    traces = _fetch_tagged_traces(
        client,
        settings=settings,
        tags=args.tags,
        limit=args.limit,
        session_id=args.session_id,
        from_timestamp=args.from_timestamp,
        to_timestamp=args.to_timestamp,
    )
    exports = asyncio.run(
        _build_conversation_exports(
            traces,
            postgres_dsn=args.postgres_dsn or settings.session_store.postgres_dsn,
            include_postgres=not args.no_postgres,
            include_session_payload=args.include_session_payload,
        )
    )
    _write_exports(exports, json_array=args.json_array)


def _fetch_tagged_traces(
    client: Langfuse,
    *,
    settings: AppSettings,
    tags: list[str],
    limit: int,
    session_id: str | None,
    from_timestamp: datetime | None,
    to_timestamp: datetime | None,
) -> list[Any]:
    traces_response = client.api.trace.list(
        limit=limit,
        session_id=session_id,
        tags=tags,
        environment=settings.observability.environment,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )
    traces = _as_list(_get_attr(traces_response, "data", []))
    detailed_traces: list[Any] = []
    for trace in traces:
        trace_id = _trace_id(trace)
        detailed_traces.append(
            _load_trace_details(client, trace_id, fallback=trace) if trace_id else trace
        )
    return detailed_traces


async def _build_conversation_exports(
    traces: list[Any],
    *,
    postgres_dsn: str,
    include_postgres: bool,
    include_session_payload: bool,
) -> list[dict[str, Any]]:
    conversation_ids = sorted({_trace_conversation_id(trace) for trace in traces})
    postgres_payloads: dict[str, dict[str, Any]] = {}
    postgres_errors: dict[str, str] = {}
    if include_postgres and conversation_ids:
        postgres_payloads, postgres_errors = await _load_postgres_payloads(
            postgres_dsn=postgres_dsn,
            conversation_ids=conversation_ids,
        )
    return _conversation_exports_from_traces(
        traces,
        postgres_payloads=postgres_payloads,
        postgres_errors=postgres_errors,
        include_session_payload=include_session_payload,
    )


def _conversation_exports_from_traces(
    traces: list[Any],
    *,
    postgres_payloads: Mapping[str, dict[str, Any]] | None = None,
    postgres_errors: Mapping[str, str] | None = None,
    include_session_payload: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for trace in traces:
        grouped[_trace_conversation_id(trace)].append(trace)

    exports: list[dict[str, Any]] = []
    for conversation_id in sorted(grouped):
        conversation_traces = sorted(grouped[conversation_id], key=_trace_sort_key)
        payload = (postgres_payloads or {}).get(conversation_id)
        eval_tags = _merge_tags(
            *(_trace_eval_tags(trace) for trace in conversation_traces),
            _postgres_eval_tags(payload),
        )
        messages = [
            message
            for trace in conversation_traces
            for message in _messages_from_trace(trace)
        ]
        exports.append(
            {
                "conversation_id": conversation_id,
                "eval_tags": eval_tags,
                "traces": [_trace_summary(trace) for trace in conversation_traces],
                "messages": messages,
                "postgres": _postgres_summary(
                    payload,
                    error=(postgres_errors or {}).get(conversation_id),
                    include_session_payload=include_session_payload,
                ),
            }
        )
    return exports


async def _load_postgres_payloads(
    *,
    postgres_dsn: str,
    conversation_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    store = PostgresSessionStore(dsn=postgres_dsn)
    payloads: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    try:
        for conversation_id in conversation_ids:
            try:
                payload = await store.load(
                    namespace=AGENT_SESSION_NAMESPACE,
                    session_id=conversation_id,
                )
            except Exception as exc:
                errors[conversation_id] = f"{exc.__class__.__name__}: {exc}"
                continue
            if payload is not None:
                payloads[conversation_id] = payload
    finally:
        await store.aclose()
    return payloads, errors


def _messages_from_trace(trace: Any) -> list[dict[str, Any]]:
    trace_id = _trace_id(trace)
    timestamp = _trace_timestamp(trace)
    trace_input = _jsonish(_get_attr(trace, "input", None))
    trace_output = _jsonish(_get_attr(trace, "output", None))
    messages: list[dict[str, Any]] = []

    if isinstance(trace_input, dict):
        text = str(trace_input.get("text") or "")
        attachments = [
            _safe_attachment_payload(attachment)
            for attachment in _as_list(trace_input.get("attachments", []))
            if isinstance(attachment, dict)
        ]
    else:
        text = str(trace_input or "")
        attachments = []

    if text or attachments:
        messages.append(
            {
                "role": "user",
                "text": text,
                "attachments": attachments,
                "trace_id": trace_id,
                "timestamp": timestamp,
            }
        )

    assistant_text = _assistant_text_from_output(trace_output)
    if assistant_text:
        messages.append(
            {
                "role": "assistant",
                "text": assistant_text,
                "trace_id": trace_id,
                "timestamp": timestamp,
            }
        )

    return messages


def _messages_from_session_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    state = payload.get("state")
    if not isinstance(state, dict):
        return []
    in_memory = state.get("in_memory")
    if not isinstance(in_memory, dict):
        return []
    return [
        message
        for raw_message in _as_list(in_memory.get("messages", []))
        if isinstance(raw_message, dict)
        for message in [_agent_message_payload(raw_message)]
        if message is not None
    ]


def _agent_message_payload(raw_message: dict[str, Any]) -> dict[str, Any] | None:
    role = raw_message.get("role")
    contents = _as_list(raw_message.get("contents", []))
    text_parts = [
        str(content.get("text"))
        for content in contents
        if isinstance(content, dict) and content.get("type") == "text" and content.get("text")
    ]
    attachments = [
        _agent_content_attachment(content)
        for content in contents
        if isinstance(content, dict) and content.get("type") != "text"
    ]
    text = " ".join(text_parts).strip()
    if not role or (not text and not attachments):
        return None
    payload: dict[str, Any] = {
        "role": str(role),
        "text": text,
        "attachments": attachments,
    }
    message_id = raw_message.get("message_id")
    if message_id:
        payload["message_id"] = str(message_id)
    return payload


def _agent_content_attachment(content: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": str(content.get("type") or "unknown"),
    }
    media_type = content.get("media_type")
    if media_type:
        payload["media_type"] = str(media_type)
    additional_properties = content.get("additional_properties")
    if isinstance(additional_properties, dict) and additional_properties.get("filename"):
        payload["filename"] = str(additional_properties["filename"])
    uri = content.get("uri")
    if isinstance(uri, str):
        if uri.startswith("data:"):
            payload["has_data_uri"] = True
        else:
            payload["uri"] = uri
    return payload


def _postgres_summary(
    payload: dict[str, Any] | None,
    *,
    error: str | None,
    include_session_payload: bool,
) -> dict[str, Any]:
    if payload is None:
        summary: dict[str, Any] = {"found": False}
        if error:
            summary["error"] = error
        return summary

    messages = _messages_from_session_payload(payload)
    summary = {
        "found": True,
        "eval_tags": _postgres_eval_tags(payload),
        "message_count": len(messages),
        "messages": messages,
    }
    if include_session_payload:
        summary["session_payload"] = payload
    return summary


def _postgres_eval_tags(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    state = payload.get("state")
    if not isinstance(state, dict):
        return []
    sumampa_state = state.get("sumampa")
    if not isinstance(sumampa_state, dict):
        return []
    return _merge_tags(sumampa_state.get("eval_tags", []))


def _trace_summary(trace: Any) -> dict[str, Any]:
    return {
        "trace_id": _trace_id(trace),
        "timestamp": _trace_timestamp(trace),
    }


def _trace_eval_tags(trace: Any) -> list[str]:
    trace_input = _jsonish(_get_attr(trace, "input", None))
    metadata = _jsonish(_get_attr(trace, "metadata", {})) or {}
    tags = _as_list(_get_attr(trace, "tags", []))
    input_tags = trace_input.get("eval_tags", []) if isinstance(trace_input, dict) else []
    metadata_tags = metadata.get("eval.tags", []) if isinstance(metadata, dict) else []
    metadata_tags_csv = metadata.get("evalTags") if isinstance(metadata, dict) else None
    langfuse_eval_tags = [tag for tag in tags if isinstance(tag, str) and tag.startswith("eval:")]
    return _merge_tags(input_tags, metadata_tags, _split_csv(metadata_tags_csv), langfuse_eval_tags)


def _trace_conversation_id(trace: Any) -> str:
    metadata = _jsonish(_get_attr(trace, "metadata", {})) or {}
    trace_input = _jsonish(_get_attr(trace, "input", None))
    candidates = [
        _get_attr(trace, "session_id", None),
        _get_attr(trace, "sessionId", None),
        metadata.get("transport.conversation_id") if isinstance(metadata, dict) else None,
        trace_input.get("conversation_id") if isinstance(trace_input, dict) else None,
    ]
    return next((str(candidate) for candidate in candidates if candidate), "unknown-conversation")


def _trace_id(trace: Any) -> str:
    value = _get_attr(trace, "id", None)
    return str(value) if value else ""


def _trace_timestamp(trace: Any) -> str | None:
    for field in ("timestamp", "created_at", "createdAt", "start_time", "startTime"):
        value = _get_attr(trace, field, None)
        if isinstance(value, datetime):
            return value.isoformat()
        if value:
            return str(value)
    return None


def _trace_sort_key(trace: Any) -> tuple[str, str]:
    return (_trace_timestamp(trace) or "", _trace_id(trace))


def _assistant_text_from_output(trace_output: Any) -> str:
    if isinstance(trace_output, dict):
        return str(trace_output.get("assistant_text") or trace_output.get("text") or "")
    return str(trace_output or "")


def _safe_attachment_payload(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in attachment.items()
        if key not in {"content_base64", "content_bytes"}
    }


def _build_langfuse_client(settings: AppSettings) -> Langfuse:
    return Langfuse(
        public_key=os.environ.get(settings.observability.public_key_env_var),
        secret_key=os.environ.get(settings.observability.secret_key_env_var),
        base_url=settings.observability.base_url,
        environment=settings.observability.environment,
    )


def _load_trace_details(client: Langfuse, trace_id: str, *, fallback: Any) -> Any:
    try:
        return client.api.trace.get(trace_id)
    except Exception as exc:
        print(f"trace {trace_id} detail fetch failed, using list payload: {exc}", file=sys.stderr)
        return fallback


def _write_exports(exports: list[dict[str, Any]], *, json_array: bool) -> None:
    if json_array:
        print(json.dumps(exports, ensure_ascii=False, indent=2, default=str))
        return
    for export in exports:
        print(json.dumps(export, ensure_ascii=False, default=str))


def _merge_tags(*tag_groups: Any) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag_group in tag_groups:
        if isinstance(tag_group, str):
            candidates: list[Any] = [tag_group]
        elif isinstance(tag_group, list | tuple | set):
            candidates = list(tag_group)
        else:
            continue
        for candidate in candidates:
            tag = str(candidate).strip()
            if not tag:
                continue
            tag = tag[:200]
            if tag in seen:
                continue
            tags.append(tag)
            seen.add(tag)
    return tags


def _split_csv(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


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
