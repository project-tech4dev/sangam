"""Who an Import run works for, as the tools see it: they run on the owner pool, so RLS does not apply."""

from __future__ import annotations

from typing import Any

from app.core.security import CallerScope, chat_scope
from app.ingest.source_guards import is_private_source


def scope() -> CallerScope:
    """The run's caller; outside a chat request nobody, so every gated tool refuses."""
    return chat_scope.get() or CallerScope(user_id=None, is_staff=False)


def staff_only(tool: str) -> str | None:
    """A refusal for a non-staff caller, else None."""
    if scope().is_staff:
        return None
    return (f"REFUSED: {tool} is for the Sangam team only. Do not call it again in this run; "
            "offer research from public websites instead.")


def without_private(row: dict[str, Any]) -> dict[str, Any]:
    """A research row with staff-spreadsheet and vault findings removed, for a caller who is not staff."""
    findings = row.get("findings") or []
    public = [f for f in findings if not is_private_source(f.get("source_url"))]
    if len(public) == len(findings):
        return row
    return {**row, "findings": public, "fact_count": len(public), "private_removed": True,
            "sources_read": [u for u in row.get("sources_read") or [] if not is_private_source(u)]}


def caller_note(s: CallerScope) -> str:
    """The supervisor's per-run line on who it is working for and what they may do."""
    if s.is_staff:
        return "You are working for the Sangam team. Every task in these instructions is open to them."
    supported = [s.org_names.get(o, f"org {o}") for o in s.steward_of]
    own = [s.org_names.get(o, f"org {o}") for o in s.org_roles if o not in s.steward_of]
    lines = ["You are working for someone outside the Sangam team."]
    if supported:
        lines.append(f"They support these NGOs as a steward: {', '.join(supported)}. They may research "
                     "and save any funder, and these NGOs only.")
    else:
        who = f"a member of {', '.join(own)}" if own else "a signed-in user"
        lines.append(f"They are {who}. They may research and save funders only, not NGOs.")
    lines.append("Team spreadsheets are the Sangam team's: never propose staff_paths in choose_sources.")
    lines.append("The adapter pipeline, news imports, the review queue and registry checks are for the Sangam "
                 "team: if asked, say so in one line and offer funder research from public websites instead.")
    return "\n".join(lines)
