"""The agent's system prompt, authored as markdown in instructions.md."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings

# Beside this module, not relative to the working directory: `make dev-backend` runs from backend/ while the
# container runs from /srv. Docker's `COPY app/ app/` and the compose mount of ./backend/app both carry .md.
_INSTRUCTIONS = Path(__file__).parent / "instructions.md"
_INSTRUCTIONS_MD = _INSTRUCTIONS.read_text(encoding="utf-8")

# An agent with no instructions answers from general knowledge and cites nothing,
# which is exactly the failure the prompt exists to prevent. Fail at import.
if not _INSTRUCTIONS_MD.strip():
    raise RuntimeError(f"agent instructions are empty: {_INSTRUCTIONS}")


def render_prompt(settings: Settings) -> str:
    """The wave size, as Import does it: a plain replace, because the file is full of literal braces."""
    return _INSTRUCTIONS_MD.replace("{{MAX_PARALLEL_RESEARCH}}", str(settings.max_parallel_research))


# For tests and tooling; build_agent renders from the Settings it was given.
SYSTEM_PROMPT = render_prompt(get_settings())


def subagent_prompt(name: str) -> str:
    """A subagent's instructions, from prompts/<name>.md beside this module."""
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"subagent prompt is empty: {path}")
    return text
