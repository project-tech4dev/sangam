"""One news pull, end to end (spec section 2, 2a and D15): search, score what is new, group, store, show."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.ingest import runner
from app.ingest.adapters import tavily_news
from app.ingest.adapters.tavily_news import Hit, SearchFailed
from app.ingest.matcher import name_key
from app.ingest.news import store, windows
from app.ingest.news.bars import Bars, topic_visibility, visibility
from app.ingest.news.classify import (
    PROMPT_VERSION,
    EntityVerdict,
    TopicVerdict,
    classify_entity,
    classify_topic,
    write_headline,
)
from app.ingest.news.feeds import Subject, queries_for, scopes_for
from app.ingest.news.group import Candidate, group
from app.ingest.news.links import (
    best_link_rank,
    host,
    is_profile_page,
    is_social,
    post_id_date,
    source_type,
    url_key,
    weak_title,
)
from app.ingest.news.windows import stale_floor, window_days

SOURCE = "tavily_news"
EVERYONE = "all"
# Past the function's 1800 s limit a claimed run that still reads 'running' was killed, never finished.
STALE_CLAIM = timedelta(minutes=35)


class RunRefused(Exception):
    """Not a news run, or one that names nobody: running it would mean the whole Registry, billed."""


class RunBusy(Exception):
    """Another execute already claimed this run."""
TOPIC_OF_SIGNAL = {"regulatory": "fcra", "grant": "csr_funding", "open_call": "csr_funding",
                   "programme_result": "programme", "governance_issue": "governance", "controversy": "governance"}


@dataclass
class Deps:
    search: Any
    entity_model: Any
    topic_model: Any
    group_model: Any
    headline_model: Any
    api_key: str
    bars: Bars
    parallel_searches: int = 4
    parallel_classify: int = 8
    max_classify: int = 2000  # per run; past it the rest wait for the next run, their watermarks held

    @classmethod
    def from_settings(cls, s) -> Deps:
        from app.agent.models import resolve_model

        utility = resolve_model(s.utility_model)
        return cls(search=tavily_news.search, entity_model=utility, topic_model=utility,
                   group_model=resolve_model(s.research_model), headline_model=utility, api_key=s.tavily_api_key,
                   bars=Bars.from_settings(s), parallel_searches=s.news_parallel_searches,
                   parallel_classify=s.news_parallel_classify, max_classify=s.news_max_classify)


@dataclass
class Found:
    """One item classified for one subject, and the link it was stored as."""

    subject: Subject
    hit: Hit
    verdict: Any
    link_id: int
    published_on: date | None
    date_source: str | None


def entity_story_fields(v) -> dict:
    scope = "district" if v.region.district else "state" if v.region.state else "national"
    return {"topic": TOPIC_OF_SIGNAL.get(v.signal_type, "other"), "scope": scope, "sentiment": v.stance,
            "content_kind": v.content_kind, "is_news": v.is_news, "summary": v.summary}


def topic_story_fields(v) -> dict:
    return {"topic": v.topic, "scope": v.scope, "sentiment": v.sentiment, "content_kind": v.content_kind,
            "is_news": v.is_news, "summary": v.summary}


def _key(s: Subject) -> str:
    return f"feed:{s.key}" if s.kind == "feed" else f"{s.kind}:{s.id}"


# ---- the run row ------------------------------------------------------------------------------------------


async def create_run(pool, *, org_ids: list[int] | None, funder_ids: list[int] | None, feeds: list[str],
                     started_by: Any, goal: str | None = None) -> int:
    everyone = org_ids is None and funder_ids is None
    # "Everyone" is written down, never inferred from an empty list: an empty selection must not mean all.
    subjects = [f"feed:{k}" for k in feeds] + (
        [EVERYONE] if everyone else [f"org:{i}" for i in org_ids or []] + [f"funder:{i}" for i in funder_ids or []])
    label = "News: everyone" if everyone else f"News: {len(org_ids or []) + len(funder_ids or [])} chosen"
    if feeds:
        label += " · " + ", ".join(feeds)
    goal = f"{goal} ({label})" if goal else label
    async with pool.connection() as conn:
        # A news run created and never executed, or killed mid-run, would read 'running' for ever.
        await conn.execute(
            "UPDATE ingest_runs SET status = 'failed', finished_at = now(), "
            "notes = coalesce(notes, '') || ' · stopped: never finished' "
            "WHERE requested_sources = %s AND status = 'running' AND coalesce(claimed_at, started_at) < now() - %s",
            ([SOURCE], STALE_CLAIM))
        row = await (await conn.execute(
            "INSERT INTO ingest_runs (requested_sources, subjects, started_by, notes) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            ([SOURCE], subjects, started_by, goal))).fetchone()
    return row["id"]


def _parse(subjects: list[str]) -> tuple[list[int] | None, list[int] | None, list[str]]:
    orgs = [int(x[4:]) for x in subjects if x.startswith("org:")]
    funders = [int(x[7:]) for x in subjects if x.startswith("funder:")]
    feeds = [x[5:] for x in subjects if x.startswith("feed:")]
    if EVERYONE in subjects:
        return None, None, feeds
    if not (orgs or funders or feeds):
        raise RunRefused("this run names nobody; refusing rather than pulling the whole Registry")
    return orgs, funders, feeds


@dataclass(frozen=True)
class Selection:
    """Who a news pull covers: everyone (both id lists None) or named Registry records, and which names matched."""

    org_ids: list[int] | None
    funder_ids: list[int] | None
    feeds: list[str]
    matched: list[str]
    unmatched: list[str]


async def select(pool, names: list[str] | None) -> Selection:
    """No names: everyone with the topic feeds. Names: only Registry records they match, by name or alias."""
    from app.ingest.news.feeds import feeds_for

    if not names:
        return Selection(None, None, feeds_for(everyone=True), [], [])
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            # A hidden record is never pulled (load_subjects), so it must not read as matched either.
            "SELECT 'org' AS kind, id, name, aliases FROM orgs WHERE registry_status IS DISTINCT FROM 'hidden' "
            "UNION ALL SELECT 'funder', id, name, aliases FROM funders "
            "WHERE registry_status IS DISTINCT FROM 'hidden'")).fetchall()
    found: dict[str, dict] = {}
    for n in names:
        hit = next((r for r in rows if name_key(n) in {name_key(x) for x in (r["name"], *(r["aliases"] or []))}),
                   None)
        if hit:
            found[n] = hit
    return Selection([r["id"] for r in found.values() if r["kind"] == "org"],
                     [r["id"] for r in found.values() if r["kind"] == "funder"], [],
                     [found[n]["name"] for n in names if n in found], [n for n in names if n not in found])


async def plan_subjects(pool, *, org_ids: list[int] | None, funder_ids: list[int] | None,
                        feeds: list[str]) -> list[Subject]:
    async with pool.connection() as conn:
        return await store.load_subjects(conn, org_ids=org_ids, funder_ids=funder_ids, feeds=feeds)


async def plan_for(pool, *, org_ids: list[int] | None, funder_ids: list[int] | None,
                   feeds: list[str]) -> windows.NewsPlan:
    """What a pull of these subjects would search and cost: one plan for the card, Scout and the CLI."""
    subjects = await plan_subjects(pool, org_ids=org_ids, funder_ids=funder_ids, feeds=feeds)
    return windows.plan(subjects, today=date.today(), settings=get_settings())


async def run_summary(pool, run_id: int) -> dict:
    async with pool.connection() as conn:
        run = await (await conn.execute(
            "SELECT id, status, notes, subjects, started_at, finished_at FROM ingest_runs WHERE id = %s",
            (run_id,))).fetchone()
        items = await (await conn.execute(
            "SELECT record_kind, status, subject, reason FROM ingest_run_items WHERE run_id = %s ORDER BY id",
            (run_id,))).fetchall()
    return {
        "run_id": run_id, "status": run["status"], "goal": run["notes"], "subjects": run["subjects"],
        "started_at": run["started_at"], "finished_at": run["finished_at"],
        "counts": dict(Counter(f"{i['record_kind']}:{i['status']}" for i in items)),
        "failed": [f"{i['subject']}: {i['reason']}" for i in items if i["status"] == "failed"][:20],
    }


async def _claim(pool, run_id: int) -> bool:
    """Atomically take the run; a claim older than the function's limit was killed and is marked failed."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE ingest_runs SET status = 'failed', finished_at = now(), "
            "notes = coalesce(notes, '') || ' · stopped: ran past the time limit' "
            "WHERE id = %s AND status = 'running' AND claimed_at < now() - %s", (run_id, STALE_CLAIM))
        row = await (await conn.execute(
            "UPDATE ingest_runs SET claimed_at = now() WHERE id = %s AND status = 'running' AND claimed_at IS NULL "
            "RETURNING id", (run_id,))).fetchone()
    return row is not None


