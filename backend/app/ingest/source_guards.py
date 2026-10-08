"""Where a fact came from decides what it may claim: aggregator and prior-research values are claimed (C8, C14).
Pure: no pool, no settings. Refused at save so the model relabels; re-checked and held at promote."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from app.ingest.sources import AccessRule, normal_path, rule_for_url, sources_on_host

TIER_FIELDS: frozenset[str] = frozenset({"source_type", "evidence_tier"})
# The org concepts whose tables carry source_type and evidence (0033); anything else cannot be marked claimed.
TIERED_ORG_CONCEPTS: frozenset[str] = frozenset(
    {"org_identity", "org_identifier", "org_financials", "org_location", "program", "metric", "contact"}
)


def labelled_by(url: str) -> tuple[str, str] | None:
    """(the source_type a finding citing this URL must carry, the source's name), or None."""
    found = rule_for_url(url)
    if found and found[0] is AccessRule.INTERNAL_RESEARCH:
        path, why = normal_path(urlsplit(url).path)
        if why is None and found[1].claims_path(path):
            return "prior_research", found[1].name
    # Any page on an aggregator's host is the aggregator's account, whichever entry governs the path.
    for source in sources_on_host(urlsplit(url).hostname or ""):
        if source.access_rule is AccessRule.MANUAL_AGGREGATOR:
            return "aggregator", source.name
    return None


def problems(
    concept: str, finding: dict[str, Any], fields: frozenset[str], entity_kind: str | None,
    *, at: Literal["save", "promote"],
) -> list[str]:
    """Why this finding may not be saved (at='save') or promoted (at='promote'); empty when it may."""
    label = labelled_by(str(finding.get("source_url") or ""))
    if label is None:
        if finding.get("source_type") == "prior_research":
            return [(f"{concept}: prior_research cites the dossier file at the pinned commit. A value re-read "
                     f"at its own source takes that source's type; one only the dossier states cites the dossier.")]
        return []
    source_type, name = label
    if TIER_FIELDS <= fields and (finding.get("source_type") != source_type
                                  or finding.get("evidence_tier") != "claimed"):
        return [(f"{concept} from {name}: set source_type='{source_type}' and evidence_tier='claimed'. A value "
                 f"from {name} is claimed until its own source is re-read and saved as its own finding.")]
    if at == "promote" and not (entity_kind == "org" and concept in TIERED_ORG_CONCEPTS):
        return [(f"{concept} from {name}: its table cannot mark a value claimed, so it stays research until "
                 f"a primary source states it.")]
    return []


def check_research(findings: list[Any], entity_kind: str | None) -> list[str]:
    """Every problem in a payload being saved; findings are the pydantic models."""
    out: list[str] = []
    for f in findings:
        out += problems(f.concept, f.model_dump(), frozenset(type(f).model_fields), entity_kind, at="save")
    return out


def hold_at_promote(
    findings: list[dict[str, Any]], entity_kind: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """(findings that may be promoted, a held reason for each that may not)."""
    from app.ingest.research_records import FINDING_MODELS  # research_records imports this module

    kept: list[dict[str, Any]] = []
    held: list[str] = []
    for f in findings:
        model = FINDING_MODELS.get(str(f.get("concept")))
        fields = frozenset(model.model_fields) if model else frozenset()
        why = problems(str(f.get("concept")), f, fields, entity_kind, at="promote")
        held.extend(why)
        if not why:
            kept.append(f)
    return kept, held
