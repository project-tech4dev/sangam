"""What `create_deep_agent` adds that we did not ask for, taken back out.

Two things arrive with the preset and neither is wanted by default.

**Eight filesystem tools** — `ls`, `read_file`, `write_file`, `edit_file`,
`delete`, `glob`, `grep`, `execute` — come from `FilesystemMiddleware`.
Against the default `StateBackend` they operate on virtual files in graph
state, so they do nothing useful, and `execute` answers "Execution not
available" because state is not a sandbox. They were still advertised in every
request, to agents whose job is reading untrusted web pages.

**A `general-purpose` subagent**, inserted whenever any subagent is declared,
carrying *the main agent's entire tool list* and deepagents' generic prompt.
On Sangam Import that meant a subagent that could call `run_import_now` and
`promote_research` — both of which write — with none of the instructions: no
research budget, no entity confirmation, no evidence floor, no access rules.
`entity-researcher` is carefully constrained and had an unconstrained sibling
offering the same tools.

The two are removed by different mechanisms, and the difference matters. A
harness profile is registered per **provider**, so it is global to every agent
sharing a model — right for the subagent, wrong for tools, since both
supervisors need `ls` to find a skill and no subagent may hold it.
`FilesystemMiddleware` passed in `middleware=` replaces the default one **per
agent**, which is where the tool surface is decided — and per *subagent* too:
an isolated one builds its own stack and inherits none of the parent's, so
`app/ingest/agent.py` declares this on each spec as well. Left to the library
both subagents run the full eight against whatever backend they are handed.
"""

from __future__ import annotations

from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from deepagents.middleware.filesystem import FilesystemMiddleware

# Added by FilesystemMiddleware, and none of them registered by us.
FILESYSTEM_TOOLS: frozenset[str] = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"}
)

# FilesystemMiddleware refuses to be built without read_file, so one of the
# eight always remains. On a subagent it is the floor the library imposes, not
# a capability it uses.
REQUIRED_MINIMUM: tuple[str, ...] = ("read_file",)

# Both supervisors keep ls as well. deepagents has no dedicated tool for loading
# a skill: the model reads a SKILL.md with read_file, and ls is how it recovers
# when a path in the prompt has gone stale. Nothing that writes is kept — on
# the parent, or on a subagent, whose spec has to ask for this separately.
SKILL_READING_TOOLS: tuple[str, ...] = ("read_file", "ls")

# Every provider app/agent/models.py can resolve. An exact `provider:model`
# key would only cover the model configured today.
PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "google", "google_genai")

_installed = False


def install() -> None:
    """Disable the general-purpose subagent. Idempotent; call before building.

    Profile-level because that is the only switch deepagents offers for it,
    and global is what we want: neither agent should have one.
    """
    global _installed
    if _installed:
        return
    profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
    )
    for provider in PROVIDERS:
        register_harness_profile(provider, profile)
    _installed = True


def filesystem(
    backend: Any, *, keep: tuple[str, ...] = REQUIRED_MINIMUM, evict_at: int | None = None, evict: bool = True
) -> FilesystemMiddleware:
    """A FilesystemMiddleware exposing only `keep`, replacing the default.

    `create_deep_agent` merges custom middleware by name, so this takes the
    place of the stack's own FilesystemMiddleware rather than adding to it —
    and an excluded name is never registered, not merely hidden. `evict_at` lowers the token size at
    which a tool result is moved to a file the model pages back; unset keeps the library's 20k.
    """
    if not evict:
        # Nothing moved to a file: a file outlives the agent that wrote it, in the parent's state.
        return FilesystemMiddleware(backend=backend, tools=list(keep), tool_token_limit_before_evict=None)
    if evict_at is None:
        return FilesystemMiddleware(backend=backend, tools=list(keep))
    return FilesystemMiddleware(backend=backend, tools=list(keep), tool_token_limit_before_evict=evict_at)
