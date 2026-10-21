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

from app.proposals import facts as fact_rules
from app.proposals import questions as question_rules
from app.proposals import readiness, reliability, review, rubric, trace

STAGES = (1, 2, 3, 4)  # 4 is "Before you send it"
FACT_STATUS = ("proposed", "confirmed", "corrected", "rejected")
LOG_TEXT = 200  # a logged value longer than this is cut; the section itself keeps it all
TEXT_LIMIT = 12000

_SECTION = re.compile(r"^sections\.([A-Z]\d{1,2})\.(text|done|score|needs_rewrite|missing|untraced)$")
_FACT = re.compile(r"^facts\.(k\d+)\.(status|correct|used_in)$")
_NEW_FACT = re.compile(r"^facts\.(k\d+)$")
_QUESTION = re.compile(r"^questions\.(q\d+)(\.status)?$")
SET_BY_PERSON = ("proposed", "confirmed", "rejected")  # "corrected" comes only with the fact that replaces it
_GATE = re.compile(r"^gates\.([a-z0-9]{1,16})$")
_READER = re.compile(r"^readers\.(funder|public|\d+)$")
READER_STATUS = ("running", "done", "failed")


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


def _check(work: dict[str, Any], path: str, value: Any, advance: bool, via: str) -> None:
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
        if value and "outline" in value:
            raise BadChange("the funder's form is read by Sangam when it fills it in")
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
        if m.group(2) == "score" and (via != "agent" or value not in (0, 1, 2, None)):
            raise BadChange("a section is scored by Sangam Pitch, 0 to 2")
        if m.group(2) == "needs_rewrite" and (via != "agent" or not isinstance(value, bool)):
            raise BadChange("a part is marked for rewriting when a fact it cites changes")
        if m.group(2) == "text" and not (isinstance(value, str) and len(value) <= TEXT_LIMIT):
            raise BadChange(f"text is up to {TEXT_LIMIT:,} characters")
        if m.group(2) in ("missing", "untraced"):
            raise BadChange("what a part misses and what it cannot trace are worked out by code")
    elif m := _FACT.match(path):
        fact = (work.get("facts") or {}).get(m.group(1))
        if fact is None:
            raise BadChange(f"no fact {m.group(1)!r}")
        if m.group(2) == "used_in" and (via != "agent" or not isinstance(value, list)):
            raise BadChange("where a fact is used is set by Sangam Pitch")
        if m.group(2) == "status" and value not in SET_BY_PERSON:
            raise BadChange(f"a fact's status is set to one of {', '.join(SET_BY_PERSON)}")
        if m.group(2) == "correct":
            if not fact_rules.is_live(fact):
                raise BadChange("that fact was already replaced or set aside")
            if not isinstance(value, str) or not value.strip() or len(value) > fact_rules.VALUE_TEXT:
                raise BadChange(f"a corrected value is 1 to {fact_rules.VALUE_TEXT} characters")
    elif m := _NEW_FACT.match(path):
        if via != "agent":
            raise BadChange("facts are added by Sangam Pitch, which checks their source first")
        if m.group(1) in (work.get("facts") or {}):
            raise BadChange(f"fact {m.group(1)} exists")
        if not (isinstance(value, dict) and value.get("status") in FACT_STATUS
                and value.get("origin") in reliability.ORIGINS and value.get("subject") and value.get("value")):
            raise BadChange("a fact has a subject, a value, an origin and a status")
    elif m := _QUESTION.match(path):
        if via != "agent":
            raise BadChange("questions are asked and answered in the chat")
        if m.group(2):
            if m.group(1) not in (work.get("questions") or {}) or value not in question_rules.STATUSES:
                raise BadChange(f"a question's status is one of {', '.join(question_rules.STATUSES)}")
        elif not (isinstance(value, dict) and value.get("reason") in question_rules.REASONS
                  and value.get("status") in question_rules.STATUSES):
            raise BadChange("a question has a reason and a status")
    elif _READER.match(path):
        if via != "agent":
            raise BadChange("files are read by Sangam Pitch")
        if not (isinstance(value, dict) and value.get("status") in READER_STATUS and value.get("at")):
            raise BadChange("a reader has a status and a time")
    elif path == "polished":
        if via != "polish" or not (isinstance(value, dict) and isinstance(value.get("parts"), dict)):
            raise BadChange("the smoothed wording is saved only once code has checked it")
    elif path == "template.outline":
        if via != "version" or not (isinstance(value, dict) and isinstance(value.get("headings"), list)):
            raise BadChange("the funder's form is read by Sangam when it fills it in")
    elif path == "versions":
        held = work.get("versions") or []
        if via != "version" or not isinstance(value, list):
            raise BadChange("a version is saved with its Word file")
        # Two people saving at once would both claim the same number, and the same file.
        if value[:-1] != held or len(value) != len(held) + 1 or value[-1].get("n") != len(value):
            raise BadChange("someone saved a copy at the same moment; try again")
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
    if isinstance(value, dict):  # a whole fact, question or reader is logged by what it says
        said = value.get("value") or value.get("status")
        return _short(f"{value.get('subject') or value.get('title')}" + (f": {said}" if said else ""))
    if isinstance(value, list) and value and isinstance(value[-1], dict):  # the versions, by the one just added
        return _short(value[-1])
    return value if not isinstance(value, str) or len(value) <= LOG_TEXT else f"{value[:LOG_TEXT]}…"


