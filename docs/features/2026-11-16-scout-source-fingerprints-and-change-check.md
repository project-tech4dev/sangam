# Scout: remember what each source said, and check it for change cheaply

Part of [#411](https://github.com/project-tech4dev/sangam/issues/411) (epic #332). This plan covers the first part
of #411: **source fingerprints, the change check and the partial update.** The queue, the scheduled runner, the
daily budget and the triggers come later; this plan only makes them possible.

**Start lean.** The first version is the smallest thing that answers "did anything Sangam holds change?". It runs on
5–10 funders by hand before anything is added (section 8 lists what waits for that).

## The picture

```
  STEP 1 · FULL PULL                          once per funder · uses the model · ~$2
  ─────────────────────────────────────────────────────────────────────────────────
     Scout reads the funder's ~15 pages and reports
                    │
                    ▼
     For each one, Sangam saves:   the text  +  its fingerprint (hash)  +  the date


  STEP 2 · CHANGE CHECK                       every few weeks · ~$0.01–0.05 per funder
  ─────────────────────────────────────────────────────────────────────────────────
     Fetch → Clean → Hash → Compare with the baseline
                    │
          same hash │ (most pages)            hash differs
                    ▼                               ▼
              nothing to do          Diff old vs new text
                                                    ▼
                                     Evidence check (no model): is each fact's
                                     sentence still on the page?
                                                    ▼
                                     Cheap model (Haiku) reads ONLY the diff and
                                     the facts: does this change anything Sangam
                                     records, or add something it should?
                                                    ▼
                                     no → nothing to do      yes → step 3

     Also: a few searches for new reports, programmes and open calls. A relevant
     new source → step 3


  STEP 3 · PARTIAL UPDATE                     only if step 2 found a change · ~$0.40
  ─────────────────────────────────────────────────────────────────────────────────
     The model reads ONLY the diff (or the new source) plus ONLY the facts
     Sangam took from that page, and answers: keep, update, remove or add
                    │
                    ▼
     Sangam saves the updated research for today, as a draft to review
```

**Why this saves money:** today every refresh is step 1 again ($2 per funder). With this plan most funders stop at
step 2, and only the ones whose facts changed pay for step 3.

## The approach in plain words

**1. A fingerprint is a hash of a page's cleaned text.** `read_page` already strips menus, footers and scripts
(trafilatura) and SHA-256-hashes the text to name the archived file. The same text always gives the same hash; one
changed word gives a different one. Two hashes are compared: equal means the text is identical.

**2. What's missing is memory.** The hash lives only in a file name in Supabase Storage. Postgres knows a research
row read `…/about`, but not *which version* of it. So the first job is one table of page versions, and a column on
`entity_research` saying which versions each run read.

**3. A changed hash is only a question, not an answer.** A footer year changes the hash; so does a changed grant
size. How *much* text changed says nothing about whether it *matters*: "400 organisations" → "500" is a tiny edit,
a 500-word news section is a big one that may matter not at all. So a changed hash leads to a diff, and the diff is
judged on meaning, in two steps:

- **The evidence check (no model).** Every finding already carries the sentence it came from (`evidence`). If that
  sentence is no longer on the page, the fact is **broken**: a real change, whatever the rest of the page did.
- **The relevance check (cheap model).** Haiku reads only the added and removed text and the facts from that page,
  and answers one question: does this change a fact Sangam holds, or add one it has a place for?

**4. Sites misbehave, and a failure isn't a change.** A 403 or a timeout is *unverified*: keep the findings and try
again later. Only a 404 or 410 is *dead*.

**5. New things appear at new URLs.** A new annual report, a new programme page, an open call. So the check also
runs a few searches per funder, on its own domain, and the cheap model says which results are worth reading.

**6. The partial update reads the change, not the site.** The model gets the diff, the broken facts, the judge's
hints and only the findings from that page, and answers keep / update / remove / add (the idea behind Salesforce's
ClaimWriter).

## 1. Goal

**After a full pull, Sangam knows which version of each page and report the research was based on, and can tell,
for a few cents per entity, whether anything it holds about that entity changed since.**

Success, on 5–10 pilot funders:

- Every new `entity_research` row records the snapshots it read, written by the tools that fetched them, not by the
  model.
- `make source-check SLUG=azim-premji-foundation` labels each source `unchanged`, `minor`, `changed`, `unverified`,
  `dead` or `new`, using no model for unchanged pages and only the cheap model for changed ones.
- On the pilot, a person reading every `minor` finds no fact change in it, and every `changed` holds one.

## 2. What is there today

```
Postgres: entity_research                 Supabase Storage: source-archive
┌──────────────────────────────────┐      ┌─────────────────────────────────────────┐
│ slug: azim-premji-foundation     │      │ 3fa91c0b2e7d/a81f…e09c-…-about.md       │
│ researched_on: 2026-11-14        │  ✗   │ 77c2d0e4b1aa/5be3…11d2-annual-2024.pdf  │
│ sources_read: {…/about,          │  no  │   (folder = hash of URL,                │
│                …/annual.pdf}     │ link │    file name starts with hash of text)  │
└──────────────────────────────────┘      └─────────────────────────────────────────┘
```

| Piece | Where | State |
|---|---|---|
| Page cleaning | `read_page` → `trafilatura.extract()` (`ingest/tools/research_tools.py:207`) | Done |
| Content hash | `storage.archive_key()` = `<sha256(url)[:12]>/<sha256(text)>-<name>` (`integrations/storage.py:150`) | Computed, but lives only in a Storage key; no normalising |
| Archived text | `source-archive` bucket, never overwritten (`storage.upload`) | Done: every version kept |
| PDFs | `fetch_document` archives the **bytes** (`research_tools.py:288`) | Done, but the hash is of bytes, not text |
| Promotion | `_shelve` **moves** archived files to `funders/<slug>/…` (`catalog/promote_documents.py:155`) | A stored key goes stale after a move |
| What a run read | `entity_research.sources_read text[]` (`0016_entity_research.sql:23`) | URLs only, written by the model |
| Per-finding source | `FindingBase.source_url` + `evidence` (`research/finding_types.py:147`) | Done: every fact names its page and sentence |
| What the brief uses | `brief.rows_for` + `merge_findings` (`brief.py:532`, `:233`) | **Every** research row for the slug, not just the latest |

## 3. Design

### 3.1 One table and one column (migration `0058_source_snapshots.sql`)

**`source_snapshots`**: one row per distinct version of a URL Sangam has read. Written by the fetching tools.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity PK | |
| `url` | text not null | canonical, as `canonical_url()` returns it |
| `kind` | text | `page` \| `document` |
| `text_hash` | text not null | sha256 of the normalised cleaned text (3.2). Named apart from `documents.content_hash`, which hashes bytes |
| `archive_key` | text | `source-archive` key; NULL when Storage was off or the upload failed |
| `first_seen_at` | timestamptz not null default now() | when this version was first read |
| `last_seen_at` | timestamptz not null default now() | the latest read that still found it |

`UNIQUE (url, text_hash)`, inserted `ON CONFLICT DO UPDATE SET last_seen_at = now()`, so re-reading an unchanged page
updates one row instead of adding one.

**`entity_research.snapshot_ids bigint[]`**: the snapshots this research run read. Written by `save_research`. No
link table: a run reads ~15 sources, and "cited" is already in the findings (`source_url`).

RLS and grants like `entity_research` (`0027_rls.sql`, `0025_table_grants.sql`); `source_snapshots` goes in
`KNOWN_EXCLUDED` (`ask/tools/sql/catalog.py`). `sources_read` stays as it is; the brief, profile page and API read it.

### 3.2 Recording a read (the tools)

```
read_page / fetch_document
  ├─ fetch + clean              (unchanged)
  ├─ storage.upload(...)        (unchanged; returns the key or None)
  └─ record_snapshot(url, kind, text, key)   ← new, one INSERT … ON CONFLICT, returns the id
```

- **The file first, then the row**, so a row never names an archive that isn't there.
- **Normalise, then hash:** Unicode NFC, zero-width characters and soft hyphens removed, whitespace collapsed. Not
  lowercased: a changed capital can change meaning.
- **PDFs hash their text, not their bytes**, so a re-export with new dates or producer isn't a change. That means
  extracting the whole PDF's text at fetch time. A scanned PDF with no text layer hashes its bytes instead.
- **Never raises into the tool**: a failure is logged and the text is still returned, as archiving already is.
- **Private sources are not recorded** (Doc Vault, staff spreadsheets): nothing public to re-fetch.
- **The run remembers what it read.** Tools keep no state between calls and up to 8 researchers run at once, so the
  snapshot ids go on a per-run context variable, set by middleware the same way `run_sources.CURRENT` is
  (`ingest/middleware.py:386`). `record_snapshot` lives in `ingest/reading/`, not `tools/` (R1).
- **Promotion keeps the key right.** When `_shelve` moves an archived file, it updates `source_snapshots.archive_key`
  in the same step, or the check can't load the old text later.

The fetch-and-clean code in `_read_page` and `_fetch_document` first moves to `ingest/reading/fetch.py`, so the check
cleans pages exactly as the researcher did. That move is its own PR (R5). Pin trafilatura's version: an upgrade
changes every hash (section 7).

### 3.3 Linking a save to what it read (`save_research`)

In the same transaction as the `entity_research` upsert, `save_research` writes `snapshot_ids` from the run's context
variable: everything the tools fetched, not the model's list. A cited URL with no snapshot is a finding whose page
was never fetched: worth a log line now and a grader rule later.

### 3.4 The change check

A script, `ingest/refresh/change_check.py`, run by hand as `make source-check SLUG=…` during the pilot.

#### What "the old version" is: the baseline, per URL

The brief merges facts from **every** research row of an entity (`merge_findings`), so the check must too:

- **Sources to check:** the union of URLs across all the entity's research rows that aren't `wrong_entity`.
- **Baseline for each URL:** the snapshot of that URL in the newest such row that read it.

A check records new snapshots but **never moves a baseline**; only a new research row does. So a change found in
January and not yet acted on is still `changed` in February, and small edits that add up are still compared with the
text the facts came from.

| Check | Page text | Compared with | Result |
|---|---|---|---|
| Nov 14, full pull | A | (none) | research links A, **baseline = A** |
| Dec 14 | A | A | unchanged |
| Jan 14 | B | A | changed → refresh |
| Feb 14, refresh not run yet | B | A | **still changed** |
| Feb 15, partial update | B | (none) | new row links B, **baseline = B** |
| Mar 14 | B | B | unchanged |

#### The flow for one source

```
1. Fetch + clean   with the shared fetch.py
     403, 429, timeout, robots/registry refusal, empty text  → UNVERIFIED   keep the facts, retry next time
     404 or 410                                              → DEAD         its facts need a look
     a redirect to the site's home page (soft 404)           → DEAD
2. Hash            sha256(normalised text) == baseline.text_hash
                                                             → UNCHANGED    stop (most sources end here)
3. Diff            load the baseline text by archive_key; paragraph-level diff of baseline vs today
     no archive                                              → CHANGED      can't compare, so assume it did
   Archive and record today's version (file first, then row).
4. Evidence check  (no model) for each finding from this source:
     its evidence is in the baseline text and still in today's  → INTACT
     in the baseline, not in today's                            → BROKEN
     not in the baseline either (paraphrased or derived)        → UNANCHORED
   Any BROKEN                                                 → CHANGED      skip step 5; the update is told which
5. Relevance       (cheap model) diff + this source's findings + the entity's open gaps
                   + the fields the research contract asks for
     meaningful: false                                       → MINOR        reason kept in detail
     meaningful: true, a failed call, or a malformed answer  → CHANGED
```

The evidence check uses `rapidfuzz.fuzz.partial_ratio` ≥ 95 on normalised text, so a sentence moved to another
paragraph is still intact.

**The relevance judge** is `UTILITY_MODEL` (Haiku, low effort), set by `SOURCE_CHECK_JUDGE_MODEL` (default in
`config.py`). It has no tools and returns one structured answer:

```json
{ "meaningful": true, "confidence": "high",
  "reason": "a new programme, 'Teacher Fellowship', with its own eligibility",
  "affected_findings": ["f12"],
  "new_facts": [{"field": "programmes", "excerpt": "In 2026 we launched the Teacher Fellowship ..."}],
  "gaps_it_may_fill": ["how_to_apply"] }
```

The diff is page text, so it's untrusted: the prompt says so, and the answer can only be this shape. It never writes
a finding; it only decides whether step 3 runs, and its hints go to the partial update.

**A worked example: Azim Premji Foundation's `/about` page**

| What happened | Hash | Evidence check | Judge | Status | Update? |
|---|---|---|---|---|---|
| Nothing | same | not run | not run | unchanged | no |
| Footer "© 2025" → "© 2026" | differs | all intact | not meaningful | minor | no |
| "400 organisations" → "500" | differs | 1 broken | not run | changed | yes |
| A new "How to apply" section | differs | all intact | meaningful, fills `how_to_apply` | changed | yes |
| A 500-word news section about an event | differs | all intact | not meaningful | minor | no |
| Site returns 403 | n/a | n/a | n/a | unverified | no |
| Page removed (410) | n/a | n/a | n/a | dead | yes |

#### New sources: reports, programmes and open calls

After the per-source loop, three searches on the funder's own domain and name:

- `"<name>" annual report OR CSR report <current FY>`
- `"<name>" new programme OR initiative OR fellowship`
- `"<name>" call for proposals OR applications open OR grant round`

Each result is dropped if its URL is already among the entity's snapshots, or if its text hash matches one (the same
report at a new URL). What's left goes to the judge as title + snippet, with the same question: is this a source
for a fact Sangam records? Only a yes is `new`. Results from other domains are ignored, so news sites and
aggregators don't flag every funder. Cost: three Tavily calls and one Haiku call.

