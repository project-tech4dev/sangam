"""The fact list's rules: what a fact holds, when two are the same, and what each origin must show. Pure.

The registry check re-reads rows, so it lives in `records.py`; everything here needs only `work`.
"""

from __future__ import annotations

import re
from typing import Any

from app.proposals import reliability, rubric

LIVE = ("proposed", "confirmed")  # corrected and rejected facts fill no gap and reach no text
VALUE_TEXT = 500
WEB_EVIDENCE = 20
_MARKER = re.compile(r"^\[(org|activity|score):\d+\]$")
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def norm(text: Any) -> str:
    """Lower case, one space, and "24,765" read as "24765"."""
    return " ".join(_DIGIT_COMMA.sub("", str(text or "")).lower().split())


def numbers(text: Any) -> list[float]:
    return [float(n) for n in _NUMBER.findall(norm(text))]


def is_live(fact: dict[str, Any]) -> bool:
    return fact.get("status") in LIVE


def source(fact: dict[str, Any]) -> str:
    if fact.get("marker"):
        return fact["marker"]
    if fact.get("document_id") is not None:
        return f"doc{fact['document_id']}#p{fact.get('page') or ''}"
    return fact.get("source_url") or ",".join(fact.get("from") or [])


def same_as(work: dict[str, Any], fact: dict[str, Any]) -> str | None:
    """The id of a fact already holding this origin, source, subject and value: a retried turn adds nothing."""
    key = (fact.get("origin"), source(fact), norm(fact.get("subject")), norm(fact.get("value")))
    return next((k for k, f in (work.get("facts") or {}).items()
                 if (f.get("origin"), source(f), norm(f.get("subject")), norm(f.get("value"))) == key), None)


def next_id(work: dict[str, Any]) -> str:
    """Allocated inside the row lock, so two people adding facts at once never share an id."""
    taken = [int(k[1:]) for k in (work.get("facts") or {}) if k[1:].isdigit()]
    return f"k{max(taken, default=0) + 1}"


def partner_names(work: dict[str, Any], *own: str) -> set[str]:
    """Partner and people names in the fact list; the proposal's own org and funder are free to name."""
    mine = {norm(o) for o in own}
    return {norm(f.get("value")) for f in (work.get("facts") or {}).values()
            if f.get("kind") == "name" and is_live(f) and norm(f.get("value")) not in mine}


def section_of(work: dict[str, Any], code: str | None) -> rubric.Section | None:
    return next((s for s in rubric.sections_for(bool(work.get("earlier_phase")), work.get("template"))
                 if s.code == code), None)


def element_of(section: rubric.Section, element: str | None) -> str | None:
    """The section's own wording of a strong element, matched without case."""
    return next((e for e in section.strong if norm(e) == norm(element)), None)


def problem(work: dict[str, Any], fact: dict[str, Any]) -> str | None:
    """Why this fact cannot be added, or None. The registry row itself is checked in records.py."""
    subject, value, origin = fact.get("subject"), fact.get("value"), fact.get("origin")
    if not isinstance(subject, str) or not subject.strip():
        return "a fact needs a subject"
    if not isinstance(value, str) or not value.strip() or len(value) > VALUE_TEXT:
        return f"{subject}: a value is 1 to {VALUE_TEXT} characters"
    if origin not in reliability.ORIGINS:
        return f"{subject}: origin is one of {', '.join(reliability.ORIGINS)}"
    if fact.get("section"):
        section = section_of(work, fact["section"])
        if section is None:
            return f"{subject}: no section {fact['section']!r} in this proposal"
        if fact.get("element") and element_of(section, fact["element"]) is None:
            return f"{subject}: {section.label} has no element {fact['element']!r}"
    elif fact.get("element"):
        return f"{subject}: an element needs its section"
    if origin == "you_said":
        return f"{subject}: what the person says becomes a fact only through ask_user"
    if origin == "registry" and not _MARKER.match(str(fact.get("marker") or "")):
        return f"{subject}: a registry fact carries its [org:N], [activity:N] or [score:N] marker"
    if origin == "web":
        if not str(fact.get("source_url") or "").startswith(("http://", "https://")):
            return f"{subject}: a web fact needs its http link"
        if len(str(fact.get("evidence") or "").strip()) < WEB_EVIDENCE:
            return f"{subject}: a web fact quotes at least {WEB_EVIDENCE} characters of the page"
    if origin == "vault":
        from app.ingest import vault

        if fact.get("document_id") not in (work.get("sources") or []):
            return f"{subject}: document {fact.get('document_id')} is not one of the files ticked for this proposal"
        found = vault.check_findings([{"concept": subject, "source_url": fact.get("source_url"),
                                       "evidence": fact.get("evidence")}], set(work.get("sources") or []))
        if found:
            return found[0]
    if origin == "derived":
        held = work.get("facts") or {}
        sources = fact.get("from") or []
        if not sources or any(k not in held for k in sources):
            return f"{subject}: a derived fact names the facts it is worked out from"
    return None


def make(fact: dict[str, Any], *, by: dict[str, Any] | None = None) -> dict[str, Any]:
    """The stored fact: proposed and coloured by its origin; only `by` (the person who said it) is trusted."""
    keep = ("kind", "subject", "value", "marker", "as_of", "section", "element", "evidence", "source_url",
            "source_name", "page", "document_id", "from", "supersedes")
    out = {k: fact[k] for k in keep if fact.get(k) not in (None, "", [])}
    origin = fact["origin"]
    out.update(origin=origin, tier=reliability.tier(origin), status="proposed", used_in=[],
               private=origin in ("vault", "you_said"))
    if by is not None:
        out["said_by"] = by
    return out


def said(question: dict[str, Any], answer: str, by: dict[str, Any], supersedes: str | None = None) -> dict[str, Any]:
    """A person's answer, in their words: confirmed, since they said it themselves."""
    fact = make({"kind": question.get("kind"), "subject": question["subject"], "value": answer[:VALUE_TEXT],
                 "section": question.get("section"), "element": question.get("element"), "evidence": answer,
                 "origin": "you_said", "supersedes": supersedes}, by=by)
    return {**fact, "status": "confirmed"}
