"""`summary(work)`: what the list and "Before you send it" show, recomputed on every save. Pure.

Lines are plain words for the screen: section labels, never codes.
"""

from __future__ import annotations

import re
from typing import Any

from app.proposals import rubric

ANSWERS = ("yes", "will_have", "no")
_GAP = re.compile(r"\[Add:[^\]]*\]")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary(work: dict[str, Any]) -> dict[str, Any]:
    from app.proposals import steps  # steps reads ANSWERS from here

    requirements = work.get("requirements") or []
    gates = work.get("gates") or {}
    sections = work.get("sections") or {}
    facts = (work.get("facts") or {}).values()
    questions = (work.get("questions") or {}).values()
    conflicts = [c for c in work.get("conflicts") or [] if not c.get("settled")]
    all_sections = rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))

    fix_first: list[str] = []
    worth_checking: list[str] = []
    for r in requirements:
        answer = gates.get(r["key"])
        if answer not in ANSWERS:
            fix_first.append(f"Answer: {r['label']}")
        elif answer == "no":
            (fix_first if r.get("hard") else worth_checking).append(
                f"{r['label']}: the funder needs it" if r.get("hard") else f"{r['label']}: answered No")
        elif answer == "will_have":
            worth_checking.append(f"{r['label']}: promised before sending")

    unwritten = [s for s in all_sections if not (sections.get(s.code) or {}).get("text")]
    if unwritten:
        fix_first.append(f"{_plural(len(unwritten), 'part', 'parts')} not written yet")
    gaps = 0
    for s in all_sections:
        part = sections.get(s.code) or {}
        score = part.get("score")
        gaps += len(_GAP.findall(part.get("text") or ""))
        if score is None:
            continue
        if s.code in rubric.MUST_SCORE_2 and score < 2:
            fix_first.append(f"{s.label}: needs a full score")
        elif rubric.is_core(s.code) and score == 0:
            fix_first.append(f"{s.label}: not usable yet")
        elif score == 1:
            worth_checking.append(f"{s.label}: one thing missing")
    if gaps:
        worth_checking.append(f"{_plural(gaps, 'gap', 'gaps')} still to fill")

    facts_open = sum(1 for f in facts if f.get("status") == "proposed" and f.get("used_in"))
    if facts_open:
        fix_first.append(f"{_plural(facts_open, 'fact', 'facts')} used and not confirmed")
    if conflicts:
        fix_first.append(f"{_plural(len(conflicts), 'disagreement', 'disagreements')} to settle")
    questions_open = sum(1 for q in questions if q.get("status") in ("open", "parked"))
    parked = sum(1 for q in questions if q.get("status") == "parked")
    if parked:
        worth_checking.append(f"{_plural(parked, 'question', 'questions')} saved for later")

    def scored(codes: list[str]) -> tuple[int, int]:
        return sum((sections.get(c) or {}).get("score") or 0 for c in codes), 2 * len(codes)

    core, core_max = scored([s.code for s in all_sections if rubric.is_core(s.code)])
    funder, funder_max = scored([s.code for s in all_sections if s.code.startswith("F")])
    return {
        "stage": work.get("stage", 1),
        "gates_answered": sum(1 for r in requirements if gates.get(r["key"]) in ANSWERS),
        "gates_total": len(requirements),
        "done": sum(1 for s in all_sections if (sections.get(s.code) or {}).get("done")),
        "total": len(all_sections),
        "core": core, "core_max": core_max, "funder": funder, "funder_max": funder_max,
        "facts_open": facts_open,
        "questions_open": questions_open,
        "fix_first": fix_first,
        "worth_checking": worth_checking,
        "ready": not fix_first,
        "to_continue": steps.exit_check(work.get("stage", 1), work),
    }
