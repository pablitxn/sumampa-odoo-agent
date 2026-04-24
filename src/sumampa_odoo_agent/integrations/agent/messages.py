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
    return (
        f"{prompt}\n\n"
        "Contexto JSON:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )
