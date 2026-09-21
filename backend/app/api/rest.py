"""Plain REST endpoints for the Next.js pages (registry tables, score matrix)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.db import get_pool

router = APIRouter()


@router.get("/orgs")
async def list_orgs(user_id: UUID = Depends(get_current_user)) -> list[dict]:
    pool = get_pool()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT id, slug, name, darpan_id, cohort, state, district, sectors,
                       source_name, fetched_at
                FROM orgs ORDER BY name
                """
            )
        ).fetchall()
    return rows


@router.get("/funders")
async def list_funders(user_id: UUID = Depends(get_current_user)) -> list[dict]:
    pool = get_pool()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT f.id, f.slug, f.name, f.funder_type, f.website,
                       f.focus_sectors, f.geographies, f.profile,
                       COALESCE(
                         (SELECT jsonb_object_agg(sub.version, sub.total_score)
                          FROM (
                            SELECT DISTINCT ON (r.version) r.version, fs.total_score
                            FROM fit_scores fs JOIN rubrics r ON r.id = fs.rubric_id
                            WHERE fs.funder_id = f.id
                            ORDER BY r.version, fs.scored_at DESC
                          ) sub),
                         '{}'::jsonb
                       ) AS latest_scores
                FROM funders f ORDER BY f.name
                """
            )
        ).fetchall()
    return rows


@router.get("/funders/{funder_id}/scores")
async def funder_scores(funder_id: int, user_id: UUID = Depends(get_current_user)) -> list[dict]:
    pool = get_pool()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT fs.id, o.name AS org_name, r.version AS rubric_version,
                       fs.total_score, fs.max_score, fs.scored_by, fs.scored_at, fs.notes
                FROM fit_scores fs
                JOIN orgs o ON o.id = fs.org_id
                JOIN rubrics r ON r.id = fs.rubric_id
                WHERE fs.funder_id = %s
                ORDER BY r.version, fs.scored_at DESC
                """,
                (funder_id,),
            )
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No scores for this funder")
    return rows
