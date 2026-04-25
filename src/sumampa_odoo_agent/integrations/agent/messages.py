"""Message formatting for agent runtime requests."""

from __future__ import annotations

import json
from typing import Any


def _build_agent_message(
    *,
    prompt: str,
    context: dict[str, Any],
) -> str:
    if not context:
        return prompt
    context_message = (
        "JSON context:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )
    if not prompt:
        return context_message
    return (
        f"{prompt}\n\n"
        f"{context_message}"
    )
