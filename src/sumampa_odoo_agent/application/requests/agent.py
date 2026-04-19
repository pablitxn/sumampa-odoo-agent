"""Application request models for agent interactions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunAgentCommand(BaseModel):
    prompt: str = Field(min_length=1)
    session_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
