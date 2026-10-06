"""Judgements of fit: the matching engine behind one call per job. No SQL here (R23)."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool

from app.agent.tools import match_render as render
from app.db.pool import get_pool
from app.matching import service
from app.matching.models import Ambiguous, Resolved

MAX_COMPARED = 3


async def resolve(conn: Any, kind: Literal["org", "funder"], text: str) -> Resolved | str:
    """The one id the text names, or the rendered candidates for the model to ask about."""
    found = await service.resolve(conn, kind, text)
    return render.render_ambiguous(found) if isinstance(found, Ambiguous) else found


@tool
async def match_funders(org: str, limit: int = 10) -> str:
    """Rank every funder for one organisation — "which funders fit KABIL?", "who can Goonj apply to?".

    `org` is a name, slug or id. Returns, in one call, the ranked funders with each one's gate status
    (passed / unverified), a score range computed by Sangam and its fit checks; the organisation's own
    gaps; every funder with not enough recorded to rank, by name; and the funders that did not pass,
    with the gate that failed. Cited [org:N] / [funder:N]. Never rebuild this ranking in db_query.
    """
    try:
        async with get_pool().connection() as conn:
            o = await resolve(conn, "org", org)
            if isinstance(o, str):
                return o
            return render.render_shortlist(await service.shortlist(conn, o.id, limit=max(1, min(limit, 50))))
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"match_funders failed: {exc}"


@tool
async def explain_match(org: str, funders: list[str]) -> str:
    """Every check for one organisation against one to three funders — "why is HDFC first for KABIL?",
    "what does KABIL need for SBI Foundation?", "compare HDFC and Tata Trusts for KABIL".

    Names, slugs or ids. Returns each check's outcome (met / fail / unknown, and why unknown: not
    recorded, searched and not found, not on file), its evidence citation, the gate status, the score
    range and the gaps in the order to close them. With more than one funder, a side-by-side table first.
    """
    try:
        if not 1 <= len(funders) <= MAX_COMPARED:
            raise ValueError(f"name one to three funders, not {len(funders)}")
        async with get_pool().connection() as conn:
            o = await resolve(conn, "org", org)
            if isinstance(o, str):
                return o
            ids = []
            for text in funders:
                f = await resolve(conn, "funder", text)
                if isinstance(f, str):
                    return f
                ids.append(f.id)
            return render.render_assessments(await service.assess_many(conn, o.id, ids))
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"explain_match failed: {exc}"
