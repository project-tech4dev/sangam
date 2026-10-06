"""Match and profile results as cited text for the model. No queries: the service hands these objects over."""

from __future__ import annotations

from app.agent.tools.sql.render import MAX_OUTPUT_CHARS
from app.matching.evidence import OrgProfile
from app.matching.models import (
    Ambiguous,
    Assessment,
    CheckResult,
    Dimension,
    FunderList,
    FunderProfile,
    FunderRef,
    OrgRef,
    Shortlist,
)

REASONS = {
    # place
    "shared_district": "works in the same district: {places}",
    "shared_state": "shares a state: {places}",
    "pan_india_stated": "says it funds across India",
    "region_membership_not_recorded": "states a region ({regions}); which states it covers is not recorded",
    "no_overlap_stated": "funds only elsewhere: {stated} stated places, none shared",
    "no_overlap_observed": "has given elsewhere (places given: {observed}) but never states a limit",
    "funder_places_not_recorded": "where it gives is not recorded",
    "org_places_not_recorded": "the organisation's places are not recorded",
    # theme and programme
    "shared_theme": "shares a theme: {shared}",
    "no_shared_theme": "funds other themes only: {funder_themes}",
    "funder_themes_inferred_only": "its themes are only inferred ({funder_themes}), none shared",
    "funder_themes_not_recorded": "its themes are not recorded",
    "org_themes_not_recorded": "the organisation's themes are not recorded",
    "shared_programme_theme": "runs a programme in the theme: {programmes}",
    "no_programme_in_theme": "none of its {tagged} tagged programmes is in the theme",
    "funder_programmes_inferred_only": "{tagged} programmes with only inferred themes, none in the theme",
    "funder_programmes_not_tagged": "its programmes' themes are not recorded",
    # credentials
    "recorded": "recorded: {value}",
    "document_on_file": "certificate on file in the Vault (document {document_id})",
    "conflicting_evidence": "sources disagree: {event} on {as_of}, yet a current record exists",
    "superseded": "superseded on {as_of}; the replacement is not recorded",
    "validity_ended": "validity ended {valid_until}; a renewal is not recorded",
    "searched_not_found": "searched {searched_on}, not found",
    "not_recorded": "not recorded",
    "registered": "registered ({as_of})",
    "renewed": "renewed ({as_of})",
    "checked_active": "checked active ({as_of})",
    "restored": "restored ({as_of})",
    "expired": "expired ({as_of})",
    "suspended": "suspended ({as_of})",
    "cancelled": "cancelled ({as_of})",
    "surrendered": "surrendered ({as_of})",
    # readiness
    "audited_years": "audited accounts for {years}",
    "years_short_recorded": "{have} of {need} audited years recorded",
    "board_size": "board of {have}",
    "count_short": "board of {have}, needs {need}",
    "document_recorded": "document recorded (document {document_id})",
    "not_on_file": "recorded, but not uploaded to the Vault",
    "projects_complete": "{complete} projects fully recorded",
    "projects_short": "{complete} of {need} projects fully recorded ({recorded} recorded; missing {missing})",
    # engine and search
    "not_applicable": "does not apply to this funder",
    "funder_type": "type: {funder_type}",
    "funder_type_not_recorded": "funder type not recorded",
}

_UNKNOWN = {"not_researched": "not recorded", "searched_not_found": "searched, not found",
            "not_on_file": "not on file", "recorded": "unknown", "on_file": "unknown",
            "not_applicable": "n/a"}


class _Params(dict):
    def __missing__(self, key):
        return "?"


def _plain(value) -> str:
    """A Schedule VII slug as words: csr-education-and-livelihoods → education & livelihoods."""
    s = str(value)
    return s[4:].replace("-and-", " & ").replace("-", " ") if s.startswith("csr-") else s


def phrase(code: str, params: dict) -> str:
    shown = _Params({k: ", ".join(map(_plain, v)) if isinstance(v, list | tuple) else v for k, v in params.items()})
    return REASONS.get(code, code.replace("_", " ")).format_map(shown)


