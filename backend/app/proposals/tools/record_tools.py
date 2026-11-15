"""What Sangam already holds about the proposal's org and its fit with the funder. Public rows only, every one cited."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.db.pool import get_pool
from app.proposals import context
from app.proposals.records import match_text, org_text
from app.repositories import profile_facts
from app.repositories import proposals as repo

logger = logging.getLogger(__name__)


@tool
async def read_match() -> str:
    """Read the saved Funder Match this proposal started from: the score, each criterion with its points and
    note, and what would raise the score. Cited [score:N]."""
    try:
        p = await context.current()
        if p is None:
            return "No proposal is open in this chat."
        match = await repo.match_for(get_pool(), p.org_id, p.funder_id)
        if match is None or match["id"] != (p.work.get("match") or {}).get("id"):
            saved = p.work.get("match") or {}
            note = "" if match is None else " A newer run exists; this proposal keeps the one it started from."
            return f"The saved match [score:{saved.get('id')}] scored {saved.get('score')}/100.{note}"
        return match_text(match)
    except Exception as exc:
        logger.exception("read_match failed")
        return f"read_match failed: {type(exc).__name__}"


@tool
async def read_org_record() -> str:
    """Read what Sangam's registry holds about this proposal's organisation: identity, registrations (no numbers),
    places, recent finances, programmes with their figures, and past funding. Public rows only. Cited [org:N] and
    [activity:N]."""
    try:
        p = await context.current()
        if p is None:
            return "No proposal is open in this chat."
        facts = await profile_facts.org_facts(get_pool(), get_pool(), str(p.org_id))
        if facts is None:
            return f"Sangam holds no record for {p.org_name}."
        return org_text(facts)
    except Exception as exc:
        logger.exception("read_org_record failed")
        return f"read_org_record failed: {type(exc).__name__}"
