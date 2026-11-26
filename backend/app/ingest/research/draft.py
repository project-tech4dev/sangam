"""A researcher's findings as it records them, kept per run and out of its messages so a summary cannot lose them."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ingest.brief import fact_key
from app.ingest.research import source_guards
from app.ingest.research.finding_types import FINDING_MODELS, YEARLY
from app.ingest.research.findings import Gap, Unplaced

# Problems named per refused item, so one bad finding never buries the rest.
LINES_PER_ITEM = 4
LABELS = ("partner_name", "program_name", "project_name", "title", "name", "id_type", "state", "fiscal_year")


@dataclass
class Draft:
    findings: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    unplaced: list[dict[str, Any]] = field(default_factory=list)
    # Saves refused for what they contain, not their shape; two move the run to the strong model.
    refusals: int = 0
    # What the last successful save wrote, for the summary the parent reads, and the goals it was judged against.
    saved: dict[str, Any] | None = None
    goals: list[str] = field(default_factory=list)
    # The row that save wrote, merged with today's earlier one: what the judge reads.
    record: dict[str, Any] | None = None
    # The saved research this run tops up, from research_goals: only its pages answer ALREADY READ.
    slug: str | None = None


# One per launched researcher; ChosenSources opens it beside snapshots.collecting().
CURRENT: ContextVar[Draft | None] = ContextVar("import_research_draft", default=None)


@contextmanager
def drafting() -> Iterator[Draft]:
    draft = Draft()
    token = CURRENT.set(draft)
    try:
        yield draft
    finally:
        CURRENT.reset(token)


# "source_url":"https":"//x" is never meant as a key and a value: a quote was dropped mid-URL.
_SPLIT_URL = re.compile(r'"(https?)"\s*:\s*"//')


def parse_json(text: str) -> Any:
    """JSON a model sent as a string. Only surplus closers and a URL split at its colon are forgiven; None otherwise."""
    text = _SPLIT_URL.sub(r'"\1://', text.strip())
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    return None if text[end:].strip(" \t\r\n}]") else value


def as_list(value: Any) -> list[Any] | str:
    """The items a model sent: a list, one object, or either as a JSON string; an error message otherwise."""
    if value is None:
        return []
    if isinstance(value, str):
        value = parse_json(value)
        if value is None:
            return "not valid JSON; send a list of objects, not a string"
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else f"expected a list of objects, got {type(value).__name__}"


def _clean(item: dict[str, Any], model: type[BaseModel]) -> tuple[dict[str, Any], list[str]]:
    """Unknown keys are dropped and named, never refused: an empty `goals_note` once cost a run $1.32."""
    dropped = [k for k in item if k not in model.model_fields]
    return {k: v for k, v in item.items() if k in model.model_fields}, dropped


def label(item: dict[str, Any]) -> str:
    label = next((str(item[k])[:60] for k in LABELS if item.get(k)), "")
    return f"{item.get('concept', '?')}{f' {label!r}' if label else ''}"


def _errors(exc: ValidationError) -> str:
    lines = []
    for e in exc.errors()[:LINES_PER_ITEM]:
        where = ".".join(str(p) for p in e["loc"])
        lines.append(f"{where + ': ' if where else ''}{e['msg'].removeprefix('Value error, ')}")
    return "; ".join(lines)


def _put(items: list[dict[str, Any]], item: dict[str, Any], key: Any) -> None:
    """Replace the item with the same key, or add it."""
    for i, old in enumerate(items):
        if key(old) == key(item):
            items[i] = item
            return
    items.append(item)


# One page can hold two of these under one key (a mailbox and a helpline), so the quote tells them apart.
_BY_QUOTE = frozenset({"contact"})
# What a finding says beyond its key; two that differ here under one key may be two facts, not a correction.
_META = frozenset({"evidence", "source_url", "confidence", "page", "basis", "notes"})


def _finding_key(f: dict[str, Any]) -> tuple:
    """A fact sent again from its page replaces the earlier copy, so a corrected figure or a reworded quote is one."""
    quote = f.get("evidence") if f.get("concept") in _BY_QUOTE else None
    return fact_key(f), f.get("source_url"), quote


def _replaces(items: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    """Whether item overwrites a copy that said something else, which the reply names."""
    old = next((f for f in items if _finding_key(f) == _finding_key(item)), None)
    return old is not None and {k: v for k, v in old.items() if k not in _META} != {
        k: v for k, v in item.items() if k not in _META}


def _guarded(f: dict[str, Any], entity_kind: str | None) -> bool:
    model = FINDING_MODELS.get(f.get("concept"))
    return bool(model and source_guards.problems(f["concept"], f, frozenset(model.model_fields), entity_kind,
                                                 at="save"))


def drop_refused(draft: Draft, exc: ValidationError, findings: list[dict[str, Any]],
                 entity_kind: str | None) -> list[str]:
    """Takes the findings a whole save refused out of the run, so recording them again, fixed, is not a second copy:
    those its errors point at, and those the source guards refuse, which the save names but cannot point at."""
    bad = {_finding_key(findings[e["loc"][1]]) for e in exc.errors()
           if len(e["loc"]) >= 2 and e["loc"][0] == "findings" and isinstance(e["loc"][1], int)
           and e["loc"][1] < len(findings)}
    bad |= {_finding_key(f) for f in draft.findings if _guarded(f, entity_kind)}
    gone = [label(f) for f in draft.findings if _finding_key(f) in bad]
    draft.findings[:] = [f for f in draft.findings if _finding_key(f) not in bad]
    return gone


def _gap_key(g: dict[str, Any]) -> tuple:
    return g.get("concept"), g.get("fiscal_year"), g.get("field")


def _unplaced_key(u: dict[str, Any]) -> tuple:
    return u.get("field"), u.get("value")


def _one(kind: str, i: int, item: Any) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """An item validated alone: (its stored form, the keys dropped, why it was refused)."""
    if not isinstance(item, dict):
        return None, [], f"{kind}[{i}]: not an object"
    if kind == "findings":
        model = FINDING_MODELS.get(item.get("concept"))
        if model is None:
            return None, [], f"findings[{i}]: unknown concept {item.get('concept')!r}; allowed: {list(FINDING_MODELS)}"
        name = label(item)
    else:
        model, name = (Gap if kind == "gaps" else Unplaced), str(item.get("concept") or item.get("field") or "?")
    clean, dropped = _clean(item, model)
    try:
        stored = model.model_validate(clean).model_dump(mode="json")
    except ValidationError as exc:
        return None, dropped, f"{kind}[{i}] ({name}): {_errors(exc)}"
    return stored, [f"{kind}[{i}] `{k}`" for k in dropped], None


def record(draft: Draft, findings: Any, gaps: Any, unplaced: Any) -> str:
    """Adds each valid item to the draft and names only the refused ones, so only those are sent again."""
    accepted = {"findings": 0, "gaps": 0, "unplaced": 0}
    refused: list[str] = []
    dropped: list[str] = []
    replaced: list[str] = []
    targets = {"findings": (draft.findings, _finding_key), "gaps": (draft.gaps, _gap_key),
               "unplaced": (draft.unplaced, _unplaced_key)}
    for kind, value in (("findings", findings), ("gaps", gaps), ("unplaced", unplaced)):
        items = as_list(value)
        if isinstance(items, str):
            refused.append(f"{kind}: {items}")
            continue
        for i, item in enumerate(items):
            stored, gone, why = _one(kind, i, item)
            dropped += gone
            if why:
                refused.append(why)
                continue
            target, key = targets[kind]
            if kind == "findings" and _replaces(target, stored):
                replaced.append(label(stored))
            _put(target, stored, key)
            accepted[kind] += 1
    out = [(f"Recorded {accepted['findings']} findings, {accepted['gaps']} gaps, {accepted['unplaced']} unplaced. "
            f"This run holds {len(draft.findings)} findings, {len(draft.gaps)} gaps, {len(draft.unplaced)} unplaced; "
            "nothing recorded needs sending again.")]
    if replaced:
        out.append(f"Replaced an earlier finding from the same page with other values: {', '.join(replaced)}. Fine "
                   "for a correction; if they are two facts, send both again, each with the name, programme, project, "
                   "place or year that tells them apart.")
    if dropped:
        out.append(f"Dropped keys that are not fields (the rest of each item was kept): {', '.join(dropped)}.")
    if refused:
        out.append(f"Refused {len(refused)}; send only these again, fixed:\n" + "\n".join(f"- {r}" for r in refused))
    return "\n".join(out)


def _filled(v: Any) -> bool:
    return v not in (None, "", [], {})


def answered(gap: dict[str, Any], findings: list[dict[str, Any]]) -> bool:
    """A gap a finding now fills; one covering every year of a yearly concept is never closed by a single year,
    and a field gap only once every such finding has the field (one untagged programme keeps its themes gap)."""
    concept, year, name = gap.get("concept"), gap.get("fiscal_year"), gap.get("field")
    if concept in YEARLY and not year and not name:
        return False
    same = [f for f in findings if f.get("concept") == concept and (not year or f.get("fiscal_year") == year)]
    return bool(same) and all(_filled(f.get(name)) for f in same) if name else bool(same)


def merged_gaps(prior: list[dict[str, Any]], mine: list[dict[str, Any]],
                findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """This run's gaps over the day's earlier ones, less any a finding now answers."""
    out = list(prior)
    for g in mine:
        _put(out, g, _gap_key)
    return [g for g in out if not answered(g, findings)]


REFUSAL_LINES = 25


def problems(exc: ValidationError, findings: list[dict[str, Any]]) -> list[str]:
    """A whole save's schema problems, each naming the finding it is about rather than an index."""
    out = []
    for e in exc.errors()[:REFUSAL_LINES]:
        loc, msg = e["loc"], e["msg"].removeprefix("Value error, ")
        if len(loc) >= 2 and loc[0] == "findings" and isinstance(loc[1], int) and loc[1] < len(findings):
            where = f"finding ({label(findings[loc[1]])}) {'.'.join(str(p) for p in loc[3:])}".rstrip()
        else:
            where = ".".join(str(p) for p in loc) or "save"
        out.append(f"{where}: {msg}")
    return out
