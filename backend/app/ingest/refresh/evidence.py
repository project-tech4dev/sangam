"""Is each fact's sentence still on the page? Catches a changed fact without a model."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from typing import Any

from rapidfuzz import fuzz

from app.ingest.reading.access import canonical_url
from app.ingest.reading.fingerprint import normalise
from app.ingest.refresh.compare import CHANGED, DIFFERS, Check, counts

INTACT, BROKEN, UNANCHORED = "intact", "broken", "unanchored"
MATCH = 95  # a sentence moved or re-spaced still scores ~100
# A changed figure barely moves the fuzzy score ("400" → "500" is ~98), so numbers must match exactly.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# A changed month, status word or "not" also barely moves it, so every word must be there too.
_WORD = re.compile(r"\w+")
# extract_pdf_text's page headers, and a word split at a line end: neither is a change in what the page says.
# Every hyphen inside a word goes, on both sides alike, so "multi-year" still matches "multi-\nyear" and "2024-25".
_PAGE = re.compile(r"^--- page \d+ ---$", re.MULTILINE)
_HYPHEN = re.compile(r"(\w)- ?(\w)")

# Every row's facts are loaded, but each is checked against the newest version of its page (baseline.py), so a fact
# an older row read from a version a later row replaced goes unchecked while the page stays as the later row read it.
FINDINGS_SQL = """
    SELECT findings FROM entity_research
     WHERE slug = %s AND status <> 'wrong_entity'
"""


async def load_findings(conn: Any, slug: str) -> dict[str, list[str]]:
    """Each source URL's distinct evidence sentences, across every research row of the slug."""
    rows = await (await conn.execute(FINDINGS_SQL, (slug,))).fetchall()
    by_url: dict[str, list[str]] = {}
    for row in rows:
        for f in row["findings"] or []:
            url, evidence = f.get("source_url"), (f.get("evidence") or "").strip()
            if not url or not evidence:
                continue
            sentences = by_url.setdefault(canonical_url(url), [])
            if evidence not in sentences:
                sentences.append(evidence)
    return by_url


def on_page(sentence: str, text: str) -> bool:
    """The sentence is on the page nearly word for word, and with every number it states."""
    needle, page = _clean(sentence), _clean(text)
    hit = fuzz.partial_ratio_alignment(needle, page)
    if hit is None or hit.score < MATCH:
        return False
    # Widened to whole words, so a number the match cut in half is read whole, and nothing from the next sentence.
    start, end = hit.dest_start, hit.dest_end
    while start > 0 and not page[start - 1].isspace():
        start -= 1
    while end < len(page) and not page[end].isspace():
        end += 1
    window = page[start:end]
    words = Counter(_WORD.findall(needle.casefold())) <= Counter(_WORD.findall(window.casefold()))
    return words and Counter(_NUMBER.findall(needle)) <= Counter(_NUMBER.findall(window))


def _clean(text: str) -> str:
    return _HYPHEN.sub(r"\1\2", normalise(_PAGE.sub(" ", text)))


def verdict(sentence: str, old: str, new: str) -> str:
    if not on_page(sentence, old):
        return UNANCHORED  # paraphrased or derived: the check cannot say whether it still holds
    return INTACT if on_page(sentence, new) else BROKEN


def run(checks: list[Check], findings: dict[str, list[str]]) -> list[Check]:
    return [_check_one(c, findings.get(c.baseline.url, [])) if c.status == DIFFERS and c.old_text else c
            for c in checks]


def _check_one(check: Check, sentences: list[str]) -> Check:
    verdicts = tuple((verdict(s, check.old_text or "", check.today.text), s) for s in sentences)
    broken = sum(v == BROKEN for v, _ in verdicts)
    tally = ", ".join(f"{sum(v == k for v, _ in verdicts)} {k}" for k in (INTACT, BROKEN, UNANCHORED))
    if broken:
        return replace(check, status=CHANGED, verdicts=verdicts, reason=f"facts: {tally}")
    return replace(check, verdicts=verdicts, reason=f"{check.reason}; facts: {tally}" if verdicts else
                   f"{check.reason}; no facts cite this page")


def describe(slug: str, checks: list[Check]) -> str:
    lines = [f"{slug}: {counts(checks)}"]
    for c in checks:
        if not c.verdicts and not (c.status == DIFFERS and c.old_text):
            continue
        lines.append(f"  {c.status:10}  {c.baseline.url}  ({c.reason})")
        lines += [f"      broken: {s[:200]}" for v, s in c.verdicts if v == BROKEN]
    return "\n".join(lines)
