"""What `create_deep_agent` adds that we did not ask for, taken back out.

Two things arrive with the preset and neither is wanted here.

**Eight filesystem tools** — `ls`, `read_file`, `write_file`, `edit_file`,
`delete`, `glob`, `grep`, `execute` — come from `FilesystemMiddleware`. Against
the default `StateBackend` they operate on virtual files in graph state, so
they do nothing useful for either agent, and `execute` answers "Execution not
available" because state is not a sandbox. They were still advertised in every
request, to agents whose job is reading untrusted web pages. The frontend used
to hide them from the trace, which treated the symptom.

**A `general-purpose` subagent**, inserted whenever any subagent is declared,
carrying *the main agent's entire tool list* and deepagents' generic prompt. On
Sangam Import that meant a subagent that could call `run_import_now` and
`promote_research` — both of which write — with none of the instructions:
no research budget, no entity confirmation, no evidence floor, no access rules.
`entity-researcher` is carefully constrained and had an unconstrained sibling
offering the same tools.

A harness profile is keyed by model, and deepagents registers none of its own,
so registering at the provider level covers every model we resolve.
"""

from __future__ import annotations

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

# Added by FilesystemMiddleware. Skills read a SKILL.md with read_file, so if
# app/ingest/skills ever lands, that one name comes back — scoped to the route
# a CompositeBackend gives it, not the whole tool.
FILESYSTEM_TOOLS: frozenset[str] = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"}
)

# Every provider app/agent/models.py can resolve. An exact `provider:model` key
# would only cover the model configured today.
PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "google", "google_genai")

_installed = False


def install() -> None:
    """Register the profile. Idempotent, and called before either agent builds."""
    global _installed
    if _installed:
        return
    profile = HarnessProfile(
        excluded_tools=FILESYSTEM_TOOLS,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )
    for provider in PROVIDERS:
        register_harness_profile(provider, profile)
    _installed = True
