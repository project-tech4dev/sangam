"""What a corrected or set-aside fact does to the text that cites it. Pure; `work.apply` adds these changes.

A sentence citing a corrected fact gets the new value when the old one is in it word for word; anything else
citing it is marked for a rewrite, and facts worked out from it go back to the person to check.
"""

from __future__ import annotations

import re
from typing import Any

from app.proposals import facts as fact_rules
from app.proposals import trace

_SENTENCE = re.compile(r"(?<=[.!?])(\s+)")
_BARE_NUMBER = re.compile(r"^[₹\s]*\d[\d,]*(?:\.\d+)?\s*%?$")


def _pattern(value: str) -> re.Pattern[str]:
    """The value as written in prose: any case and spacing, "1,240" or "1240", never inside a longer number."""
    body = re.escape(value.strip()).replace(r"\ ", r"\s+")
    body = re.sub(r"(?<=\d),?(?=\d)", ",?", body)
    return re.compile(rf"(?<![\w.,]){body}(?!\w)", re.IGNORECASE)


def _wording(old: str, new: str) -> str:
    """"96" for "120 villages" reads "96 villages": a bare number replaces only the old value's number."""
    found = fact_rules.numbers(old)
    if _BARE_NUMBER.match(new) and len(found) == 1:
        return re.sub(r"\d[\d,]*(?:\.\d+)?", new.strip().lstrip("₹").strip(), old, count=1)
    return new


def _rewrite(text: str, old_id: str, new_id: str, old: str, new: str) -> tuple[str, bool]:
    """The text with each sentence citing old_id fixed in place; False when one could not be."""
    mark, pattern, wording = f"⟦{old_id}⟧", _pattern(old), _wording(old, new)
    pieces = _SENTENCE.split(text)
    whole = True
    for i in range(0, len(pieces), 2):
        sentence = pieces[i]
        if mark not in sentence:
            continue
        if pattern.search(sentence):
            pieces[i] = pattern.sub(lambda _m: wording, sentence).replace(mark, f"⟦{new_id}⟧")
        else:
            whole = False
    return "".join(pieces), whole


def _traces(before: str, after: str, held: dict[str, Any], now: dict[str, Any], districts: set[str]) -> bool:
    """The fix adds no untraced claim: "Baksa" stays only if a fact still cited names it."""
    was = set(trace.check(before, held, districts=districts))
    return not set(trace.check(after, now, districts=districts)) - was


def follow(work: dict[str, Any], changes: dict[str, Any], districts: set[str] = frozenset()) -> dict[str, Any]:
    """The changes a correction or a "Don't use it" carries into the text and the derived facts."""
    held = {**(work.get("facts") or {}),
            **{p.split(".")[1]: v for p, v in changes.items() if re.fullmatch(r"facts\.k\d+", p)}}
    replaced = {f["supersedes"]: p.split(".")[1] for p, f in changes.items()
                if re.fullmatch(r"facts\.k\d+", p) and f.get("supersedes")}
    gone = [p.split(".")[1] for p, v in changes.items()
            if p.endswith(".status") and p.startswith("facts.") and v in ("corrected", "rejected")]
    if not gone:
        return {}

    after = {k: ({**f, "status": changes[f"facts.{k}.status"]} if f"facts.{k}.status" in changes else f)
             for k, f in held.items()}
    out: dict[str, Any] = {}
    texts = {c: s.get("text") or "" for c, s in (work.get("sections") or {}).items()}
    used = {k: list(f.get("used_in") or []) for k, f in held.items()}
    for k in gone:
        new = replaced.get(k)
        for code, text in texts.items():
            if f"⟦{k}⟧" not in text:
                continue
            whole = False
            if new:
                fixed, whole = _rewrite(text, k, new, str(held[k].get("value")), str(held[new].get("value")))
                if not _traces(text, fixed, held, after, districts):
                    fixed, whole = text, False
                text = fixed
                if text != texts[code]:
                    texts[code] = out[f"sections.{code}.text"] = text
                    used[new] = sorted({*used.get(new, []), code})
            if whole:
                used[k] = [c for c in used.get(k, []) if c != code]
            else:
                out[f"sections.{code}.needs_rewrite"] = True
        for d, f in held.items():
            if k in (f.get("from") or []) and f.get("status") == "confirmed":
                out[f"facts.{d}.status"] = "proposed"
    for k, now in used.items():
        if k in held and now != list(held[k].get("used_in") or []):
            out[f"facts.{k}.used_in"] = now
    return out
