"""Profiles and lists, read through the matching engine's own loaders (R17). No SQL here (R23)."""

from __future__ import annotations

from langchain_core.tools import tool

from app.agent.tools import match_render as render
from app.agent.tools.match_tools import resolve
from app.db.pool import get_pool
from app.matching import service


@tool
async def get_org(org: str) -> str:
    """Everything recorded about one organisation — "tell me about KABIL".

    `org` is a name, slug or id. Returns its districts and states, themes, registrations (12A, 80G,
    CSR-1, FCRA) and credential events, audited financials, board, documents (and whether each is on
    file in the Vault), projects, and what research searched for and did not find. A field with nothing
    behind it says "not recorded". Cited [org:N] / [grant:N]. Do not re-query these fields in db_query.
    """
    try:
        async with get_pool().connection() as conn:
            o = await resolve(conn, "org", org)
            return o if isinstance(o, str) else render.render_org(await service.profile(conn, "org", o.id))
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"get_org failed: {exc}"


@tool
async def get_funder(funder: str) -> str:
    """Everything recorded about one funder — "tell me about HDFC Bank", "does SBI Foundation set any bars?".

    `funder` is a name, slug or id. Returns its type, where it says it gives and where it has given,
    themes (inferred ones marked), programmes, eligibility bars ("no eligibility bars recorded" when
    none are), CSR years and spend in rupees, partners and open calls. Cited [funder:N] / [org:N].
    """
    try:
        async with get_pool().connection() as conn:
            f = await resolve(conn, "funder", funder)
            return f if isinstance(f, str) else render.render_funder(await service.profile(conn, "funder", f.id))
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"get_funder failed: {exc}"


@tool
async def find_funders(places: list[str] | None = None, themes: list[str] | None = None,
                       funder_types: list[str] | None = None, limit: int = 20, offset: int = 0) -> str:
    """List funders by place, theme or type — "which CSR funders give in Assam?", "who funds livelihoods?".

    `places` are district or state names; `themes` are sector or Schedule VII names; `funder_types` are
    values such as corporate_csr or private_foundation. Each must be satisfied. Returns the matches with
    the level each matched at (district, state, stated pan-India), every funder whose record cannot say
    (not recorded), and a count of those with no overlap. An unknown name returns near matches to ask about.
    """
    try:
        async with get_pool().connection() as conn:
            return render.render_funders(await service.find_funders(
                conn, places=places or [], themes=themes or [], funder_types=funder_types or [],
                limit=max(1, min(limit, 50)), offset=max(0, offset)))
    except Exception as exc:  # noqa: BLE001 - error-as-string tool discipline
        return f"find_funders failed: {exc}"