async def _finish(pool, run_id: int, status: str, note: str | None) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            # Only a run still running: one swept as stale stays failed rather than contradicting itself.
            "UPDATE ingest_runs SET finished_at = now(), status = %s, notes = concat_ws(' · ', notes, %s::text) "
            "WHERE id = %s AND status = 'running'",
            (status, note, run_id))


# ---- one run ----------------------------------------------------------------------------------------------


async def execute_run(pool, run_id: int, deps: Deps, *, today: date | None = None) -> dict:
    """Run a created run to the end. A run that already ran is not run again; its summary comes back."""
    today = today or date.today()
    async with pool.connection() as conn:
        run = await (await conn.execute(
            "SELECT status, subjects, requested_sources, claimed_at FROM ingest_runs WHERE id = %s",
            (run_id,))).fetchone()
    if run is None:
        raise LookupError(run_id)
    if list(run["requested_sources"]) != [SOURCE]:
        raise RunRefused(f"run {run_id} is not a news run")
    org_ids, funder_ids, feeds = _parse(run["subjects"])
    if run["status"] != "running":
        return await run_summary(pool, run_id)
    if not await _claim(pool, run_id):
        async with pool.connection() as conn:
            now = await (await conn.execute("SELECT status FROM ingest_runs WHERE id = %s", (run_id,))).fetchone()
        if now["status"] != "running":  # it was a stale claim, now marked failed
            return await run_summary(pool, run_id)
        raise RunBusy(f"run {run_id} is already running")
    try:
        async with pool.connection() as conn:
            subjects = await store.load_subjects(conn, org_ids=org_ids, funder_ids=funder_ids, feeds=feeds)
            names = await store.registry_names(conn) if feeds else {}
        failed: set[str] = set()  # a subject with any failure keeps its watermark, so the next run retries it
        hits = await _search_all(pool, run_id, subjects, deps, today, failed)
        if subjects and {_key(s) for s in subjects} <= failed:
            # No key, a bad key or Tavily down: nothing was read, so this must not read as the last pull.
            await _finish(pool, run_id, "failed", "every search failed")
            return await run_summary(pool, run_id)
        await _classify_all(pool, run_id, subjects, hits, names, deps, today, failed)
        await _build_stories(pool, run_id, subjects, deps, today, failed)
        async with pool.connection() as conn:
            for s in subjects:
                if _key(s) not in failed:
                    await store.advance_watch(conn, s, today)
    except BaseException as exc:
        note = "cancelled" if isinstance(exc, asyncio.CancelledError) else f"{type(exc).__name__}: {exc}"
        await _finish(pool, run_id, "failed", note)
        raise
    await _finish(pool, run_id, "finished", None)
    return await run_summary(pool, run_id)


