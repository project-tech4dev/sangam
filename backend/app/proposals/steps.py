"""What stops a proposal leaving its step, in words. Pure; REST's /advance and the agent both ask it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.proposals import readiness, rubric

# The screen's names for work.stage, as frontend/features/ask/views/proposals/steps.ts writes them.
STAGES = {1: "Can you apply?", 2: "Your documents and style", 3: "Make a case", 4: "Make a plan",
          5: "Before you send it"}
LAST = max(STAGES)
CASE_FIRST = ("A2", "A3")  # the place and the problem; the Summary waits for the plan


def exit_check(stage: int, work: dict[str, Any]) -> list[str]:
    """What is missing before `stage` can be left; empty means it can."""
    if stage == 1:
        gates = work.get("gates") or {}
        missing = [f"answer {r['label']}" for r in work.get("requirements") or []
                   if gates.get(r["key"]) not in readiness.ANSWERS]
        stopped = [f"{r['label']} is needed by the funder" for r in work.get("requirements") or []
                   if r.get("hard") and gates.get(r["key"]) == "no"]
        return missing + stopped
    if stage == 2:
        missing = []
        if not work.get("template") and not work.get("skipped_template"):
            missing.append("add the funder's form, or choose Sangam's usual order")
        if not (work.get("style") or "").strip():
            missing.append("set the writing style")
        # A public search alone does not read the files.
        readers = {k: r for k, r in (work.get("readers") or {}).items() if k != "public"}
        if not readers:
            missing.append("press Write the first draft")
        elif any(r.get("status") == "running" and not readers_stale(r) for r in readers.values()):
            missing.append("wait until the files are read")
        return missing
    if stage == 3:
        saved = work.get("sections") or {}
        labels = {s.code: s.label for s in rubric.CORE}
        return [f"write {labels[c]}" for c in CASE_FIRST if not ((saved.get(c) or {}).get("text") or "").strip()]
    if stage == 4:
        return []
    return ["this is the last step"]


def blocking(work: dict[str, Any], to: int) -> list[str]:
    """What stops a jump from the open step to `to`: every step passed on the way must be leavable."""
    return next((m for s in range(int(work.get("stage") or 1), to) if (m := exit_check(s, work))), [])


def furthest(work: dict[str, Any]) -> int:
    """The last step the person can click to from here."""
    stage = int(work.get("stage") or 1)
    while stage < LAST and not exit_check(stage, work):
        stage += 1
    return stage


# The step each writing tool may first be used on; the tools check, not the prompt.
FIRST_STAGE = {"add_facts": 2, "read_files": 2, "ask_user": 3, "write_section": 3, "suggest_edit": 3}
READING_STALE = timedelta(minutes=30)  # a run lasts 1800 s at most, so a "running" older than that died


def readers_stale(reader: dict[str, Any], now: datetime | None = None) -> bool:
    """A reader still marked running after the longest a run can last: its browser or function went away."""
    try:
        at = datetime.fromisoformat(str(reader.get("at")))
    except ValueError:
        return True
    return (now or datetime.now(UTC)) - at > READING_STALE


def too_early(tool: str, stage: int) -> str | None:
    first = FIRST_STAGE.get(tool, 1)
    return None if stage >= first else f"{tool} is used from step {first}, {STAGES[first]}; this is step {stage}"


def may_write(work: dict[str, Any], code: str, on_screen: str | None) -> str | None:
    """Sections are written in DEPENDS_ON order, unless the person has this one open: then it is their pick.
    The Summary is the exception: it sums up the plan, so it always waits for every other part."""
    if code == on_screen and code != "A1":
        return None
    codes = [s.code for s in rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))]
    saved = work.get("sections") or {}
    waiting = [c for c in rubric.depends_on(code, codes) if not (saved.get(c) or {}).get("text", "").strip()]
    if not waiting:
        return None
    labels = {s.code: s.label for s in rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))}
    return f"write {', '.join(f'{labels[c]} [{c}]' for c in waiting)} first, or have the person open this part"
