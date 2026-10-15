"""make calls-pull: read each funder's calls page, write the open calls, close the expired ones. No agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import trafilatura

from app.core.egress import EgressRefused, guarded_client
from app.ingest import writer
from app.ingest.access import canonical_url, check_url
from app.ingest.adapters._http import USER_AGENT
from app.ingest.calls import extract, find
from app.ingest.geography import resolve_location
from app.ingest.records import RfpRecord
from app.ingest.taxonomy import TAG_SLUGS

logger = logging.getLogger(__name__)

PINNED = json.loads((Path(__file__).parent / "pinned.json").read_text(encoding="utf-8"))["sources"]
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml",
           "Accept-Encoding": "gzip, deflate"}
MIN_TEXT = 200
PARALLEL = 4
IST = ZoneInfo("Asia/Kolkata")  # a deadline is an Indian date


@dataclass
class Outcome:
    funder: str
    page: str | None = None
    written: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    undated: list[str] = field(default_factory=list)
    look: str | None = None  # why a person should look at this funder by hand

    def line(self) -> str:
        if self.look:
            return f"{self.funder}: NEEDS A LOOK. {self.look}"
        bits = [f"{len(self.written)} open written"]
        if self.passed:
            bits.append(f"{len(self.passed)} past deadline ({'; '.join(self.passed)})")
        if self.undated:
            bits.append(f"{len(self.undated)} with no date ({'; '.join(self.undated)})")
        return f"{self.funder}: {', '.join(bits)}. Page {self.page}"


@dataclass
class Deps:
    model: object
    api_key: str

    @classmethod
    def from_settings(cls, s) -> Deps:
        from app.agent.models import resolve_model

        return cls(model=resolve_model(s.utility_model), api_key=s.tavily_api_key)


def _feed_text(xml: str) -> str:
    """RSS 1.0 or 2.0 items as plain lines; the extractor decides which, if any, are grant calls."""
    root = ET.fromstring(xml)
    lines = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in item}
        lines.append(" | ".join(f"{k}: {v}" for k, v in fields.items() if v))
    return "\n".join(lines)


async def read_page(url: str, *, feed: bool = False) -> tuple[str | None, str | None]:
    """(text, None), or (None, why it could not be read). Checked against robots and the source registry first."""
    url = canonical_url(url)
    if why := await check_url(url):
        return None, why
    try:
        async with guarded_client(timeout=25, headers=HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
    except EgressRefused as refused:
        return None, refused.reply
    except httpx.HTTPStatusError as exc:
        return None, f"{url} answered HTTP {exc.response.status_code}."
    except httpx.HTTPError as exc:
        return None, f"{url} could not be fetched ({type(exc).__name__})."
    kind = response.headers.get("content-type", "").lower()
    if "pdf" in kind or url.lower().split("?")[0].endswith(".pdf"):
        return None, f"{url} is a PDF, which the pull does not read."
    if feed:
        return _feed_text(response.text), None
    text = trafilatura.extract(response.text, url=url, include_links=True, output_format="markdown") or ""
    if len(text) < MIN_TEXT:
        return None, f"{url} has no readable text ({len(text)} characters); it may need a browser to render."
    return text, None


async def _funders(pool, slugs: list[str] | None) -> list[dict]:
    sql = "SELECT id, slug, name, website, calls_url FROM funders WHERE registry_status <> 'hidden'"
    async with pool.connection() as conn:
        if slugs:
            return await (await conn.execute(sql + " AND slug = ANY(%s) ORDER BY name", (slugs,))).fetchall()
        return await (await conn.execute(sql + " ORDER BY name")).fetchall()


async def _tag_ids(conn, call: extract.Call) -> list[int]:
    """The call's themes, and its domains so a call with no theme still reaches orgs in its field."""
    slugs = [TAG_SLUGS["themes"][t] for t in call.themes]
    rows = await (await conn.execute(
        "SELECT id FROM tags WHERE (slug = ANY(%s) OR (kind = 'domain' AND code = ANY(%s))) "
        "AND status <> 'deprecated' ORDER BY kind = 'domain' DESC, id",
        (slugs, call.domains))).fetchall()
    return [r["id"] for r in rows]


