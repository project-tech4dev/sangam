"""compare_fit: an organisation against funders, judged and scored in code under match-v2."""

from __future__ import annotations

from collections import Counter

from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.security import chat_user_id
from app.db.pool import get_pool
from app.matching.assessment import Match
from app.matching.match import match
from app.matching.rubric import RUBRIC_VERSION
from app.matching.rules import FunderProfile, OrgProfile, Places, has_places_or_themes
from app.repositories import matching


def _entry(m: Match) -> dict:
    return {
        "funder": f"{m.funder_name} [funder:{m.funder_id}]",
        "funder_type": m.funder_type,
        "score": m.score["of_100"] if m.score else None,
        "tier": m.tier,
        "judged": f"{m.score['earned']} of {m.score['judged_max']} points" if m.score else None,
        "card": [f"{'✓' if r.kind == 'fit' else '!'} {r.text}" for r in m.card],
        "summary": m.summary,
        "criteria": [
            {"criterion": c.label, "points": f"{c.points}/{c.max}" if c.points is not None else "unknown",
             "status": c.status, "note": c.note, "cites": c.cites}
            for c in m.criteria
        ],
        "not_judged": m.not_judged,
        "improve": m.improve,
    }


# deepagents moves any tool reply over 20k tokens to a file; the shortlist must stay well under it.
FULL_DETAIL_MAX = 10


def _gap(entry: dict) -> str:
    """The first ! card line, else the first line: what a one-line entry says about the funder."""
    card = entry["card"]
    return next((line for line in card if line.startswith("!")), card[0] if card else "")


def _headline(entry: dict) -> str:
    score = f"{entry['score']}/100 · {entry['tier']}" if entry["score"] is not None else entry["tier"]
    kind = f" · {entry['funder_type']}" if entry["funder_type"] else ""
    return f"{entry['funder']}{kind} · {score}"


def _full(n: int, entry: dict, *, summary: bool) -> list[str]:
    judged = f" · judged on {entry['judged']}" if entry["judged"] else ""
    lines = [f"{n}. {_headline(entry)}{judged}", *(f"   {line}" for line in entry["card"])]
    if summary and entry["summary"]:
        lines.append(f"   summary: {entry['summary']}")
    for c in entry["criteria"]:
        cites = f" {' '.join(c['cites'])}" if c["cites"] else ""
        judged = c["status"] if c["status"] == "unknown" else f"{c['points']} {c['status']}"
        lines.append(f"   - {c['criterion']} {judged}: {c['note']}{cites}")
    if entry["not_judged"]:
        lines.append(f"   not judged: {'; '.join(entry['not_judged'])}")
    lines += [f"   to raise the score: {action}" for action in entry["improve"]]
    return lines


def render(result: dict, *, shortlist: bool) -> str:
    """compare()'s result as text, one fact per line, so an oversized reply still pages."""
    matches = result["matches"]
    tiers = Counter(m["tier"] for m in matches)
    not_scored = result["not_scored"]
    lines = [
        f"compare_fit · {result['org']} · rubric {result['rubric']} · {result['funders_checked']} funders checked",
        f"scored {len(matches)}: " + " · ".join(f"{tiers[t]} {t}" for t in ("strong", "medium", "weak") if tiers[t])
        + f" · not scored {sum(len(v) for v in not_scored.values())}",
    ]
    unknown = Counter(c["criterion"] for m in matches for c in m["criteria"] if c["status"] == "unknown")
    if unknown:
        lines.append(f"unknown across the {len(matches)} scored: "
                     + ", ".join(f"{label} {n}" for label, n in unknown.most_common()))

    full = [m for m in matches if not shortlist or m["tier"] in ("strong", "medium")][:FULL_DETAIL_MAX if shortlist else None]
    short = [m for m in matches if m not in full]
    for n, entry in enumerate(full, 1):
        lines += ["", *_full(n, entry, summary=not shortlist)]
    if short:
        lines += ["", "one line each; compare_fit(org_id, funder_ids) gives any of them in full:"]
        lines += [f"- {_headline(e)} · {_gap(e)}" for e in short]
    if not_scored["nothing_in_common_recorded"]:
        lines += ["", "not scored, nothing in common recorded: " + ", ".join(not_scored["nothing_in_common_recorded"])]
    if not_scored["funder_has_nothing_recorded"]:
        lines += ["", "not scored, the funder has nothing recorded (unknown, not a poor fit): "
                  + ", ".join(not_scored["funder_has_nothing_recorded"])]
    return "\n".join(lines)