async def _search_all(pool, run_id: int, subjects: list[Subject], deps: Deps, today: date,
                      failed: set[str]) -> dict[str, list[Hit]]:
    """Every query × scope per subject, each over the subject's own window; a newcomer also gets stored links."""
    gate = asyncio.Semaphore(deps.parallel_searches)
    out: dict[str, list[Hit]] = {_key(s): [] for s in subjects}

    async with httpx.AsyncClient() as client:
        async def one(s: Subject, query: str, scope: str, domains):
            async with gate:
                try:
                    return s, await deps.search(client, api_key=deps.api_key, query=query, scope=scope,
                                                days=window_days(s.searched_through, today), domains=domains)
                except Exception as exc:  # noqa: BLE001 - one bad reply fails its subject, not the run
                    return s, exc if isinstance(exc, SearchFailed) else SearchFailed(f"{query!r}: {exc!r}")

        results = await asyncio.gather(*(one(s, q, scope, doms) for s in subjects for q in queries_for(s)
                                         for scope, doms in scopes_for(s)))
    async with pool.connection() as conn:
        for s, res in results:
            if isinstance(res, SearchFailed):
                failed.add(_key(s))
                await runner.record_item(conn, run_id, SOURCE, "news_search", "failed", subject=s.name, reason=str(res))
            else:
                out[_key(s)] += res
        for s in subjects:
            if s.kind != "feed" and s.searched_through is None:
                out[_key(s)] = await store.lookback(conn, s) + out[_key(s)]
    return out


