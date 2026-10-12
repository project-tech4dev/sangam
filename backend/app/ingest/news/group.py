"""Group links into stories (spec section 2, step 5): an exact pass first, then the model on what is left."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from app.ingest.news.links import title_key, url_key


@dataclass(frozen=True)
class Candidate:
    key: str
    date: str
    host: str
    title: str
    summary: str
    url: str


class _Group(BaseModel):
    label: str
    keys: list[str]


class _Groups(BaseModel):
    groups: list[_Group]


@cache
def _prompt() -> str:
    return (Path(__file__).parent / "prompts" / "group.md").read_text(encoding="utf-8")


def exact_groups(cands: list[Candidate]) -> list[list[str]]:
    parent = {x.key: x.key for x in cands}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    first: dict[str, str] = {}
    for x in cands:
        for sig in (f"u:{url_key(x.url)}", f"t:{title_key(x.title)}" if title_key(x.title) else None):
            if sig is None:
                continue
            if sig in first:
                parent[find(x.key)] = find(first[sig])
            else:
                first[sig] = x.key
    out: dict[str, list[str]] = {}
    for x in cands:
        out.setdefault(find(x.key), []).append(x.key)
    return _one_story_each(list(out.values()))


def _one_story_each(groups: list[list[str]]) -> list[list[str]]:
    """A group may hold at most one stored story; any other stored story leaves as its own group."""
    out = []
    for g in groups:
        stored = [k for k in g if k.startswith("s")]
        out.append([k for k in g if not k.startswith("s")] + stored[:1])
        out += [[k] for k in stored[1:]]
    return [g for g in out if g]


def _repair(groups: list[list[str]], keys: list[str]) -> list[list[str]]:
    seen, fixed = set(), []
    for g in groups:
        kept = []
        for k in g:
            if k in keys and k not in seen:
                kept.append(k)
                seen.add(k)
        if kept:
            fixed.append(kept)
    return fixed + [[k] for k in keys if k not in seen]


async def group(model, bucket: str, cands: list[Candidate]) -> list[list[str]]:
    if len(cands) <= 1:
        return [[x.key for x in cands]] if cands else []
    lines = "\n".join(f"{x.key} | {x.date} | {x.host} | {x.title[:140]} | {x.summary[:260]}" for x in cands)
    try:
        # json_schema: forced tool calls are not supported on the research tier's model.
        reply = await model.with_structured_output(_Groups, method="json_schema").ainvoke(
            [("system", _prompt()), ("user", f"Bucket: {bucket}\n{lines}")])
        groups = [g.keys for g in reply.groups]
    except Exception:  # noqa: BLE001 - grouping is an improvement; without it the exact pass still holds
        return exact_groups(cands)
    return _one_story_each(_repair(groups, [x.key for x in cands]))
