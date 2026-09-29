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

## Naming what to research

A run is either source-first — "pull the latest from India CSR" — or subject-first:
`run_import_now(funders="Axis Bank Foundation, SBI Foundation, Tata Trusts")`. A named run
searches every runnable source for each name, and the names run concurrently under the same
`Semaphore(2)` that bounds everything else, because each task holds a pooled connection.

Both are honest questions and they are not the same one. A named run can still come back empty:
the sources are general feeds, so "searched and found nothing" is a real result and the report
says so rather than implying the funder has no CSR spend.

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

---

# Researching many NGOs in one go

## Can subagents do this — and what for

Yes, and the reason is **context, not speed**. A single broad funder run read three PDFs across
twenty tool calls and did not reach its final report; five NGOs in one conversation is strictly
worse, because each one's annual report displaces the last one's findings. `create_deep_agent`
takes `subagents=[…]` with `mode: "isolated"`, which gives each NGO its own context window. Only
the structured result comes back.

What subagents are **not** for: deciding which NGOs to research. That is a list, and a list is a
`for` loop. The fan-out stays deterministic code — the same shape as today's
`(source × funder × year)` — and the subagent is the worker that researches exactly one NGO.

## Why NGO research looks different from funder research

Of 21 registered NGO sources, **four are dispatchable and none has an adapter**. NGO Darpan is
CAPTCHA-gated, Give bars data mining, FCRA / Income Tax / MCA all answer 403 or 503 from outside
India. The NGO's own website and its annual report are `crawl_allowed_check_each_site`.

So NGO research is **research-tool driven, not adapter driven**: `search_public_sources` to find
the site and the annual report, `read_page` and `fetch_document` to read them, with the robots
check happening per host at fetch time. No new adapters are needed. What *is* needed is the data
path, which still does not exist: there is no `OrgRecord`, no `resolve_org`, and no `write_org`,
so NGO research is saved and rendered but never becomes a row in `orgs`.

## Not breaking in between

Six things, each answering a specific way a batch dies halfway:

| Failure | Guard |
|---|---|
| One NGO's site 500s and the batch aborts | `return_exceptions=True` on the gather, and a per-NGO try/except that records the failure as a row |
| One hung fetch stalls everything | `asyncio.wait_for` per NGO — the evals learned this when one request blocked a suite for hours |
| The run dies at NGO 4 of 6 and loses 1–3 | Write results **per NGO**, not at the end. A batch is durable in pieces |
| Re-running repeats work already done | Before researching, check the batch for a completed marker for that NGO and skip it. A re-run resumes |
| Six concurrent researchers exhaust the pool | The existing `Semaphore(2)` — the pool is `max_size=5` and shared with the checkpointer, which writes on every graph step |
| The report says "6 researched" when 2 failed | Per-NGO status in the summary: researched · partial · failed · skipped, each with its reason |

## The markdown and the database

The instinct is to write the file and then parse it back. **Don't.** Parsing prose into rows is
lossy, and the moment someone edits the file the two disagree with no way to tell which is right.

Invert it. The research produces **typed records**, the writer persists them, and the file is
**rendered from the database** — so it cannot contradict the data, and re-rendering costs nothing.

`docs/clients/<ngo>/README.md` therefore has two kinds of content:

- **Generated blocks**, between `<!-- generated:funders -->` markers: the scores, the CSR figures,
  the eligibility checks, the impact chains. Refreshed from the catalog; never hand-edited.
- **Hand-written analysis** outside the markers: the reading that the data does not contain —
  that v2 was never vetted, that the highest-scoring funder is the inactive one. A generator
  cannot write those and should not overwrite them.

## From a finding to a row

A finding used to be a label and a value, both strings, and promotion bridged the gap to a
relational row with regular expressions — sniffing for the word "crore" to decide a scale,
grepping a label for a fiscal year. That is how a figure becomes wrong by a factor of ten
million, which has happened here twice. So the shape is fixed at the source:

1. **`app/ingest/expectations.py`** derives, per concept, the columns a source could state — from
   `app/agent/tools/sql/catalog.py`, the same data the SQL tool allowlists and that
   `verify_against_db()` checks against the live schema at boot. There is no second list to keep.
2. **`research_goals(name, years, entity_kind)`** diffs that against what the catalog already
   holds and returns the gaps. It is the first call of any research run.
3. **`app/ingest/research_records.py`** has one typed model per concept, its fields named for
   that table's columns. A test fails when the two drift.
4. **`save_research`** validates and persists, as `entity_research` with `schema_version = 2`.
5. **`promote_research`** maps fields to columns and writes.

### What promotion writes, and what it will not

Eleven of the twelve concepts have a writer: identity, identifier, csr_year, document, program,
csr_spend, footprint, stated_geography, partner, metric, contact.

**`grant` does not**, and it is not an oversight. `grants.org_id` is `NOT NULL` and there is no
`OrgRecord`, `resolve_org` or `write_org`, so a funded organisation the catalog does not hold
cannot become a grant row. `funder_partners.org_id` is nullable, which is why a named partner
belongs there — and which is the more honest claim anyway, since a partner is not proof that
money changed hands.

**An NGO stays research.** Every table above hangs off `funders`. Promoting an org row would
write an NGO into `funders`, which is worse than not promoting it: a wrong answer wearing a
catalog citation. It is refused with a reason.

Three other refusals, all reported rather than logged:

- **A place that is not an Indian state.** `app/ingest/geography.py` holds the 28 states and 8
  union territories with the spellings reports actually print (Orissa, NCT of Delhi, Pondicherry).
  Districts are created on first sight under their stated state, because there is no offline list
  of 780 to check against; states are not, because a typo that becomes a state row is wrong for
  good. A district always travels with its state: several states have a Bishnupur.
- **A name that resembles one we hold without matching it.** Never merged; a person decides.
- **A v1 finding.** Flat label/value rows still render, with a note, and are re-researched rather
  than migrated.

### Amounts

Every amount is `{value, unit, text}` — the number as printed, the unit, and the source's own
wording kept beside it. `Money.inr` is the only conversion in the codebase, and `to_inr()` reads
the same table for findings that have been through jsonb. The unit is a field, not something
inferred from the text, because inference is exactly what got it wrong before.

### Ordering

Documents are written first, so every fact can cite the report it was read from. Programmes
next, parents before children, because six concepts resolve a `program_name` to a `program_id`
and a programme written afterwards leaves nulls behind it.

## Milestones

**Done.** Schema-derived goals, typed findings, and the funder-side writers, in
`d94dac8`, `bf1dbdb` and what follows them.

**Next — the org data path.** `OrgRecord`, `resolve_org` (identifiers → exact → boilerplate →
trigram → queue, reusing the funder matcher's rules), `write_org`, identifier and credential
writing, and then the `grants` writer that depends on it. *Exit: an NGO researched by hand can be
written, read back, and re-run without duplicating.*

**Then — the batch.** One isolated subagent per NGO, deterministic fan-out, the six guards above.
*Exit: six NGOs where one is deliberately broken — the batch finishes, five are written, the
report names the sixth and why, and a re-run does only the sixth.*