def _hit_date(h: Hit) -> tuple[date | None, str | None]:
    """The date a link carries before anyone reads it: its post ID, else the publisher's date (D10)."""
    if d := post_id_date(h.url):
        return d, "post_id"
    if h.published and not is_social(h.url):
        try:
            return parsedate_to_datetime(h.published).date(), "publisher"
        except (TypeError, ValueError):
            pass
    return None, None


def _date(h: Hit, v) -> tuple[date | None, str | None]:
    """D10: the post ID, the publisher's date, then the date the text gives."""
    d, source = _hit_date(h)
    if d:
        return d, source
    return (v.event_date, "text") if v.event_date else (None, None)


async def _pending(conn, s: Subject, hits: list[Hit], floor: date) -> list[Hit]:
    """Hits not yet scored for this subject, one per URL. Copies under other URLs are kept: grouping joins them."""
    seen, fresh = set(), []
    for h in hits:
        k = url_key(h.url)
        if k in seen or is_profile_page(h.url):  # a profile is about the organisation, never one event
            continue
        seen.add(k)
        d, _ = _hit_date(h)
        if d and d < floor:  # old news Tavily still indexes: not worth a classification
            continue
        fresh.append(h)
    done = await store.scored_urls(conn, [h.url for h in fresh], s, PROMPT_VERSION)
    if done:
        await conn.execute("UPDATE news_links SET last_seen_at = now() WHERE url = ANY(%s)", (list(done),))
    return [h for h in fresh if h.url not in done]