async def _write(conn, funder: dict, call: extract.Call, *, page: str, text: str) -> str:
    rec = RfpRecord(
        funder_name=funder["name"], title=call.title.strip(), url=call.url or page, deadline=call.deadline,
        amount_min=call.amount_min, amount_max=call.amount_max, eligibility=call.eligibility,
        source_url=page, source_name=f"{funder['name']} website", fetched_at=datetime.now(UTC),
        content_hash=hashlib.sha256(text.encode()).hexdigest(), extractor_version=extract.PROMPT_VERSION,
    )
    places = []
    for state in call.states:
        location_id, why = await resolve_location(conn, state)
        if location_id is None:
            logger.info("calls: %s place %r not resolved: %s", funder["slug"], state, why)
        else:
            places.append(location_id)
    tags = await _tag_ids(conn, call)
    status, rfp_id, _ = await writer.write_rfp(
        conn, rec, funder["id"], location_id=places[0] if places else None,
        tag_id=tags[0] if tags else None, document_id=None)
    # write_rfp attaches one place and one theme; a call names more.
    for location_id in places[1:]:
        await conn.execute(
            "INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at) "
            "VALUES (%s, %s, 'funds', %s, %s, %s) ON CONFLICT (rfp_id, location_id) DO NOTHING",
            (rfp_id, location_id, rec.source_url, rec.source_name, rec.fetched_at))
    for tag_id in tags[1:]:
        await conn.execute(
            "INSERT INTO rfp_tags (rfp_id, tag_id, role, is_inferred, tagged_by) "
            "VALUES (%s, %s, 'secondary', true, %s) ON CONFLICT (rfp_id, tag_id) DO NOTHING",
            (rfp_id, tag_id, writer.EXTRACTOR_TAGGER))
    return status


async def pull_one(pool, funder: dict, deps: Deps, *, pinned: dict | None) -> Outcome:
    out = Outcome(funder=funder["name"])
    try:
        page = (pinned or {}).get("url") or funder["calls_url"]
        if page is None:
            async with pool.connection() as conn:
                found, failed = await find.candidates(conn, funder, api_key=deps.api_key)
            if not found:
                out.look = "no website and no page Import cited, so nowhere to look."
                return out
            page = await extract.pick_page(deps.model, funder=funder["name"], candidates=found)
            if page is None:
                out.look = f"none of {len(found)} pages on its site looks like a calls page"
                out.look += f"; {failed}." if failed else "."
                return out
        out.page = page
        text, why = await read_page(page, feed=bool((pinned or {}).get("feed")))
        if text is None:
            out.look = why + (f" Known: {pinned['note']}" if pinned and pinned.get("note") else "")
            return out
        calls = await extract.extract_calls(deps.model, funder=funder["name"], url=page, text=text)
        today = datetime.now(IST).date()
        async with pool.connection() as conn, conn.transaction():
            for call in calls:
                if call.deadline is None:
                    out.undated.append(call.title)
                elif call.deadline < today:
                    out.passed.append(f"{call.title}, {call.deadline:%d %b %Y}")
                else:
                    await _write(conn, funder, call, page=page, text=text)
                    out.written.append(call.title)
            if calls:  # kept only when it held a call, so a wrong pick is searched again next time
                await conn.execute(
                    "UPDATE funders SET calls_url = coalesce(calls_url, %s), calls_url_found_at = now() "
                    "WHERE id = %s", (page, funder["id"]))
    except Exception as exc:  # one funder's failure is a report line, not the end of the pull
        logger.exception("calls: %s failed", funder["slug"])
        out.look = f"the pull failed here ({type(exc).__name__}: {exc})."
    return out


async def close_expired(pool) -> int:
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "UPDATE rfps SET status = 'closed' WHERE status = 'open' AND deadline < current_date RETURNING id"
        )).fetchall()
    return len(rows)


async def run(pool, deps: Deps, slugs: list[str] | None) -> list[str]:
    """Every pinned source first, whether or not Sangam has the funder, then the rest. Returns the report."""
    funders = await _funders(pool, slugs)
    by_slug = {f["slug"]: f for f in funders}
    report: list[str] = []
    pinned_slugs = {p["slug"] for p in PINNED}
    for p in PINNED:
        if slugs and p["slug"] not in slugs:
            continue
        if p["slug"] not in by_slug:
            report.append(f"{p['slug']}: NEEDS A LOOK. Pinned, but not in Sangam; add it with Import first. "
                          f"Known: {p['note']}")
    for s in slugs or []:
        if s not in by_slug and s not in pinned_slugs:
            report.append(f"{s}: no funder in Sangam has this slug; nothing read.")
    gate = asyncio.Semaphore(PARALLEL)

    async def one(f: dict) -> Outcome:
        async with gate:
            return await pull_one(pool, f, deps, pinned=next((p for p in PINNED if p["slug"] == f["slug"]), None))

    pinned_first = sorted(funders, key=lambda f: f["slug"] not in pinned_slugs)
    outcomes = await asyncio.gather(*(one(f) for f in pinned_first))
    report += [o.line() for o in outcomes]
    closed = await close_expired(pool)
    written = sum(len(o.written) for o in outcomes)
    looks = sum(1 for line in report if "NEEDS A LOOK" in line)
    report.append(f"-- {len(outcomes)} funders read, {written} open calls written, {closed} expired calls closed, "
                  f"{looks} need a look.")
    return report
