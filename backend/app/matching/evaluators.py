"""The checks. Pure functions over evidence: no pool, no async, no settings."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.matching.evidence import FunderEvidence, OrgEvidence
from app.matching.models import Basis, Outcome

ENGINE_API = 1


@dataclass(frozen=True)
class Check:
    outcome: Outcome
    basis: Basis
    reason_code: str
    reason_params: dict = field(default_factory=dict)
    cites: tuple[str, ...] = ()
    level: str | None = None


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class EvaluatorSpec:
    name: str
    fn: Callable[[OrgEvidence, FunderEvidence | None, Any], Check]
    reads: frozenset[str]
    params: type[Params]
    levels: tuple[str, ...] = ()
    """The `partial` levels this evaluator can emit."""


REGISTRY: dict[str, EvaluatorSpec] = {}


def evaluator(name: str, *, reads: set[str], params: type[Params], levels: tuple[str, ...] = ()):
    def register(fn):
        REGISTRY[name] = EvaluatorSpec(name, fn, frozenset(reads), params, levels)
        return fn
    return register


def run(name: str, org: OrgEvidence, funder: FunderEvidence | None, params: dict) -> Check:
    spec = REGISTRY[name]
    return spec.fn(org, funder, spec.params(**params))


def _unknown(reason: str, basis: Basis = "not_researched", **params) -> Check:
    return Check("unknown", basis, reason, params)


# --- credentials ---------------------------------------------------------------------------

_ACTIVE = {"registered", "renewed", "checked_active", "restored"}
_LAPSED = {"expired", "suspended", "cancelled", "surrendered", "superseded"}
_SEARCHED = {"not_found", "not_available"}


class HasIdentifierParams(Params):
    id_type: str
    doc_type: str | None = None
    """A Vault document of this type proves the credential is on file."""


def _mentions(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text.lower().replace("-", "")) is not None


@evaluator("has_identifier", reads={"org.identifiers", "org.credential_events", "org.documents",
                                    "org.research"}, params=HasIdentifierParams)
def has_identifier(org: OrgEvidence, _f, p: HasIdentifierParams) -> Check:
    event = org.credential_events.get(p.id_type)
    if event and event.value in _LAPSED:
        return Check("fail", event.basis, event.value, {"as_of": event.as_of}, (event.cite,))
    vault = [d for d in org.documents.get(p.doc_type or "", ()) if d.vault]
    if vault:
        return Check("met", "on_file", "document_on_file", {"document_id": vault[0].id}, (org.cite,))
    ident = org.identifiers.get(p.id_type)
    if ident:
        return Check("met", ident.basis, "recorded", {"value": ident.value}, (ident.cite,))
    if event and event.value in _ACTIVE:
        return Check("met", event.basis, event.value, {"as_of": event.as_of}, (event.cite,))
    if event and event.value in _SEARCHED:
        return _unknown("searched_not_found", "searched_not_found", searched_on=event.as_of)
    for concept, on in org.not_found:
        if _mentions(concept, p.id_type):
            return _unknown("searched_not_found", "searched_not_found", searched_on=on.isoformat())
    return _unknown("not_recorded")