async def _classify_all(pool, run_id: int, subjects: list[Subject], hits: dict[str, list[Hit]],
                        names: dict[str, Subject], deps: Deps, today: date, failed: set[str]) -> None:
    """Score each pair and store it as it lands, so a killed run keeps what it paid for."""
    gate = asyncio.Semaphore(deps.parallel_classify)
    registry = sorted({s.name for s in names.values()})
    budget = [deps.max_classify]
    named: list[tuple[Subject, Hit]] = []

    async def one(s: Subject, h: Hit) -> None:
        if budget[0] <= 0:
            failed.add(_key(s))
            async with pool.connection() as conn:
                await runner.record_item(conn, run_id, SOURCE, "news_link", "refused", subject=s.name, source_url=h.url,
                                   reason=f"over this run's cap of {deps.max_classify} classifications; next run")
            return
        budget[0] -= 1
        async with gate:
            try:
                v = (await classify_topic(deps.topic_model, s.key, h, registry) if s.kind == "feed"
                     else await classify_entity(deps.entity_model, s, h))
            except Exception as exc:  # noqa: BLE001 - a bad reply fails this pair, never the run
                v = exc
        async with pool.connection() as conn:
            if isinstance(v, Exception):
                failed.add(_key(s))
                await runner.record_item(conn, run_id, SOURCE, "news_link", "failed", subject=s.name, source_url=h.url,
                                   reason=f"classification failed: {type(v).__name__}: {str(v)[:200]}")
                return
            published_on, date_source = _date(h, v)
            link_id, status = await store.upsert_link(conn, h, run_id=run_id, content_kind=v.content_kind,
                                                      published_on=published_on, date_source=date_source)
            await store.save_score(conn, link_id, s, PROMPT_VERSION, v)
            await runner.record_item(conn, run_id, SOURCE, "news_link", status, subject=s.name,
                               target_table="news_links", target_id=str(link_id), source_url=h.url)
            # D14: a topic item naming a Registry record is scored for that record too.
            if s.kind == "feed" and v.on_target:
                for n in v.registry_named:
                    who = names.get(name_key(n))
                    if who and (who, h) not in named and not await store.scored(conn, h.url, who, PROMPT_VERSION):
                        named.append((who, h))

    async with pool.connection() as conn:
        todo = [(s, h) for s in subjects
                for h in await _pending(conn, s, hits[_key(s)], stale_floor(s.searched_through, today))]
    await asyncio.gather(*(one(s, h) for s, h in todo))
    await asyncio.gather(*(one(s, h) for s, h in named))


# ---- stories ----------------------------------------------------------------------------------------------


async def _build_stories(pool, run_id: int, subjects: list[Subject], deps: Deps, today: date,
                         failed: set[str]) -> None:
    """From the stored scores, not this run's memory: a story that failed to build is built next run.
    Feeds first, so a D14 entity link finds the topic story already made."""
    for s in sorted(subjects, key=lambda s: s.kind != "feed"):
        try:
            async with pool.connection() as conn:
                rows = await store.unstoried(conn, s, PROMPT_VERSION, listed_match=deps.bars.listed_match,
                                             floor=stale_floor(s.searched_through, today))
            schema = TopicVerdict if s.kind == "feed" else EntityVerdict
            items = [Found(s, Hit(url=r["url"], title=r["original_title"], snippet=r["snippet"] or "",
                                  text=r["snippet"] or "", published=None, query="", scope="stored"),
                           schema.model_validate(r["verdict"]), r["link_id"], r["published_on"], r["date_source"])
                     for r in rows]
            if items:
                await _stories_for(pool, s, items, deps, today)
        except Exception as exc:  # noqa: BLE001 - one subject's stories failing must not stop the others
            failed.add(_key(s))
            async with pool.connection() as conn:
                await runner.record_item(conn, run_id, SOURCE, "news_story", "failed", subject=s.name,
                                   reason=f"{type(exc).__name__}: {str(exc)[:200]}")


async def _stories_for(pool, s: Subject, items: list[Found], deps: Deps, today: date) -> None:
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT id, story_id FROM news_links WHERE id = ANY(%s)",
                                         ([f.link_id for f in items],))).fetchall()
        already = {r["id"]: r["story_id"] for r in rows if r["story_id"]}
        since = today - timedelta(days=window_days(s.searched_through, today) + 7)
        stored = await store.recent_stories(conn, s, since=since)
    # A link another subject already put in a story joins that story; the rest are grouped.
    groups: list[tuple[int | None, list[Found]]] = []
    for story_id in set(already.values()):
        groups.append((story_id, [f for f in items if already.get(f.link_id) == story_id]))
    loose = [f for f in items if f.link_id not in already]
    cands = [Candidate(f"s{r['id']}", str(r["published_on"] or ""), r["host"], r["headline"], r["summary"],
                       r["url"]) for r in stored]
    cands += [Candidate(f"n{i}", str(f.published_on or ""), host(f.hit.url), f.hit.title or "",
                        f.verdict.summary, f.hit.url) for i, f in enumerate(loose)]
    for keys in await group(deps.group_model, _key(s), cands) if loose else []:
        new = [loose[int(k[1:])] for k in keys if k.startswith("n")]
        if new:
            stories = [int(k[1:]) for k in keys if k.startswith("s")]
            groups.append((stories[0] if stories else None, new))
    for story_id, members in groups:
        # The headline is a model call: made before taking a connection, never while holding one.
        headline = None if story_id else await _headline(members, deps)
        async with pool.connection() as conn, conn.transaction():  # a story is written whole or not at all
            await _place_in_story(conn, s, story_id, members, deps, headline)


