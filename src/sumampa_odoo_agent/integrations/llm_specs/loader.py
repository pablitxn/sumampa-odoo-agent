"""Load versioned LLM specs from the integrations package."""

from __future__ import annotations

from pathlib import Path

LLM_SPECS_ROOT = Path(__file__).resolve().parent


def resolve_llm_spec_path(spec_path: str) -> Path:
    candidate = (LLM_SPECS_ROOT / spec_path).resolve()
    if not str(candidate).startswith(str(LLM_SPECS_ROOT)):
        raise ValueError(f"Invalid llm spec path outside root: {spec_path}")
    if not candidate.exists():
        raise FileNotFoundError(f"Missing llm spec: {spec_path}")
    return candidate


def load_llm_spec(spec_path: str) -> str:
    return resolve_llm_spec_path(spec_path).read_text(encoding="utf-8").strip()


def render_llm_spec(spec_path: str, **context: object) -> str:
    template = load_llm_spec(spec_path)
    return template.format(**context)
