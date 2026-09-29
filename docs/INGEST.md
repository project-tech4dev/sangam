# Sangam Import: discovering and importing funder data

An agent that finds funder records in permitted sources, matches them against the catalog, and
writes what is safe to write. Separate from Ask Sangam: its own endpoint, its own UI, its own
instructions. v1 is the local database and two funder sources.

## The rule everything else follows from

**The model never writes SQL.** Ask Sangam's safety story is that model-authored SQL is read-only
and re-generated from an AST; an importer that emits `INSERT`s would reverse it. Here the model's
only write-shaped output is a **typed record** — a pydantic object with named fields — and
`ingest/writer.py` performs the upsert with fixed SQL. The model decides what a source says and how
it maps; it cannot decide which table or which row.

```
sources.py      config: what may be read, and on what basis
     ↓  asyncio.gather, Semaphore(2)
adapter          fetch (conditional on content_hash) → raw items
     ↓
extract          one sub-agent per source → typed records
     ↓
matcher.py       identifier → exact name/alias → trigram → queue
     ↓
writer.py        fixed SQL upsert, provenance required     → ingest_run_items
```

## Access rules are config, not comments

Every source carries the rule that governs it and the evidence for it — `access_rule`,
`basis`, `robots_checked_at`. The runner dispatches only `open_api` and `crawl_allowed`;
everything else is reported as **refused**, with the reason, in the run summary. That is what
makes "give.do: terms bar data mining" a row in the report rather than a crawl that should
never have happened.

| Source | Rule | Basis | Yields |
|---|---|---|---|
| India CSR (`indiacsr.in`) | crawl_allowed | robots.txt blocks only `/wp-admin/`; read via the WordPress REST API | funders, `funder_csr_years`, documents |
| GDELT DOC 2.0 (`funders_grants`) | open_api | free public API, cite GDELT | `news_mentions` linked to funders, documents |
| Give (`give.do`) | no_scraping | terms bar data mining | registered and never dispatched — it proves the gate |

Crawl etiquette is in the adapter, not left to the operator: one request at a time per host, a
`Sangam/0.1` user agent, and `documents.content_hash` so a re-run does not re-fetch an unchanged
page.

## Matching, and what "could not be processed" means

Four steps, in order: **fixed identifier** (CIN, CSR-1, PAN) → **exact name or alias**,
case-insensitively → **`pg_trgm similarity()`** above a threshold → **`resolution_queue`**.

A name is never merged into a registry funder automatically unless it passed step 1 or 2. That
rule exists because the Graphiti spike merged Christian Medical College, Vellore into the registry
org Better Life Foundation. Step 3 proposes; a person accepts.

A record is **valid to write** when its source is permitted, every fact carries
`source_url` + `fetched_at` + `as_of`, `fiscal_year` matches the format CHECK, and it resolved to
exactly one funder or is new with no near-miss. Anything else is queued with its reason.

## What a run produces

`ingest_runs` holds one row per run; `ingest_run_items` one row per record, with `status` in
`added | updated | matched | queued | failed` and, for an update, the old and new value. The
summary the agent returns at the end of a run is a query over those two tables, so it is the same
whether you ask during the run, after it, or a week later.

## Where it plugs in

Three insertion points, all additive: a second `add_langgraph_fastapi_endpoint(path="/ingest")`,
a second entry in the CopilotKit runtime's `agents` map, and `frontend/features/ingest/` behind
`/ingest`. Ask Sangam is untouched.
