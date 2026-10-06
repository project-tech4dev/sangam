"""The criteria file's schema, and every reason the loader refuses one."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.matching.evaluators import ENGINE_API, REGISTRY

DEFAULT_PATH = Path(__file__).parent / "criteria" / "funder_matching.yaml"
SELECTORS = {"funder_type", "always"}
RANKING_KEYS = {"gate_status", "score_min", "score_max", "coverage", "shared_districts", "funder_id"}


class CriteriaError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class CheckDef(_Strict):
    code: str
    label: str
    evaluator: str
    params: dict[str, Any] = Field(default_factory=dict)


class GroupDef(_Strict):
    all_: list[str] | None = Field(None, alias="all")
    any_: list[str] | None = Field(None, alias="any")
    min_met: int | None = None
    of: list[str] | None = None

    @property
    def members(self) -> list[str]:
        return self.all_ or self.any_ or self.of or []


class Roles(_Strict):
    gate: list[str] = Field(default_factory=list)
    advisory: list[str] = Field(default_factory=list)


class Category(_Strict):
    weight: int
    checks: dict[str, int]


class Criteria(_Strict):
    set_: str = Field(alias="set")
    version: int
    engine: int
    checks: list[CheckDef]
    groups: dict[str, GroupDef] = Field(default_factory=dict)
    roles: Roles = Roles()
    applies: dict[str, dict[str, Any]] = Field(default_factory=dict)
    weights: dict[str, Category] = Field(default_factory=dict)
    partial: dict[str, dict[str, float]] = Field(default_factory=dict)
    ranking: list[str]

    @model_validator(mode="after")
    def _consistent(self) -> Criteria:
        problems = _problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def check(self, code: str) -> CheckDef:
        return next(c for c in self.checks if c.code == code)

    def category_of(self, code: str) -> tuple[str, int] | None:
        for name, cat in self.weights.items():
            if code in cat.checks:
                return name, cat.checks[code]
        return None


def _problems(c: Criteria) -> list[str]:
    out: list[str] = []
    if c.engine != ENGINE_API:
        out.append(f"engine {c.engine} does not match the code's evaluator API {ENGINE_API}")
    codes: list[str] = [x.code for x in c.checks] + list(c.groups)
    for dup in sorted({x for x in codes if codes.count(x) > 1}):
        out.append(f"code '{dup}' defined twice")
    known = set(codes)
    for chk in c.checks:
        spec = REGISTRY.get(chk.evaluator)
        if spec is None:
            out.append(f"check '{chk.code}': unknown evaluator '{chk.evaluator}'")
            continue
        try:
            spec.params(**chk.params)
        except ValidationError as exc:
            out.append(f"check '{chk.code}': bad params: {exc.errors()[0]['msg']}")
    for name, g in c.groups.items():
        forms = [g.all_ is not None, g.any_ is not None, g.of is not None]
        if sum(forms) != 1 or (g.of is not None) != (g.min_met is not None):
            out.append(f"group '{name}': use exactly one of all / any / min_met+of")
        for m in g.members:
            if m not in known:
                out.append(f"group '{name}' names undefined member '{m}'")
    out += _cycles(c)
    for role, members in (("gate", c.roles.gate), ("advisory", c.roles.advisory)):
        out += [f"role {role} names undefined '{m}'" for m in members if m not in known]
    for target, sel in c.applies.items():
        if target not in known:
            out.append(f"applies names undefined '{target}'")
        bad = set(sel) - SELECTORS
        if bad or len(sel) != 1:
            out.append(f"applies '{target}': unknown selector {sorted(bad) or sorted(sel)}")
    total = 0
    weighted: list[str] = []
    for name, cat in c.weights.items():
        total += cat.weight
        if sum(cat.checks.values()) != cat.weight:
            out.append(f"category '{name}' weight {cat.weight} != sum of its checks {sum(cat.checks.values())}")
        for code in cat.checks:
            weighted.append(code)
            if code not in {x.code for x in c.checks}:
                out.append(f"weight on undefined check '{code}'")
    if c.weights and total != 100:
        out.append(f"weights must total 100, got {total}")
    for dup in sorted({x for x in weighted if weighted.count(x) > 1}):
        out.append(f"check '{dup}' weighted in two categories")
    for code, levels in c.partial.items():
        chk = next((x for x in c.checks if x.code == code), None)
        emitted = REGISTRY[chk.evaluator].levels if chk and chk.evaluator in REGISTRY else ()
        for lvl, share in levels.items():
            if lvl not in emitted:
                out.append(f"partial '{code}': level '{lvl}' is not one its evaluator emits")
            if not 0 <= share <= 1:
                out.append(f"partial '{code}.{lvl}' must be between 0 and 1")
    for key in c.ranking:
        if key not in RANKING_KEYS:
            out.append(f"unknown ranking key '{key}'")
    if not c.ranking or c.ranking[-1] != "funder_id":
        out.append("ranking must end in funder_id so ties are deterministic")
    return out


def _cycles(c: Criteria) -> list[str]:
    def visit(name: str, path: tuple[str, ...]) -> str | None:
        if name in path:
            return " -> ".join((*path, name))
        for m in c.groups[name].members if name in c.groups else ():
            found = visit(m, (*path, name))
            if found:
                return found
        return None
    for name in c.groups:
        found = visit(name, ())
        if found:
            return [f"group cycle: {found}"]
    return []


def parse_criteria(raw: dict) -> Criteria:
    try:
        return Criteria.model_validate(raw)
    except ValidationError as exc:
        raise CriteriaError("; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())) from exc


def content_hash(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_yaml(path: Path | str = DEFAULT_PATH) -> tuple[Criteria, dict]:
    raw = yaml.safe_load(Path(path).read_text())
    return parse_criteria(raw), raw
