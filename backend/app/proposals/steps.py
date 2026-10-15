"""What stops a proposal leaving its step, in words. Pure; REST's /advance and the agent both ask it."""

from __future__ import annotations

from typing import Any

from app.proposals import readiness


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
        return missing
    if stage == 3:
        return []
    return ["this is the last step"]
