"""The checks. Pure functions over evidence: no pool, no async, no settings."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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
_LAPSED = {"expired", "suspended", "cancelled", "surrendered"}
"""`superseded` is not here: a 12A re-registered as 12AB is superseded, not lapsed."""
_SEARCHED = {"not_found", "not_available"}


def _today():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


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
    vault = [d for d in org.documents.get(p.doc_type or "", ()) if d.vault]
    ident = org.identifiers.get(p.id_type)
    if event and event.value in _LAPSED:
        if vault or ident:  # two sources disagree; neither is positive evidence of a fail
            return _unknown("conflicting_evidence", "recorded", event=event.value, as_of=event.as_of)
        return Check("fail", event.basis, event.value, {"as_of": event.as_of}, (event.cite,))
    if vault:
        return Check("met", "on_file", "document_on_file", {"document_id": vault[0].id}, (org.cite,))
    if ident:
        return Check("met", ident.basis, "recorded", {"value": ident.value}, (ident.cite,))
    if event and event.value == "superseded":
        return _unknown("superseded", "recorded", as_of=event.as_of)
    if event and event.value in _ACTIVE and event.valid_until and event.valid_until < _today():
        return _unknown("validity_ended", "recorded", valid_until=event.valid_until.isoformat())
    if event and event.value in _ACTIVE:
        return Check("met", event.basis, event.value, {"as_of": event.as_of}, (event.cite,))
    if event and event.value in _SEARCHED:
        return _unknown("searched_not_found", "searched_not_found", searched_on=event.as_of)
    for concept, on in org.not_found:
        if _mentions(concept, p.id_type):
            return _unknown("searched_not_found", "searched_not_found", searched_on=on.isoformat())
    return _unknown("not_recorded")


# --- fit: place, theme, programme ------------------------------------------------------------

class SharesPlaceParams(Params):
    levels: tuple[str, ...] = ("district", "state", "pan_india_stated")


@evaluator("shares_place", reads={"org.places", "pair.fit"}, params=SharesPlaceParams,
           levels=("district", "state", "pan_india_stated"))
def shares_place(org: OrgEvidence, f: FunderEvidence | None, p: SharesPlaceParams) -> Check:
    if not (org.districts or org.states):
        return _unknown("org_places_not_recorded")
    fit = f.fit
    cites = (org.cite, f.cite)
    if "district" in p.levels and fit.shared_districts:
        return Check("met", "recorded", "shared_district", {"places": list(fit.shared_districts)}, cites, "district")
    if "state" in p.levels and fit.shared_states:
        return Check("met", "recorded", "shared_state", {"places": list(fit.shared_states)}, cites, "state")
    if "pan_india_stated" in p.levels and fit.pan_india:
        return Check("met", "recorded", "pan_india_stated", {}, cites, "pan_india_stated")
    if fit.regions:
        return _unknown("region_membership_not_recorded", "recorded", regions=list(fit.regions))
    if fit.stated_places:
        return Check("fail", "recorded", "no_overlap_stated", {"stated": fit.stated_places}, cites)
    if fit.observed_places:
        return _unknown("no_overlap_observed", "recorded", observed=fit.observed_places)
    return _unknown("funder_places_not_recorded")


@evaluator("shares_theme", reads={"org.themes", "pair.fit"}, params=Params)
def shares_theme(org: OrgEvidence, f: FunderEvidence | None, _p) -> Check:
    if not org.clauses:
        return _unknown("org_themes_not_recorded")
    if f.fit.shared_tag_clauses:
        return Check("met", "recorded", "shared_theme", {"shared": list(f.fit.shared_tag_clauses)},
                     (org.cite, f.cite))
    if f.fit.asserted_tag_clauses:  # only tags a person set can rule a theme out
        return Check("fail", "recorded", "no_shared_theme", {"funder_themes": list(f.fit.asserted_tag_clauses)},
                     (org.cite, f.cite))
    if f.fit.tag_clauses:
        return _unknown("funder_themes_inferred_only", "recorded", funder_themes=list(f.fit.tag_clauses))
    return _unknown("funder_themes_not_recorded")


@evaluator("shares_programme_theme", reads={"org.themes", "pair.fit"}, params=Params)
def shares_programme_theme(org: OrgEvidence, f: FunderEvidence | None, _p) -> Check:
    if not org.clauses:
        return _unknown("org_themes_not_recorded")
    if f.fit.shared_programmes:
        return Check("met", "recorded", "shared_programme_theme",
                     {"programmes": list(f.fit.shared_programmes)}, (org.cite, f.cite))
    if f.fit.asserted_programmes:
        return Check("fail", "recorded", "no_programme_in_theme", {"tagged": f.fit.asserted_programmes},
                     (org.cite, f.cite))
    if f.fit.tagged_programmes:
        return _unknown("funder_programmes_inferred_only", "recorded", tagged=f.fit.tagged_programmes)
    return _unknown("funder_programmes_not_tagged")


# --- readiness: audits, board, documents, projects ------------------------------------------

class YearsParams(Params):
    years: int


@evaluator("min_audited_years", reads={"org.financials"}, params=YearsParams)
def min_audited_years(org: OrgEvidence, _f, p: YearsParams) -> Check:
    if not org.financials:
        return _unknown("not_recorded")
    audited = sorted({x.key for x in org.financials if x.value.get("is_audited")})
    cites = tuple(sorted({x.cite for x in org.financials}))
    if len(audited) >= p.years:
        return Check("met", "recorded", "audited_years", {"years": audited}, cites)
    return Check("unknown", "recorded", "years_short_recorded", {"have": len(audited), "need": p.years}, cites)


class CountParams(Params):
    count: int


@evaluator("min_board", reads={"org.board"}, params=CountParams)
def min_board(org: OrgEvidence, _f, p: CountParams) -> Check:
    have = len(org.board)
    if not have:
        return _unknown("not_recorded")
    cites = (org.cite,)
    if have >= p.count:
        return Check("met", "recorded", "board_size", {"have": have}, cites)
    return Check("fail", "recorded", "count_short", {"have": have, "need": p.count}, cites)


class HasDocumentParams(Params):
    doc_type: str
    requires: str = "recorded"
    """'on_file' accepts only a Vault upload."""


@evaluator("has_document", reads={"org.documents"}, params=HasDocumentParams)
def has_document(org: OrgEvidence, _f, p: HasDocumentParams) -> Check:
    docs = org.documents.get(p.doc_type, ())
    vault = [d for d in docs if d.vault]
    if vault:
        return Check("met", "on_file", "document_on_file", {"document_id": vault[0].id}, (org.cite,))
    if docs and p.requires == "on_file":
        return _unknown("not_on_file", "not_on_file", document_id=docs[0].id)
    if docs:
        return Check("met", "recorded", "document_recorded", {"document_id": docs[0].id}, (org.cite,))
    return _unknown("not_recorded")


class ProjectsParams(Params):
    count: int
    fields: tuple[str, ...] = ("funder", "amount", "theme", "duration", "results")


@evaluator("min_projects", reads={"org.projects"}, params=ProjectsParams)
def min_projects(org: OrgEvidence, _f, p: ProjectsParams) -> Check:
    if not org.projects:
        return _unknown("not_recorded")
    complete = [x for x in org.projects if not x.missing(p.fields)]
    cites = tuple(x.cite for x in org.projects)
    if len(complete) >= p.count:
        return Check("met", "recorded", "projects_complete", {"complete": len(complete)}, cites)
    missing = sorted({f for x in org.projects for f in x.missing(p.fields)})
    return Check("unknown", "recorded", "projects_short",
                 {"complete": len(complete), "recorded": len(org.projects), "need": p.count, "missing": missing},
                 cites)