#### What it writes

One `source_checks` row per source (migration 0059):

| Column | Notes |
|---|---|
| `run_id` | uuid shared by one `make source-check` run |
| `slug`, `url` | |
| `checked_at` | |
| `baseline_snapshot_id` | what it was compared with; NULL for `new` |
| `new_snapshot_id` | today's version, when the hash differed |
| `status` | `unchanged` \| `minor` \| `changed` \| `unverified` \| `dead` \| `new` |
| `findings_intact`, `findings_broken`, `findings_unanchored` | the evidence check's counts |
| `judge` | jsonb, the judge's answer; NULL when not called |
| `detail` | HTTP status, refusal text, or "archive failed" |

And one line per entity:
`azim-premji-foundation: 14 sources · 11 unchanged · 1 minor · 1 changed · 1 unverified · 1 new → refresh`.

**The decision per entity:**

| Result | Decision |
|---|---|
| Only `unchanged`, `minor`, `unverified` | nothing to do |
| Any `changed`, `dead` or `new` | **refresh** (partial update) |
| More than half the sources' hashes changed | **full pull** (likely a redesign); the judge isn't called |

The script decides only; it doesn't run the update. Phase 1's queue will read its result.

### 3.5 The partial update (built after the pilot)

```
changed source …/about                       findings from …/about           judge hints
┌───────────────────────────────┐            ┌──────────────────────────┐    ┌──────────────────────┐
│ - supports over 400 orgs      │            │ f12 "over 400 orgs"  ✗   │    │ fills: how_to_apply  │
│ + supports over 500 orgs      │     +      │ f13 "school education" ✓ │  + │                      │
│ + How to apply: …             │            │ gap how_to_apply         │    │                      │
└───────────────────────────────┘            └──────────────────────────┘    └──────────────────────┘
                                   ▼
                    narrow researcher (RESEARCH_MODEL, medium effort)
                                   ▼
          { keep: [f13], update: [f12 → 500 organisations], add: [how to apply],
            gaps_closed: [how_to_apply] }
```