def _main(members: list[Found]) -> Found:
    return min(members, key=lambda f: (best_link_rank(source_type(f.hit.url, f.verdict.content_kind)),
                                       -f.verdict.match))


async def _headline(members: list[Found], deps: Deps) -> tuple[str | None, bool]:
    """(headline, written by Sangam): the main link's own title, or one written for a weak title (D9)."""
    main = _main(members)
    if not weak_title(main.hit.title, main.hit.url):
        return main.hit.title, False
    try:
        written = await write_headline(deps.headline_model, platform=source_type(main.hit.url, None),
                                       title=main.hit.title, summary=main.verdict.summary)
        return written or None, bool(written)
    except Exception:  # noqa: BLE001 - a headline is a nicety; the summary stands in
        return None, False


async def _new_story(conn, s: Subject, members: list[Found], headline: tuple[str | None, bool]) -> int:
    main = _main(members)
    v, title = main.verdict, main.hit.title
    text, generated = headline
    fields = topic_story_fields(v) if s.kind == "feed" else entity_story_fields(v)
    return await store.create_story(
        conn, headline=text or title or v.summary[:120] or main.hit.url, headline_generated=generated,
        original_headline=title if generated else None, published_on=main.published_on,
        date_source=main.date_source, feed=s.key if s.kind == "feed" else None, source_name=SOURCE,
        fetched_at=datetime.now(UTC), extractor_version=PROMPT_VERSION, **fields)


async def _place_in_story(conn, s: Subject, story_id: int | None, members: list[Found], deps: Deps,
                          headline: tuple[str | None, bool] | None) -> None:
    if story_id is None:
        story_id = await _new_story(conn, s, members, headline or (None, False))
    else:
        await store.touch_story(conn, story_id)
    await store.attach_links(conn, story_id, [f.link_id for f in members])
    await store.set_main_link(conn, story_id)
    best = max(members, key=lambda f: (f.verdict.match, f.verdict.confidence))
    v = best.verdict
    left = await store.tag_places(conn, story_id, state=v.region.state, district=v.region.district)
    if left:
        await conn.execute(
            "UPDATE news_stories SET place_names = ARRAY(SELECT DISTINCT x FROM unnest(place_names || %s) x) "
            "WHERE id = %s", (left, story_id))
    await store.tag_sectors(conn, story_id, list(v.sector_tags))
    b = deps.bars
    story = await (await conn.execute("SELECT is_news, published_on, scope FROM news_stories WHERE id = %s",
                                      (story_id,))).fetchone()
    dated = story["published_on"] is not None
    if s.kind == "feed":
        listed = topic_visibility(v.match, v.confidence, is_news=story["is_news"], dated=dated,
                                  scope=story["scope"], bars=b) == "listed"
        await conn.execute(
            "UPDATE news_stories SET topic_match = greatest(coalesce(topic_match, 0), %s), "
            "topic_confidence = greatest(coalesce(topic_confidence, 0), %s), "
            "visibility = CASE WHEN %s OR visibility = 'listed' THEN 'listed' ELSE 'hidden' END WHERE id = %s",
            (v.match, v.confidence, listed, story_id))
    else:
        await store.upsert_entity_link(
            conn, story_id, s, match=v.match, confidence=v.confidence, stance=v.stance,
            signal_type=v.signal_type,
            visibility=visibility(v.match, v.confidence, sentiment=v.stance, is_news=story["is_news"], bars=b,
                                  dated=dated))
