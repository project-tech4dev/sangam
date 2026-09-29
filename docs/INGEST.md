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

The inventory is **74 sources across four categories** — funder, ngo, rfp, media — in
`backend/app/ingest/data/sources/*.json`. It lives inside the package because the Dockerfile
copies only `app/`, and it is JSON so it can be reviewed by someone who does not write Python.
`sources.py` loads it and runs a `_self_check()` at import that raises on a duplicate key, a
missing category, an unknown yield kind, or a basis short enough to be a verdict rather than
evidence.

A source is a **product, not a host**: `mcacdm.nic.in` carries four. So the gate resolves a host
to the **strictest** rule among its products — otherwise declaration order would decide whether a
crawler runs.

Three states, and they are not the same thing:

| | Count | Meaning |
|---|---|---|
| **pulls** | 2 | permitted *and* an adapter exists — India CSR and GDELT |
| **permitted, not built** | 21 | legally readable, nothing reads it. Not a failure |
| **held** | 51 | its access rule forbids it; the basis says what would unblock it |

Crawl etiquette is in the adapter, not left to the operator: one request at a time per host, a
`Sangam/0.1` user agent, and `documents.content_hash` so a re-run does not re-fetch an unchanged
page.

**A host read but not registered becomes a proposal.** When the research tools read a robots-allowed
host nobody has classified, `ingest_source_proposals` records it with what robots said and how often
it has been seen. That is a note, never a permission: promoting it means adding it to the JSON with
a basis and a robots check, in a pull request.

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

---

# Planning the agent the way the org intelligence was done

The standard is already set: `org-grant-intelligence/hand-vetting/` holds fact-check sheets for
KABIL, BDF and four funders, each built to a fixed checklist with the exact sentence behind every
claim. None of it is code — the discipline lives in the markdown. **Encoding it is the work.**

| What the hand-vetted sheet does | What the importer does today | The change |
|---|---|---|
| **The same checklist every time** — 9 sections per org, 8 per funder — so coverage is comparable across entities | **Article-first**: asks a source what it has and writes whatever falls out | The unit of work becomes *entity + fixed checklist*, held in config: `run_import(funder="Axis Bank Foundation")` |
| Every claim carries **the exact sentence** that supports it, quoted | `notes = "Extracted from: <title>"` | `evidence` on every record — **and code checks the snippet really is a substring of the fetched text.** A figure the model invented cannot be written |
| A fact confirmed by rcrc.in *and* give.do *and* myngos.in is stronger than one seen once | `write_csr_year` upserts on `(funder, fiscal_year)`, so the second source silently overwrites the first | Stop collapsing. Two sources are two rows; agreement raises confidence and disagreement is a finding |
| Three states: ✅ confirmed · ⚠️ **not found, with what was attempted** · lower-confidence, with why | `added / updated / matched / queued / failed / refused` | Add **`not_found`** — a permitted source was read and the fact is not in it — which is not the same as `failed`, where we could not read at all |
| Records the near-miss **and the proof**: KABIL the NGO is not Khanij Bidesh India Limited, the mining PSU | The queue keeps candidates; rejected ones vanish | Keep the rejected candidate and the reason. BASF-is-not-Bata is evidence, not noise |
| Labels inference: *"Inferred from absence of any published district-eligibility list"* | Everything is treated as stated fact | `basis: stated \| inferred`; an inferred value never fills a fact column, only a note |

## The trade-off to decide first

The sheets lean on **give.do** (PAN, 12A, 80G, FCRA, programme history), rcrc.in, myngos.in,
LinkedIn and the funders' own sites. Of those, give.do is `no_scraping` and LinkedIn needs written
approval. **India CSR fills funding size, history and trends and nothing else; GDELT fills none of
the checklist.** So a faithful research pass on today's two permitted sources returns `not_found`
for most sections. That is the honest answer and a thin demo.

The one source class that fills sections 1–5 is **the funder's own website** — `crawl_allowed`
per site, and how Axis was loaded by hand. Adding it is the difference between a checklist that
reports emptiness and one that fills.

**GDELT is unverified.** Every call has failed with 429 over several hours, and a bare query with
no parameters now times out from this network — it is the IP, not the query.

## What changes

| | |
|---|---|
| `records.py` | `evidence` and `basis` on `Provenance`; a validator asserting the snippet appears in the source text |
| `checklist.py` (new) | the 8 funder sections as data: section → target tables → what to ask a source for |
| `sources.py` | the funder-website class, with a per-site robots check before each host |
| `runner.py` | entity-first loop; the report gains per-section coverage |
| `writer.py` | stop collapsing two sources into one row |
| `0012_*.sql` | `evidence` column, `not_found` status, a per-entity coverage view |

**M1 — evidence.** `evidence` + `basis` + the substring check. Exit: a run cannot write a figure
whose quoted snippet is absent from the fetched page, proven by a test that fabricates one.

**M2 — the checklist.** Sections as config, entity-first runs, per-section coverage in the report.
Exit: a run against Axis Bank Foundation reports all 8 sections as filled or `not_found` with a
reason, and the report is comparable to the next funder's.

**M3 — corroboration.** Two sources, two rows; agreement and disagreement surfaced. Exit: the same
FY figure from two sources produces two rows and one "corroborated" line; conflicting figures
produce a finding, not an overwrite.