Input: for each `changed` source, the diff of **baseline** vs today (not the whole page), its findings marked
intact / broken, and the judge's hints; for each `new` source, its text; and the gaps those sources were expected to
fill.

Output: a delta, not a record.

```json
{ "keep": ["f13"], "update": [{"id": "f12", "...new finding"}], "remove": [{"id": "f15", "why": "..."}],
  "add": ["...new findings"], "gaps_closed": [...], "gaps_opened": [...] }
```

The save builds a new `entity_research` row for today with the updated findings and the new `snapshot_ids`.
Results arrive as drafts in Review & save, as the issue says.

Open before building it:

- **A stable id per finding.** Start from `brief.fact_key` (`brief.py:206`).
- **"Remove" must stick.** The brief merges every row, so an older row would bring a removed fact back. The new row
  carries `supersedes: [fact_key, …]`, and `merge_findings` drops a fact a newer row supersedes.
- **A prompt variant** under `ingest/prompts/` and a grader rubric for a delta.

## 4. PRs, in order

| # | PR | Contents | Behaviour change |
|---|---|---|---|
| 1 | Move fetch/clean into `ingest/reading/fetch.py` | `_read_page`, `_fetch_document` cores and the helpers they use; tools call it | None (R5) |
| 2 | Source snapshots | migration 0058 (`source_snapshots`, `entity_research.snapshot_ids`), normalised text hash, full PDF text at fetch, `record_snapshot`, the run's context variable, `save_research` links, `_shelve` updates the key | Every read and save writes rows |
| 3 | Change check | `source_checks` (0059), fetch → hash → diff → evidence check → judge, the three searches, `make source-check`, `rapidfuzz`, `SOURCE_CHECK_JUDGE_MODEL` | New command only |
| — | **Pilot** | full pull on 5–10 funders after PR 2, then `make source-check` on them every week for a month | none |
| 4 | Partial update | prompt, delta save, `supersedes`, Review & save drafts | After the pilot |