def mark(outcome: str, basis: str) -> str:
    if outcome == "met":
        return "✓ met" + (" (on file)" if basis == "on_file" else "")
    return "✗ fail" if outcome == "fail" else f"? {_UNKNOWN.get(basis, 'unknown')}"


def inr(rupees: int | None) -> str:
    """Indian digit grouping, so a figure is copied rather than converted."""
    if rupees is None:
        return "not recorded"
    s = str(abs(int(rupees)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        head, groups = head[:-2], [head[-2:], *groups]
    out = ",".join([g for g in [head, *groups] if g] + [tail]) if head or groups else tail
    return ("-₹" if rupees < 0 else "₹") + out


def _org(o: OrgRef) -> str:
    return f"{o.name} [org:{o.id}]"


def _funder(f: FunderRef) -> str:
    return f"{f.name} [funder:{f.id}]"


def _cap(lines: list[str]) -> str:
    out, used = [], 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 > MAX_OUTPUT_CHARS:
            out.append(f"… output cut at {MAX_OUTPUT_CHARS} chars: {len(lines) - i} more lines not shown. "
                       "Ask for fewer funders, or the next page with a higher offset.")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _outcome(outcome: str, basis: str, code: str, params: dict) -> str:
    m, p = mark(outcome, basis), phrase(code, params)
    return m if m.endswith(p) else f"{m} — {p}"


def _check_line(c: CheckResult) -> str:
    cites = (" " + " ".join(c.cites)) if c.cites else ""
    return f"  {c.label}: {_outcome(c.outcome, c.basis, c.reason_code, c.reason_params)}{cites}"


def _score(a: Assessment) -> str:
    return f"score {a.score_min}–{a.score_max} (coverage {a.coverage}%)"


def _header(version: int, digest: str) -> str:
    return (f"criteria v{version} ({digest[:8]}). Scores are computed by Sangam from the cited rows: the low end "
            "counts every unknown as not met, the high end as met.")


# --- shortlist and assessments ---------------------------------------------------------------

def render_shortlist(sl: Shortlist) -> str:
    ranked_total = sl.total_funders - len(sl.not_enough_recorded) - len(sl.did_not_pass)
    lines = [f"Funders for {_org(sl.org)} · {sl.total_funders} funders judged · {_header(sl.criteria_version, sl.criteria_hash)}"]
    own: dict[str, CheckResult] = {}
    for a in sl.ranked:
        for g in a.gaps:
            if g.category != "fit":
                own.setdefault(g.code, g)
    if own:
        lines.append(f"{sl.org.name}'s own gaps (the same whichever funder):")
        lines += [_check_line(g) for g in own.values()]
    first = sl.offset + 1
    lines.append(f"\nRANKED ({ranked_total})" + (f", showing {first}–{sl.offset + len(sl.ranked)}" if sl.ranked else ""))
    for i, a in enumerate(sl.ranked, start=first):
        fit = "; ".join(f"{c.code} {_outcome(c.outcome, c.basis, c.reason_code, c.reason_params)}"
                        for c in a.checks if c.category == "fit")
        lines.append(f"{i}. {_funder(a.funder)} · {a.gate_status} · {_score(a)} · {fit}")
    lines.append(f"\nNOT ENOUGH RECORDED TO RANK ({len(sl.not_enough_recorded)}): fit is unknown, not poor")
    if sl.not_enough_recorded:
        lines.append(", ".join(_funder(f) for f in sl.not_enough_recorded))
    lines.append(f"\nDID NOT PASS ({len(sl.did_not_pass)}): positive evidence against a gate")
    for a in sl.did_not_pass:
        why = "; ".join(phrase(c.reason_code, c.reason_params) for c in a.checks if c.outcome == "fail")
        lines.append(f"{_funder(a.funder)} on {', '.join(a.failed_gates)}: {why}")
    return _cap(lines)


def render_assessments(assessments: list[Assessment]) -> str:
    a0 = assessments[0]
    lines = [f"Assessment of {_org(a0.org)} · {_header(a0.criteria_version, a0.criteria_hash)}"]
    if len(assessments) > 1:
        lines.append("\n| check | " + " | ".join(_funder(a.funder) for a in assessments) + " |")
        lines.append("|---" * (len(assessments) + 1) + "|")
        lines.append("| gate | " + " | ".join(a.gate_status for a in assessments) + " |")
        lines.append("| score | " + " | ".join(f"{a.score_min}–{a.score_max}" for a in assessments) + " |")
        for i, c in enumerate(a0.checks):
            lines.append(f"| {c.label} | " + " | ".join(mark(a.checks[i].outcome, a.checks[i].basis)
                                                        for a in assessments) + " |")
    for a in assessments:
        failed = f" on {', '.join(a.failed_gates)}" if a.failed_gates else ""
        lines.append(f"\n{_funder(a.funder)} · gate {a.gate_status}{failed} · {_score(a)}")
        lines += [_check_line(c) for c in a.checks]
        if a.gaps:
            lines.append("  gaps, in order: " + "; ".join(f"{g.label} ({phrase(g.reason_code, g.reason_params)})"
                                                          for g in a.gaps))
    return _cap(lines)


# --- profiles ----------------------------------------------------------------------------------

def _or_unrecorded(items: list[str]) -> str:
    return "; ".join(items) if items else "not recorded"


def render_org(op: OrgProfile) -> str:
    ev, cite = op.evidence, op.evidence.cite
    docs = [f"{t}: " + ", ".join(("on file in the Vault" if d.vault else "recorded") + f" (document {d.id})"
                                 for d in ds) for t, ds in ev.documents.items()]
    lines = [
        f"{_org(ev.org)} — every line is from {cite} unless it carries its own marker",
        f"Districts: {_or_unrecorded(list(ev.districts.values()))}",
        f"States: {_or_unrecorded(list(ev.states.values()))}",
        f"Registered office: {op.registered or 'not recorded'}",
        f"Themes (Schedule VII): {_or_unrecorded(list(ev.clauses.values()))}",
        "Registrations: " + _or_unrecorded([f"{k}: {f.value}" + (f" (as of {f.as_of})" if f.as_of else "")
                                            for k, f in ev.identifiers.items()]),
        "Credential events: " + _or_unrecorded([f"{k}: {phrase(f.value, {'as_of': f.as_of})}"
                                                for k, f in ev.credential_events.items()]),
        "Financials: " + _or_unrecorded([f"{f.key} income {inr(f.value.get('total_income'))}"
                                         + (", audited" if f.value.get("is_audited") else ", audit not recorded")
                                         for f in ev.financials]),
        "Board (office bearers): " + (f"{len(ev.board)} — " + ", ".join(f.key for f in ev.board)
                                      if ev.board else "not recorded"),
        f"Documents: {_or_unrecorded(docs)}",
        "Projects: " + (f"{len(ev.projects)} recorded — " + ", ".join(p.cite for p in ev.projects)
                        if ev.projects else "not recorded"),
        "Searched and not found: " + _or_unrecorded([f"{c} ({on.isoformat()})" for c, on in ev.not_found]),
    ]
    return _cap(lines)


def render_funder(pf: FunderProfile) -> str:
    f = pf.funder
    lines = [
        f"{_funder(f)} — every line is from [funder:{f.id}] unless it carries its own marker",
        f"Type: {f.funder_type or 'not recorded'} · Section 135 bound: "
        + ("not recorded" if pf.section_135_bound is None else "yes" if pf.section_135_bound else "no")
        + (f" · {pf.website}" if pf.website else ""),
        "Where it says it gives: " + _or_unrecorded([f"{p.name} ({p.kind}, {p.role})" for p in pf.places]),
        "Registered office: " + _or_unrecorded([p.name for p in pf.registered]),
        "Where it has given (footprints): " + (f"{pf.footprint_places} places, latest {pf.footprint_latest_year}"
                                               if pf.footprint_places else "not recorded"),
        "Themes: " + _or_unrecorded([t.label + (" (inferred)" if t.inferred else "") for t in pf.themes]),
        "Programmes: " + (f"{len(pf.programmes)} — " + "; ".join(
            p.name + (f" ({', '.join(p.clauses)})" if p.clauses else "") for p in pf.programmes[:15])
            if pf.programmes else "not recorded"),
        "Eligibility bars: " + ("; ".join(f"{q.kind}: {q.criterion}" for q in pf.requirements)
                                if pf.requirements else "no eligibility bars recorded"),
        "CSR years: " + _or_unrecorded([f"{y.fiscal_year} prescribed {inr(y.prescribed_csr)}, spent "
                                        f"{inr(y.total_spent)}" for y in pf.csr_years]),
        "CSR spend: " + (f"{pf.spend_rows} rows; by state " + _or_unrecorded(
            [f"{n} {inr(a)}" for n, a in pf.spend_by_state]) + "; by sector " + _or_unrecorded(
            [f"{n} {inr(a)}" for n, a in pf.spend_by_sector]) if pf.spend_rows else "not recorded"),
        "Partners: " + (", ".join(f"{k} {n}" for k, n in sorted(pf.partner_kinds.items())) + " — " + ", ".join(
            p.name + (f" [org:{p.org_id}]" if p.org_id else "") for p in pf.partners)
            if pf.partners else "not recorded"),
        "Open calls: " + _or_unrecorded([
            c.title + (f" (deadline {c.deadline}{', passed' if c.deadline_passed else ''})" if c.deadline else "")
            + (f", {inr(c.amount_min)}–{inr(c.amount_max)}" if c.amount_min or c.amount_max else "")
            + (f" {c.url}" if c.url else "") for c in pf.calls]),
    ]
    return _cap(lines)


# --- search and resolution ---------------------------------------------------------------------

def _dims(dims: dict[str, Dimension]) -> str:
    return "; ".join(f"{k} {_outcome(d.outcome, d.basis, d.reason_code, d.reason_params)}"
                     for k, d in dims.items())


def render_funders(fl: FunderList) -> str:
    asked = " · ".join(x for x in (
        f"place {', '.join(fl.places)}" if fl.places else "", f"theme {', '.join(fl.themes)}" if fl.themes else "",
        f"type {', '.join(fl.funder_types)}" if fl.funder_types else "") if x)
    lines = [(f"Funders for {asked}: {fl.matched_total} match, {len(fl.not_recorded)} not recorded, "
              f"{fl.no_overlap} no overlap ({fl.total_funders} funders)"),
             f"\nMATCH ({fl.matched_total})" + (f", showing {fl.offset + 1}–{fl.offset + len(fl.matched)}"
                                                if fl.matched else "")]
    lines += [f"{i}. {_funder(m.funder)} · {_dims(m.dims)}" for i, m in enumerate(fl.matched, start=fl.offset + 1)]
    lines.append(f"\nNOT RECORDED ({len(fl.not_recorded)}): might match; the record cannot say")
    lines += [f"{_funder(m.funder)} · {_dims(m.dims)}" for m in fl.not_recorded]
    return _cap(lines)


def render_ambiguous(a: Ambiguous) -> str:
    if not a.candidates:
        return f"No {a.kind} matches {a.text!r}. Ask the user to check the name; do not guess."
    marker = (lambda c: f"[org:{c.id}]") if a.kind == "org" else (lambda c: f"[funder:{c.id}]")
    return "\n".join([f"{a.text!r} could mean more than one {a.kind}. Ask the user which one; do not pick:"]
                     + [f"- {c.name} {marker(c)}" + (f" ({c.slug})" if c.slug else "") for c in a.candidates])