def _expand(work: dict[str, Any], changes: dict[str, Any], by: dict[str, Any]) -> dict[str, Any]:
    """A correction becomes two changes: the person's value as a new fact, and the old one marked corrected."""
    out: dict[str, Any] = {}
    held = dict(work.get("facts") or {})
    for path, value in changes.items():
        if (m := _FACT.match(path)) and m.group(2) == "correct":
            old, new = m.group(1), fact_rules.next_id({"facts": held})
            held[new] = fact_rules.said(held[old], value.strip(), by, supersedes=old)
            out[f"facts.{old}.status"] = "corrected"
            out[f"facts.{new}"] = held[new]
        else:
            out[path] = value
    return out


def used_in(work: dict[str, Any], code: str, ids: list[str]) -> dict[str, Any]:
    """Each fact's used_in, with this section added where it is cited and dropped where it no longer is."""
    out = {}
    for k, f in (work.get("facts") or {}).items():
        was = list(f.get("used_in") or [])
        now = sorted({*(c for c in was if c != code), *([code] if k in ids else [])})
        if now != sorted(was):
            out[f"facts.{k}.used_in"] = now
    return out


def _after_typing(work: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """What a person's own edit to a part carries: where facts are used, Done and a rewrite flag cleared,
    and the grade dropped, since it graded other text."""
    out: dict[str, Any] = {}
    for path, text in changes.items():
        if not ((m := _SECTION.match(path)) and m.group(2) == "text"):
            continue
        code, part = m.group(1), (work.get("sections") or {}).get(m.group(1)) or {}
        out.update(used_in(work, code, trace.cited(text)))
        if part.get("done") and f"sections.{code}.done" not in changes:
            out[f"sections.{code}.done"] = False
        if text != part.get("text"):
            if part.get("needs_rewrite"):
                out[f"sections.{code}.needs_rewrite"] = False
            if part.get("score") is not None or part.get("missing") is not None:
                out.update({f"sections.{code}.score": None, f"sections.{code}.missing": None})
    return out


def last_change(work: dict[str, Any], code: str) -> dict[str, Any] | None:
    """Who last changed a section, for "Ravi changed this a minute ago"."""
    prefix = f"sections.{code}."
    return next(({"by": e["by"], "at": e["at"]} for e in reversed(work.get("log") or [])
                 if e["path"].startswith(prefix)), None)


def apply(work: dict[str, Any], changes: dict[str, Any], rev: dict[str, int] | None = None, *,
          by: dict[str, Any], via: str = "rest", run_id: str | None = None, reason: str | None = None,
          facts: list[str] | None = None, title: str | None = None, advance: bool = False,
          now: datetime | None = None, districts: set[str] = frozenset(), names: set[str] = frozenset(),
          graded: dict[str, list[str] | None] | None = None) -> Applied:
    """Check every change first, then make them all and log each; nothing is half-applied.

    `graded` is the grader's missing elements per section, trusted because code ran it, not the person."""
    if not changes:
        raise BadChange("nothing to change")
    rev = rev or {}
    for path, value in changes.items():
        _check(work, path, value, advance, via)
    changes = _expand(work, changes, by)

    touched = sorted({m.group(1) for p in changes if (m := _SECTION.match(p))})
    for code in touched:
        current = (work.get("sections") or {}).get(code) or {}
        if code not in rev:
            raise BadChange(f"a change to section {code} carries its rev")
        if rev[code] != current.get("rev", 0):
            raise StaleSection(code, current, last_change(work, code))
    if via == "rest":
        changes = {**changes, **_after_typing(work, changes)}
    for code, missing in (graded or {}).items():
        changes = {**changes, f"sections.{code}.score": None if missing is None else rubric.score(missing),
                   f"sections.{code}.missing": missing}
    # What a correction carries into the text is code's, not the person's: no rev of theirs to check.
    changes = {**changes, **review.follow(work, changes, districts)}
    touched = sorted({m.group(1) for p in changes if (m := _SECTION.match(p))})

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
        part = out["sections"][code]
        part["rev"] = part.get("rev", 0) + 1
        if f"sections.{code}.text" in changes:  # derived, like rev, so not logged
            untraced = trace.unsourced(part["text"], out.get("facts") or {}, districts=districts, names=names)
            if untraced != (part.get("untraced") or []):
                part["untraced"] = untraced
    return Applied(out, readiness.summary(out), new_title)
