"""The one way `proposals.work` changes. Pure: the repository locks the row, calls `apply`, and writes the result.

Every REST save and every agent write goes through `apply`, so each change is checked against the allowed
paths, a section's `rev`, and is logged with who made it and how.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.proposals import readiness, rubric

STAGES = (1, 2, 3, 4)  # 4 is "Before you send it"
FACT_STATUS = ("proposed", "confirmed", "corrected", "rejected")
LOG_TEXT = 200  # a logged value longer than this is cut; the section itself keeps it all

_SECTION = re.compile(r"^sections\.([A-Z]\d{1,2})\.(text|done)$")
_FACT = re.compile(r"^facts\.(k\d+)\.(status|value)$")
_GATE = re.compile(r"^gates\.([a-z0-9]{1,16})$")


class BadChange(ValueError):
    """A path or value the caller may not set: a 400."""


@dataclass
class StaleSection(Exception):
    """A section changed since the caller read it: a 409 with what is there now."""

    code: str
    current: dict[str, Any]
    changed_by: dict[str, Any] | None


@dataclass
class Applied:
    work: dict[str, Any]
    summary: dict[str, Any]
    title: str | None


def _check(work: dict[str, Any], path: str, value: Any, advance: bool) -> None:
    if path == "title":
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise BadChange("title must be 1 to 200 characters")
    elif m := _GATE.match(path):
        if m.group(1) not in {r["key"] for r in work.get("requirements") or []}:
            raise BadChange(f"no requirement {m.group(1)!r}")
        if value not in (*readiness.ANSWERS, None):
            raise BadChange("an answer is yes, will_have, no or null")
    elif path == "stage":
        current = work.get("stage", 1)
        if value not in STAGES or (value != current + 1 if advance else value > current):
            raise BadChange("a step is moved forward by POST /advance; PATCH only goes back")
    elif path == "template":
        if value is not None and not (isinstance(value, dict) and isinstance(value.get("document_id"), int)):
            raise BadChange("template is null or an object with a document_id")
    elif path == "skipped_template":
        if not isinstance(value, bool):
            raise BadChange("skipped_template is true or false")
    elif path == "sources":
        if not (isinstance(value, list) and all(isinstance(v, int) for v in value)):
            raise BadChange("sources is a list of document ids")
    elif path == "style":
        if not isinstance(value, str) or len(value) > 4000:
            raise BadChange("style is text of up to 4,000 characters")
    elif m := _SECTION.match(path):
        codes = {s.code for s in rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))}
        if m.group(1) not in codes:
            raise BadChange(f"no section {m.group(1)!r} in this proposal")
        if m.group(2) == "done" and not isinstance(value, bool):
            raise BadChange("done is true or false")
        if m.group(2) == "text" and not isinstance(value, str):
            raise BadChange("text is a string")
    elif m := _FACT.match(path):
        if m.group(1) not in (work.get("facts") or {}):
            raise BadChange(f"no fact {m.group(1)!r}")
        if m.group(2) == "status" and value not in FACT_STATUS:
            raise BadChange(f"a fact's status is one of {', '.join(FACT_STATUS)}")
    else:
        raise BadChange(f"{path!r} cannot be changed")


def _get(work: dict[str, Any], path: str) -> Any:
    node: Any = work
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _set(work: dict[str, Any], path: str, value: Any) -> None:
    *parents, last = path.split(".")
    node = work
    for key in parents:
        node = node.setdefault(key, {})
    node[last] = value


def _short(value: Any) -> Any:
    return value if not isinstance(value, str) or len(value) <= LOG_TEXT else f"{value[:LOG_TEXT]}…"


def last_change(work: dict[str, Any], code: str) -> dict[str, Any] | None:
    """Who last changed a section, for "Ravi changed this a minute ago"."""
    prefix = f"sections.{code}."
    return next(({"by": e["by"], "at": e["at"]} for e in reversed(work.get("log") or [])
                 if e["path"].startswith(prefix)), None)


def apply(work: dict[str, Any], changes: dict[str, Any], rev: dict[str, int] | None = None, *,
          by: dict[str, Any], via: str = "rest", run_id: str | None = None, reason: str | None = None,
          facts: list[str] | None = None, title: str | None = None, advance: bool = False,
          now: datetime | None = None) -> Applied:
    """Check every change first, then make them all and log each; nothing is half-applied."""
    if not changes:
        raise BadChange("nothing to change")
    rev = rev or {}
    for path, value in changes.items():
        _check(work, path, value, advance)

    touched = sorted({m.group(1) for p in changes if (m := _SECTION.match(p))})
    for code in touched:
        current = (work.get("sections") or {}).get(code) or {}
        if code not in rev:
            raise BadChange(f"a change to section {code} carries its rev")
        if rev[code] != current.get("rev", 0):
            raise StaleSection(code, current, last_change(work, code))

    out = copy.deepcopy(work)
    at = (now or datetime.now(UTC)).isoformat()
    log = out.setdefault("log", [])
    new_title = None
    for path, value in changes.items():
        before = title if path == "title" else _get(out, path)
        if path == "title":
            new_title = value.strip()
        else:
            _set(out, path, value)
        log.append({"at": at, "by": by, "via": via, "run_id": run_id, "path": path,
                    "from": _short(before), "to": _short(new_title if path == "title" else value),
                    "facts": facts or [], "reason": reason})
    for code in touched:
        out["sections"][code]["rev"] = out["sections"][code].get("rev", 0) + 1
    return Applied(out, readiness.summary(out), new_title)
