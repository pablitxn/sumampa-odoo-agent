"""Helpers for Sumampa metadata stored in Agent Framework session payloads."""

from __future__ import annotations

from typing import Any

AGENT_SESSION_NAMESPACE = "agent"


def normalize_eval_tags(*tag_groups: Any) -> list[str]:
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


def with_merged_eval_tags(payload: dict[str, Any], eval_tags: list[str]) -> dict[str, Any]:
    sumampa_state = _ensure_sumampa_state(payload)
    sumampa_state["eval_tags"] = normalize_eval_tags(
        sumampa_state.get("eval_tags", []),
        eval_tags,
    )
    return payload


def with_current_eval_tags(
    payload: dict[str, Any] | None,
    *,
    session_id: str,
    eval_tags: list[str],
) -> dict[str, Any]:
    session_payload = payload or {
        "type": "session",
        "session_id": session_id,
        "service_session_id": None,
        "state": {},
    }
    session_payload.setdefault("type", "session")
    session_payload.setdefault("session_id", session_id)
    session_payload.setdefault("service_session_id", None)
    sumampa_state = _ensure_sumampa_state(session_payload)
    sumampa_state["eval_tags"] = normalize_eval_tags(eval_tags)
    return session_payload


def has_current_eval_tags(payload: dict[str, Any] | None) -> bool:
    sumampa_state = _sumampa_state(payload)
    return isinstance(sumampa_state, dict) and "eval_tags" in sumampa_state


def current_eval_tags(payload: dict[str, Any] | None) -> list[str]:
    sumampa_state = _sumampa_state(payload)
    if not isinstance(sumampa_state, dict):
        return []
    return normalize_eval_tags(sumampa_state.get("eval_tags", []))


def _ensure_sumampa_state(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state")
    if not isinstance(state, dict):
        state = {}
        payload["state"] = state

    sumampa_state = state.get("sumampa")
    if not isinstance(sumampa_state, dict):
        sumampa_state = {}
        state["sumampa"] = sumampa_state
    return sumampa_state


def _sumampa_state(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    sumampa_state = state.get("sumampa")
    return sumampa_state if isinstance(sumampa_state, dict) else None