Each PR: `make wiki-update`; a CHANGELOG line; ARCHITECTURE.md when a rule changes (PR 2: "what a run read is
recorded by the tools, not the model").

## 5. Tests

- **Hashing (unit):** whitespace, NFC or zero-width differences → same `text_hash`; a changed capital → different;
  two exports of one PDF with new dates → same; a scanned PDF → bytes hash.
- **`record_snapshot` (unit):** same text twice → one row, newer `last_seen_at`; changed text → two rows; a failed
  upload → no row.
- **Run context (unit):** two researchers in parallel each save only their own snapshot ids.
- **`_shelve` (unit):** a moved file's `archive_key` follows it.
- **Baseline (unit):** two rows, the later one narrow → the earlier row's URLs are still checked against their own
  snapshot; A → B (no refresh) → B is `changed` both times; a new row on B makes the next B `unchanged`.
- **Classifier (unit, judge stubbed):** 403 → `unverified`; 410 and soft 404 → `dead`; same hash → `unchanged`
  without loading the archive; a broken finding → `changed` without calling the judge; judge `false` → `minor`; judge
  error → `changed`; no archive → `changed`.
- **Evidence check (unit):** a moved sentence → intact; a changed number → broken; a paraphrase → unanchored.
- **Discovery (unit):** a known URL or a known text hash at a new URL is not `new`; another domain is ignored.
- **Migration (integration):** table, column, RLS and grants exist; `_verify_sql_catalog` still boots.
- **The pilot** is the real test: read every `minor` and `changed` on the 5–10 funders and record in #411 how
  often each was right.

## 6. Not in this plan

- `research_queue`, the scheduled runner, the daily budget cap (phase 1 of #411).
- Triggers from news, open calls and the financial-year calendar (phase 3).
- Backfilling snapshots for research done before PR 2: the pilot funders get a fresh full pull instead.
- Dropping `entity_research.sources_read`.

## 7. Open questions

1. **Local runs with Storage off** have no archive, so a changed hash can only be `changed`. Fine for local?
2. **Robots and the registry can change.** A page readable at research time may be refused now: `unverified`, or
   flag the findings since Sangam may no longer cite it?
3. **A trafilatura upgrade changes every hash.** With the evidence check and judge, that costs one Haiku call per
   page, not a full pull, but it's wasted. Pin the version, and upgrade it deliberately.
4. **How many unanchored findings.** If most `evidence` sentences turn out paraphrased, the evidence check decides
   little and the judge carries everything. The pilot's counts answer this; the fix would be requiring a verbatim
   sentence in the research skills.

## 8. Later, only if the pilot shows a need

Each was in an earlier draft and is left out to keep the first version small. Add one when the pilot shows the
problem it solves.

| Idea | Add it when |
|---|---|
| Metadata hash (`meta`, `meta_hash`: title, page count, dates) | the pilot finds changes the text misses, e.g. a "revised" report with the same text |
| Extractor version and options on each snapshot | trafilatura has to be upgraded or its options changed |
| `HEAD` shortcut for PDFs (ETag, Last-Modified, size) | downloading reports again makes checks too slow or heavy |
| A similarity pre-filter (e.g. ≥ 0.99 → `minor` with no judge) | judge calls on trivial edits cost more than they're worth |
| `source_check_runs` and a per-entity lock | the check runs on a schedule rather than by hand |
| A failure streak (`unverified` many times → skip) | some sites block every check |
| A link table instead of `snapshot_ids` | a query needs more than "which snapshots did this run read" |

## References

Each link is where an idea in this plan came from.

**Change detection (3.4)**

- IOEDR, *Incremental Open-Ended Deep Research with Structured Harness*,
  [arXiv 2610.11566](https://arxiv.org/abs/2610.11566): the split between updating old evidence (the evidence check)
  and discovering new evidence (the searches). Its 0.9 similarity gate was considered and not adopted: similar text
  doesn't mean the same facts.
- Firecrawl, [Change Tracking](https://docs.firecrawl.dev/features/change-tracking): the `new` / `same` /
  `changed` / `removed` statuses; comparing cleaned text, not HTML; the warning that changing extraction options makes
  comparisons unreliable (pin trafilatura).
- Firecrawl, [Monitoring](https://docs.firecrawl.dev/features/monitoring): a judge run only on changed pages against
  a goal, returning `meaningful`, `confidence`, `reason` (the relevance check).
- Firecrawl, [How to monitor a website for changes](https://firecrawl.dev/blog/monitor-website-changes-firecrawl):
  a worked example of a goal-based judge on a real page.

**Fingerprints and records (3.1, 3.2)**

- LangChain, [`langchain_core/indexing/api.py`](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/indexing/api.py):
  writing the data before the record (file first, then row); its `full` cleanup deletes anything not seen in a run,
  the reason a failed fetch is `unverified`, never `dead`.
- LlamaIndex, [`ingestion/pipeline.py`](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/ingestion/pipeline.py):
  matching on content hash across ids (`DUPLICATES_ONLY`), the same idea as "the same report at a new URL is not
  `new`".

**The partial update (3.5)**

- Salesforce ClaimWriter, [`docs/updates.md`](https://github.com/SalesforceAIResearch/claimwriter-deep-research/blob/main/docs/updates.md):
  facts as durable objects with stable ids, so a source change updates only the affected facts.
- Salesforce ClaimWriter, [`claimwriter/perturb/topdown/fact_edit.py`](https://github.com/SalesforceAIResearch/claimwriter-deep-research/blob/main/claimwriter/perturb/topdown/fact_edit.py):
  the per-source fact delta (`replaced` / `removed_ids` / `added`), with the model shown the old and new page and
  the facts taken from it.

**Libraries**

- [RapidFuzz](https://rapidfuzz.github.io/RapidFuzz/): `fuzz.partial_ratio` for the evidence check.
- [Trafilatura](https://trafilatura.readthedocs.io/): the extractor `read_page` already uses.
