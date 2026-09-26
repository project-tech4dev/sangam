"""The agent's system prompt, authored as markdown in instructions.md.

Kept as a module so `SYSTEM_PROMPT` stays importable and the loading rule lives
in one place. The prompt text moved to markdown so it can be edited and reviewed
as prose — a diff of the agent's instructions should read like a diff of writing,
not of a quoted Python string.
"""

from __future__ import annotations

from pathlib import Path

# Beside this module, not relative to the working directory: `make dev-backend`
# runs from backend/ while the container runs from /srv. Docker's `COPY app/ app/`
# and the compose mount of ./backend/app both carry .md files, so it ships on
# every path — but only because it lives INSIDE the package.
_INSTRUCTIONS = Path(__file__).parent / "instructions.md"

SYSTEM_PROMPT = _INSTRUCTIONS.read_text(encoding="utf-8")

# An agent with no instructions answers from general knowledge and cites nothing,
# which is exactly the failure the prompt exists to prevent. Fail at import.
if not SYSTEM_PROMPT.strip():
    raise RuntimeError(f"agent instructions are empty: {_INSTRUCTIONS}")