def compare(org: OrgProfile, funders: list[FunderProfile], places: Places, *, shortlist: bool) -> dict:
    matches = [match(org, f, places) for f in funders]
    has_data = {f.id: has_places_or_themes(f) for f in funders}
    shown = [m for m in matches if m.score or not shortlist]
    shown.sort(key=lambda m: (m.score is None, -(m.score or {}).get("of_100", 0), m.funder_id))
    unscored = [m for m in matches if m.score is None and shortlist]
    return {
        "org": f"{org.name} [org:{org.id}]",
        "rubric": RUBRIC_VERSION,
        "funders_checked": len(funders),
        "matches": [_entry(m) for m in shown],
        "not_scored": {
            # Recorded on both sides with nothing shared: a real non-fit.
            "nothing_in_common_recorded": [f"{m.funder_name} [funder:{m.funder_id}]"
                                           for m in unscored if has_data[m.funder_id]],
            # The funder has no places or themes recorded: unknown, never a non-fit.
            "funder_has_nothing_recorded": [f"{m.funder_name} [funder:{m.funder_id}]"
                                            for m in unscored if not has_data[m.funder_id]],
        },
    }


@tool
async def compare_fit(org_id: int, funder_ids: list[int] | None = None) -> str:
    """Score one organisation against funders under the match-v2 rubric, from the database, in one call.

    Args:
        org_id: the organisation's id (resolve the name with db_query first).
        funder_ids: the funders to score. Omit it to check every funder: those sharing a place or
            a theme are scored, the rest are listed under not_scored.

    Returns text, ranked by score (out of 100, highest first). A header gives the funders checked,
    the count per tier (strong >= 75, medium 55-74, weak < 55) and which criteria were unknown how
    often. Then each funder in full: score, tier, "judged on N of M points", card lines (✓ fit,
    ! gap), the seven criteria (theme 25, geography 15, population 15, eligibility 20,
    relationship 10, funding size 10, capacity 5) as "- label points status: note cites",
    "not judged" and "to raise the score" lines. With funder_ids every funder named is in full,
    with its summary. Without, the top strong and medium fits (up to 10) are in full and every
    other scored funder is one line: score, tier and its first gap; call
    compare_fit(org_id, [their ids]) once for any you need in full. Last come the funders not
    scored: nothing in common recorded, and nothing recorded at all (unknown, never a poor fit).
    An unknown criterion is left out of the score, never counted as zero. Every figure is
    computed in code from recorded rows: repeat it, never recompute or re-judge it.

    Only Sangam staff and the organisation's stewards and admins may run it. For anyone else it
    returns "compare_fit refused": report that plainly, and never assemble a match from db_query.
    """
    try:
        if not await matching.may_run(get_pool(), chat_user_id.get(), org_id):
            return (f"compare_fit refused: running a match for organisation {org_id} is for its stewards, "
                    "admins and Sangam staff.")
        org, funders, places = await matching.load(
            get_pool(), org_id, funder_ids, timeout_ms=get_settings().sql_timeout_ms
        )
        if org is None:
            return f"compare_fit failed: no organisation with id {org_id}"
        if funder_ids and (missing := sorted(set(funder_ids) - {f.id for f in funders})):
            return f"compare_fit failed: no funder with id {', '.join(map(str, missing))}"
        shortlist = funder_ids is None
        return render(compare(org, funders, places, shortlist=shortlist), shortlist=shortlist)
    except Exception as exc:  # noqa: BLE001 - errors are return values: a raise aborts the run
        return f"compare_fit failed: {exc}"
