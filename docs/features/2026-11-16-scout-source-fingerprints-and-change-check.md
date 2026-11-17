# Scout: remember what each source said, and check it for change without a model

Part of [#411](https://github.com/project-tech4dev/sangam/issues/411) (epic #332). This plan covers the first part
of #411: **source fingerprints, the change check and the partial update.** The queue, the scheduled runner, the
daily budget and the triggers come later; this plan only makes them possible.

## The picture

Three steps. Step 1 happens once per funder. Steps 2 and 3 repeat.

```
  STEP 1 · FULL PULL                          once per funder · uses the model · ~$2
  ─────────────────────────────────────────────────────────────────────────────────
     Scout reads the funder's 15 pages and reports
                    │
                    ▼
     For each one, Sangam saves:   the text  +  its fingerprint  +  the date


  STEP 2 · CHANGE CHECK                       every few weeks · NO model · ~$0.01
  ─────────────────────────────────────────────────────────────────────────────────
     Fetch the same 15 pages again, make a new fingerprint, compare with the old one
                    │
                    ▼
     ┌──────────────────────────┬──────────────────────────┬──────────────────────┐
     │ 13 pages: same           │ 1 page: tiny change      │ 1 page: real change  │
     │                          │ (e.g. footer year)       │ (e.g. new numbers)   │
     │ → nothing to do          │ → nothing to do          │ → go to step 3       │
     └──────────────────────────┴──────────────────────────┴──────────────────────┘
     Also: one web search for a newer annual report. Found one? → go to step 3


  STEP 3 · PARTIAL UPDATE                     only if step 2 found a change · ~$0.40
  ─────────────────────────────────────────────────────────────────────────────────
     The model reads ONLY the changed page (what was added or removed)
     plus ONLY the facts Sangam already took from that page
                    │
                    ▼
     It answers: which facts to keep, update, remove, or add
                    │
                    ▼
     Sangam saves the updated research for today
```

**Why this saves money:** today every refresh is step 1 again ($2 per funder). With this plan, most funders stop
at step 2 ($0.01), and only the ones that changed pay for step 3 ($0.40).

## The approach in plain words

**1. A fingerprint is a hash of a page's cleaned text.** Sangam already computes it. `read_page` strips menus,
footers and scripts (trafilatura), then SHA-256-hashes the text to name the archived file. The same text always
gives the same 64-character hash; one changed word gives a completely different one. Nobody decodes a hash. Two
hashes are compared: equal means the text is identical.

**2. What's missing is memory.** The hash lives only in a file name in Supabase Storage. Postgres knows a research
row read `…/about`, but not *which version* of `…/about`. So the first job is two tables:
- one row per version of every page Sangam has read;
- one row linking each research row to the versions it was based on.

**3. The change check compares the stored fingerprint with today's.** It re-fetches each source, cleans it the same
way, and hashes it. That's cheap: no model, and for most sources the old text is never opened.

**4. A changed hash isn't always a real change.** A footer that says "© 2026" instead of "© 2025" changes the hash
too. So when the hash differs, the check opens the old text and measures how similar the two are (the gate from the
IOEDR paper, arXiv 2610.11566). 90% or more similar counts as *minor*: no model run. Below 90% counts as
*changed*: the entity needs a refresh.
**5. Sites misbehave, and a failure isn't a change.** A 403 or a timeout counts as *unverified*: keep the findings
and try again later. Only a 404 or 410 counts as *dead*.

**6. New reports appear at new URLs.** A funder publishes `annual-report-2025.pdf` beside the old one; it doesn't
replace it. So one web search per funder looks for a newer report as well.

**7. The partial update reads the change, not the site.** Every finding already names its page (`source_url`) and
the sentence it came from (`evidence`). So the model gets the diff of one page and only the findings that came
from it, and answers keep / update / remove / add (the idea behind Salesforce's ClaimWriter).

### Why this doesn't get heavy

| Worry | Answer |
|---|---|
| Storing all that text | Already happens today. Unchanged pages add nothing: the file name contains the hash, so an identical copy gets the same name and is not stored again. |
| Comparing text every night | Most checks compare two 64-character hashes. Old text is loaded only for the few sources whose hash changed. |
| Re-downloading 30 MB annual reports | PDFs get a `HEAD` request first (ETag, Last-Modified, size). They're downloaded only if those changed. |
| A redesigned site | If more than half an entity's sources changed, it's sent to a full pull instead. |

## 1. Goal

**After a full pull, Sangam knows exactly which version of each page and report the research was based on, and can
tell, for about $0.01 per entity and no model, which of those sources changed since.**

Success:

- Every `entity_research` row links to the sources it was read from, each with a content hash and a fetch date,
  recorded by the tools that fetched them rather than by the model.
- `make source-check SLUG=azim-premji-foundation` re-fetches those sources and labels each one `unchanged`, `minor`,
  `changed`, `unverified`, `dead` or `new`, with no model call.
- A partial-update researcher can be given only the changed sources, their diff, and the findings that cite them.

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
| Page cleaning | `read_page` → `trafilatura.extract()` (`ingest/tools/research_tools.py:207`) | Done: hashes will be of main text, not HTML |
| Content hash | `storage.archive_key()` = `<sha256(url)[:12]>/<sha256(text)>-<name>` (`integrations/storage.py:150`) | Computed, but lives only in a Storage key |
| Archived text | `source-archive` bucket, never overwritten (`storage.upload`, no `replace`) | Done: every version kept |
| PDFs | `fetch_document` archives the bytes the same way (`research_tools.py:288`) | Done |
| What a run read | `entity_research.sources_read text[]` (`0016_entity_research.sql:23`) | **URLs only**, and written by the model in `save_research`, not by the tools |
| Per-finding source | `FindingBase.source_url` + `evidence` (`research/finding_types.py:143`) | Done: every fact already names its page |
| Version a run used | `storage.archived_key()` returns the **newest** version only (`storage.py:465`) | **Missing** |

Three gaps:

1. No hash or fetch date per URL in the database.
2. `sources_read` is the model's own list: a page it forgot is lost, a page it lists but never read is accepted.
3. Nothing records which archived version a research run was based on.

## 3. Design

### 3.1 Two new tables (migration `0058_source_snapshots.sql`)

How they relate:

```
entity_research (exists)         entity_research_sources (new)            source_snapshots (new)
┌─────────────────────┐          ┌──────────────────────────────┐          ┌────────────────────────────┐
│ id 812              │──1:many─►│ research_id 812              │          │ id 5501                    │
│ slug azim-premji-…  │          │ url …/about                  │─many:1──►│ url …/about                │
│ researched_on 11-14 │          │ snapshot_id 5501             │          │ content_hash a81f…e09c     │
│ findings [...]      │          │ cited true                   │          │ archive_key 3fa9…/a81f…md  │
└─────────────────────┘          ├──────────────────────────────┤          │ first_seen_at 2026-11-14   │
                                 │ research_id 812              │          ├────────────────────────────┤
                                 │ url …/annual-2024.pdf        │─────────►│ id 5502  …/annual-2024.pdf │
                                 │ snapshot_id 5502             │          │ content_hash 5be3…11d2     │
                                 │ cited true                   │          │ http_etag "9f2c…"          │
                                 └──────────────────────────────┘          └────────────────────────────┘

Written by:                      save_research (3.3)                       read_page / fetch_document (3.2)
```

**`source_snapshots`**: one row per distinct version of a URL Sangam has read. Written by the fetching tools.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity PK | |
| `url` | text not null | canonical, as `canonical_url()` returns it |
| `kind` | text | `page` \| `document` |
| `content_hash` | text not null | sha256 of the cleaned text, for pages **and** documents (see 3.2.1) |
| `bytes_hash` | text | sha256 of the raw bytes (documents only); names the archived file, never decides a change |
| `meta` | jsonb | the normalised metadata (3.2.1) |
| `meta_hash` | text | sha256 of `meta`, so a metadata change is seen without diffing JSON |
| `archive_key` | text | `source-archive` key; NULL when Storage was off or the upload failed |
| `byte_size` | int | |
| `extractor` | text not null | the extractor's version **and its options**, e.g. `trafilatura-2.0/plain/precision/tables`; changing either changes every hash, so the check compares like with like |
| `http_etag` | text | from the response, for the cheap PDF check |
| `http_last_modified` | text | |
| `first_seen_at` | timestamptz not null default now() | when this version was first read; never updated |
| `last_seen_at` | timestamptz not null default now() | the latest read that still found this version |

`UNIQUE (url, content_hash, extractor)`, inserted `ON CONFLICT DO UPDATE SET last_seen_at = now()`, so re-reading
an unchanged page updates one row instead of adding one. Two timestamps rather than one `fetched_at`: a page that goes
A → B → A keeps A's first date, so the history still shows A came first. Index on `(url, last_seen_at DESC)`.

**`entity_research_sources`**: which snapshot each research row was based on. Written by `save_research`.

| Column | Type | Notes |
|---|---|---|
| `research_id` | bigint FK `entity_research(id)` ON DELETE CASCADE | |
| `url` | text not null | |
| `snapshot_id` | bigint FK `source_snapshots(id)` NULL | NULL = listed or cited, but no fetch on record |
| `cited` | bool not null | true when at least one finding's `source_url` is this URL |

PK `(research_id, url)`.

Both tables: RLS on and grants like `entity_research` (`0027_rls.sql`, `0025_table_grants.sql`); add both to
`KNOWN_EXCLUDED` in `ask/tools/sql/catalog.py`. Ask does not need them, and adding a table to the catalog is a
security decision this plan does not make.

`entity_research.sources_read` stays as it is for now: the brief, the profile page and the API read it
(`brief.py:475`, `profile_facts.py:184`, `routes/ingest.py:202`). Dropping it is a later cleanup.

### 3.2 Recording a read (the tools)

```
read_page / fetch_document
  ├─ fetch + clean              (unchanged)
  ├─ storage.upload(...)        (unchanged; returns the key or None)
  └─ record_snapshot(url, kind, data, key, extractor, response headers)   ← new, one INSERT … ON CONFLICT
```

**The file first, then the row.** `record_snapshot` runs only after `storage.upload` has returned, so a row never
names an archive that isn't there. (LangChain's indexing API orders its writes the same way for the same reason.)

**Normalise, then hash.** `content_hash` is the sha256 of a lightly normalised copy of the cleaned text, so a change
that isn't one doesn't change the hash:

- Unicode NFC;
- zero-width characters and soft hyphens removed;
- every run of whitespace collapsed to one space, ends trimmed.

Not lowercased and not reordered: a changed capital or a moved line can change meaning. The archive still stores the
text as read, and its file name still uses the hash of the raw text, so `content_hash` is not the hash in the file
name. They are separate on purpose.

The fetch-and-clean code in `_read_page` and `_fetch_document` first moves to a shared reading module, say
`ingest/reading/fetch.py`. The change check (3.4) must clean pages **exactly** the way the researcher did, and R1
forbids a script from importing `tools/`. That move is its own PR (R5): extraction only, no behaviour change.

`record_snapshot` never raises into the tool: a failure is logged and the text is still returned, the same "silent
like archiving" rule the tools already follow. It runs on the owner pool, as the rest of Import does.

Not recorded: private sources (`is_private_source`: Doc Vault and staff spreadsheets). They are files, not public
pages, so there is nothing to re-fetch; the change check skips them.

`record_snapshot` returns the snapshot id, and the tool keeps it on the run (with the URL) so `save_research` can
link exactly what this run read (3.3).

#### 3.2.1 Content hash vs metadata hash

A file's bytes carry metadata as well as text: a PDF's producer, creation and modification dates, XMP block and
document ID; a page's `<title>`, meta description and `og:updated_time`. Re-exporting the same annual report gives new
bytes and so a new bytes hash, while not one word of the report changed. Hashing bytes would call that `changed` and
spend a model run on nothing.

So every source gets two fingerprints, kept apart:

| Fingerprint | Hashes | Decides a change? | Used for |
|---|---|---|---|
| `content_hash` | the cleaned text (pages: trafilatura; PDFs: the extracted text, whitespace normalised) | **Yes** | the change check |
| `meta_hash` | a small normalised `meta` object (below) | No, on its own | identifying, filtering and finding sources |

`meta` holds only fields that say something about the document, with volatile ones dropped:

- **Pages:** `title`, `description`, `canonical`, `lang`, `published`/`modified` (from `article:*` or `og:updated_time`).
- **Documents:** `title`, `author`, `subject`, `page_count`, the PDF's own `creation_date`; plus `content_type` and
  `content_length` from the response.
- **Dropped:** the PDF's `ModDate`, `Producer` and document `ID`, and anything a CMS rewrites on every request
  (cache-busters, CSRF tokens, timestamps). These change on every export and would make `meta_hash` change every time.

**`meta_hash` is the hash of one fixed serialisation.** The same metadata must always give the same hash, whatever
order the fields arrived in:

```python
canonical = json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
meta_hash = sha256(canonical.encode("utf-8")).hexdigest()
```

Before that, every value is normalised: strings NFC and trimmed, dates as ISO `YYYY-MM-DD`, numbers as numbers (not
`"42"`), and keys with no value left out rather than stored as `null` or `""`. `{"title": "AR", "page_count": 42}` and
`{"page_count": 42, "title": "AR"}` then hash the same. (LangChain's indexing API serialises metadata with
`sort_keys=True` for the same reason.)

Why keep metadata at all if it doesn't decide a change:

- **Identifying a document.** A report whose `title` changes from "Annual Report 2024" to "Annual Report 2024
  (revised)", or whose `page_count` changes, is a strong hint even when the text diff is small. The check uses it to
  promote a `minor` to `changed` (3.4, step 6).
- **Filtering and finding sources.** `meta.title`, `published` and `page_count` let the new-report search (3.4)
  recognise "same report, re-hosted at a new URL" (same `content_hash`, different `url`) instead of counting it as a
  `new` source, and let a later screen sort or filter a funder's sources by date or type without opening them.
- **A cheap explanation.** "Only the metadata changed" goes in `source_checks.detail`, so a person reading the
  check output knows why a changed bytes hash led to no refresh.

`bytes_hash` stays because the archive key and the PDF `HEAD` shortcut are about the file, not its text.

### 3.3 Linking a save to what it read (`save_research`)

In the same transaction as the `entity_research` upsert (`research_tools.py:400`):

```
urls = set(findings.sources_read) ∪ {f.source_url for f in findings.findings}   (minus private sources)
for url in urls:
    snapshot = the snapshot THIS run recorded for url (3.2), else NULL
    insert entity_research_sources(research_id, url, snapshot.id or NULL, cited = url in finding urls)
```

On the `ON CONFLICT (slug, researched_on)` replace path, delete the row's old links first.

Link the snapshot this run fetched, not "the newest for this URL". A change check can record a newer snapshot
between a researcher's read and its save; "newest" would then link the research to text it never saw.

A side benefit: a cited URL with `snapshot_id IS NULL` is a finding whose page Sangam never fetched. That's worth a
log line now and a grader rule later.

### 3.4 The change check (no model)

A pure classifier plus a script: `ingest/research/change_check.py` (or `ingest/refresh/`), run as
`make source-check [SLUG=…]`.

**One check per entity at a time.** The script takes `pg_try_advisory_lock` on the entity's slug before it starts and
skips the entity if the lock is held, so two overlapping runs can't record the same snapshots twice. A skipped entity
is logged as `skipped: already running`, like Firecrawl's `skipped_overlap`.

#### What "the old version" is: the baseline

Each source is compared with its **baseline**: the snapshot linked to the entity's latest `entity_research` row
(`entity_research_sources.snapshot_id`), the version the current facts were taken from. Not the newest snapshot.

A check records newer snapshots but **never moves the baseline**; only a new research row (a full pull or a partial
update) does. The newest snapshot is a shortcut only: if today's hash equals it and it equals the baseline, the source
is `unchanged`.

| Check | Page text | Compared with | Result |
|---|---|---|---|
| Nov 14, full pull | A | (none) | snapshot A; research links to A, **baseline = A** |
| Dec 14 | A | A | unchanged |
| Jan 14 | B | A | changed → refresh |
| Feb 14, refresh not run yet | B | A | **still changed** |
| Feb 15, partial update | B | (none) | new research row links to B, **baseline = B** |
| Mar 14 | B | B | unchanged |

Why not the newest snapshot:

- **A change would be lost.** The queue comes later, so a refresh may not run right after a check. Jan finds A → B and
  records B; compared with the newest, Feb's B vs B says `unchanged` and the refresh is never asked for again.
- **Small edits would add up unseen.** Five per cent changes each month all pass the 0.9 gate one by one (Nov→Dec,
  Dec→Jan, Jan→Feb), while Feb vs Nov is ~85% and a real change. Against the baseline, the drift is caught once it
  passes 10%.

For one source, the check asks up to four questions, cheapest first, and stops at the first answer:

```
  Q1. Could we fetch it?
        403, timeout, blocked page   →  UNVERIFIED   keep the old facts, try again next time
        404 or 410 (page is gone)    →  DEAD         its facts need a look
        yes                          →  go to Q2

  Q2. Is the fingerprint the same as last time?
        yes                          →  UNCHANGED    done (most pages stop here)
        no                           →  go to Q3

  Q3. Do we still have the old text?
        no                           →  CHANGED      can't compare, so assume it changed
        yes                          →  go to Q4

  Q4. Is the new text at least 90% the same as the old?
        yes                          →  MINOR        e.g. only the footer year changed; no model
        no                           →  CHANGED      a real edit; the funder needs step 3

  (For a PDF, Q1 starts with a HEAD request: if the server says the file is the same
   size and version as before, it's UNCHANGED without downloading it.)
```

The same steps, as the code will run them:

```
1. kind = document:
     HEAD the URL (through guarded_client, after check_url)
     same ETag / Last-Modified / Content-Length as stored  → unchanged          stop
     otherwise download, hash, continue at step 3
2. kind = page:
     fetch + clean with the shared fetch.py, same extractor     (no archive yet)
3. fetch refused by robots / registry, 403, 429, timeout     → unverified       stop, keep the findings
   404 or 410                                                  → dead           stop, flag the findings
   empty text, or a text under MIN_TEXT                        → unverified     (block page or JS shell)
4. extractor differs from the baseline's                     → skip the hash, go to step 5
                                                                 (a new trafilatura changes every hash; the archive
                                                                  holds cleaned text, so the old page can't be re-cleaned)
   sha256(new text) == baseline.content_hash                  → unchanged       stop   ← most sources end here;
                                                                                         the old text is never read
5. load the baseline's text from source-archive by archive_key
     no archive_key                                            → changed        (can't compare; assume it did)
     similarity(old, new) >= 0.9                               → minor
     otherwise                                                 → changed
6. metadata (3.2.1), only when step 5 said minor:
     title changed, or page_count changed                      → changed        detail "metadata: <field>"
     meta_hash differs otherwise                               → minor          detail "metadata only"
```

Every new snapshot from steps 5–6 is archived, then recorded (file first, then row; 3.2), `minor` included.
Storage dedups identical text, so it costs nothing, and a snapshot with no archive can never be diffed later. If the
upload fails, the `source_checks` row is still written, with `new_snapshot_id` NULL and `detail` "archive failed".

A document whose bytes hash changed but whose `content_hash` didn't (a re-export, new PDF producer or dates) ends at
step 4 as `unchanged`; the new `bytes_hash` and `meta` are recorded on a new snapshot only if `meta_hash` changed.

`similarity` is a character ratio, the gate IOEDR uses (τ = 0.9). Use `rapidfuzz.fuzz.ratio` (new dependency, fast
on long text) rather than `difflib.SequenceMatcher`, which is quadratic on a 50 KB page. 0.9 is a starting value;
section 5 says how to tune it.

**A worked example: Azim Premji Foundation's `/about` page**

| What happened by April | Hash | Similarity | Status | Model run? |
|---|---|---|---|---|
| Nothing | same | not computed | unchanged | no |
| Footer "© 2025" → "© 2026" | differs | 99.9% | minor | no |
| "400 organisations" → "500", plus a new "How to apply" section | differs | ~82% | changed | yes |
| A new 500-word news section about an event | differs | ~70% | changed | yes, though nothing Sangam holds changed |
| Site returns 403 | n/a | n/a | unverified | no |
| Page removed (410) | n/a | n/a | dead | yes |

Two cases page similarity gets wrong are known and left as they are: a long news section added (row 4, a model run
for nothing) and a single number changed in a long page (99.8% similar, `minor`, a stale fact kept). Section 8 has two
options for them, to weigh once the check has run on real data.

**New evidence: one search per funder.** After the per-source loop, one search query, e.g.
`"<canonical name>" annual report OR CSR report <current FY>`. Any PDF result whose URL isn't among the entity's
sources is a **new source** and marks the entity as needing a refresh. This is the issue's "one search for a newer
annual report". Cost: one Tavily call. A result whose `content_hash` matches a source already held is the same report
at a new URL: recorded as a snapshot of the new URL, not `new`.

**What it writes.** A `source_checks` row per source (migration 0059, in PR 3):

| Column | Notes |
|---|---|
| `run_id` | the check run (below) |
| `snapshot_id` | the baseline compared against |
| `checked_at` | |
| `status` | `unchanged` \| `minor` \| `changed` \| `unverified` \| `dead` \| `new` |
| `new_snapshot_id` | when `minor` or `changed`; NULL when the archive upload failed |
| `similarity` | numeric, NULL when not computed |
| `detail` | HTTP status, refusal text, or "metadata only" |

And one `source_check_runs` row per run: `id`, `started_at`, `finished_at`, `status` (`running` \| `complete` \|
`partial` \| `failed`), and the counts. A run that dies leaves `running` or `partial`, which is how the next run, and
anyone reading the table, knows its results are incomplete.

Plus one line per entity in the script's output:
`azim-premji-foundation: 14 sources · 11 unchanged · 1 minor · 1 changed · 1 unverified · 1 new report → refresh`.

**The decision per entity:**

| Result | Decision |
|---|---|
| Not every source has a row in this run (timed out, crashed) | **incomplete**: no decision; the next run checks it again |
| Only `unchanged`, `minor`, `unverified` | nothing to do |
| Any `changed`, `dead` or `new` | **refresh** (partial update) |
| More than half the sources `changed` | **full pull** (likely a redesign) |
| The same URL `unverified` several checks in a row | counted from `source_checks`, reset by the next successful fetch, so a site that always blocks can be skipped |

The script decides only; it doesn't queue or run anything. Phase 1's queue will read its result.

### 3.5 The partial update (design only; built after 3.1–3.4 have run on real data)

```
changed source …/about                       findings whose source_url = …/about
┌───────────────────────────────┐            ┌───────────────────────────────────────┐
│ - supports over 400 orgs      │            │ f12  "supports over 400 organisations"│
│ + supports over 500 orgs      │     +      │ f13  "focus: school education"        │
│ + How to apply: …             │            │ gap  how_to_apply: not_stated         │
└───────────────────────────────┘            └───────────────────────────────────────┘
                    │                                         │
                    └──────────────┬──────────────────────────┘
                                   ▼
                    narrow researcher (RESEARCH_MODEL, medium effort)
                                   ▼
          { keep: [f13], update: [f12 → 500 organisations], add: [how to apply],
            gaps_closed: [how_to_apply] }
```

Modelled on ClaimWriter's fact delta (Salesforce, `claimwriter/perturb/topdown/fact_edit.py`). Scout already stores
findings the way it needs: each with a `source_url` and the `evidence` sentence.

Input to a narrow researcher:

- for each `changed` source: a unified diff of the **baseline** vs today's text (from `source-archive`), not the
  whole page. Not the newest snapshot vs today: that would hide every edit made between the baseline and the last
  check, and the findings from those edits would stay stale;
- for each `new` source: its text, read with the normal tools;
- the findings whose `source_url` is one of those sources, each with an id;
- the gaps those sources were expected to fill.

Output: a delta, not a record.

```json
{ "keep": ["f12", "f13"], "update": [{"id": "f14", "...new finding"}], "remove": [{"id": "f15", "why": "..."}],
  "add": ["...new findings"], "gaps_closed": [...], "gaps_opened": [...] }
```

The save builds a new `entity_research` row for today: findings from unchanged sources copied as they are, the
delta applied to the rest, and links (3.3) to the new snapshots. History survives because rows are per day
(`UNIQUE (slug, researched_on)`).

Open before building it:

- **Findings have no stable id.** Use a hash of `source_url + evidence` for now, or add an `id` to `FindingBase`.
- **A prompt variant** under `ingest/prompts/` and a grader rubric for a delta rather than a full record.
- **Results arrive as drafts** in Review & save, as the issue says, so this needs no auto-promote.

## 4. PRs, in order

| # | PR | Contents | Behaviour change |
|---|---|---|---|
| 1 | Move fetch/clean into `ingest/reading/fetch.py` | `_read_page`, `_fetch_document` cores, `page_name`; tools call it | None (R5) |
| 2 | Source snapshots | migration 0058 (two tables, RLS, grants), `record_snapshot`, `save_research` links, `KNOWN_EXCLUDED` | Every read and save writes rows |
| 3 | Change check | `source_checks` and `source_check_runs` (0059), classifier, per-entity lock, `make source-check`, `rapidfuzz` | New command only |
| 4 | Partial update | prompt, delta save, Review & save drafts | After 3 has run on real funders |

Each PR: `make wiki-update`; a CHANGELOG line; ARCHITECTURE.md when a rule changes (PR 2: "what a run read is
recorded by the tools, not the model").

## 5. Tests

- **Classifier (unit, pure):** a table of (stored hash, new text, old text, HTTP status) → status. Includes footer
  year edit → `minor`, new paragraph → `changed`, 403 → `unverified`, 410 → `dead`, empty 200 → `unverified`,
  missing archive → `changed`.
  Also: extractor differs from the baseline → hash skipped, similarity decides; same text with new PDF
  producer/dates → `unchanged`; title or page count change on a `minor` → `changed`.
- **Hashing (unit, pure):** text differing only in whitespace, NFC form or zero-width characters → same
  `content_hash`; a changed capital → different. `meta` with keys in a different order, or `42` vs `"42"`, or a key
  `null` vs absent → same `meta_hash`. Extractor options change → hash skipped, similarity decides.
- **Write order (unit):** an upload that fails records no snapshot row; the `source_checks` row says "archive failed".
- **Runs (unit):** a run stopped after 9 of 15 sources leaves the entity `incomplete`, not "nothing to do"; a second
  run on an entity whose lock is held skips it.
- **Baseline (unit):** A (research) → B (check, no refresh) → B (check) is `changed` both times; five steps of 95%
  each end `changed` once the total drift passes 10%; a new research row on B makes the next B `unchanged`.
- **`record_snapshot` (unit):** same text twice → one row, newer `last_seen_at`, same `first_seen_at`; changed text
  → two rows; A → B → A keeps A's `first_seen_at`.
- **Metadata (unit):** `meta` drops `ModDate`, `Producer` and the document `ID`, so two exports of one PDF have the
  same `meta_hash`.
- **`save_research` links (unit, repositories monkeypatched):** cited vs listed-only URLs; a cited URL with no fetch
  → `snapshot_id` NULL; replace path drops old links; a snapshot recorded by a check after the run's read is not the
  one linked.
- **Migration (integration):** tables, RLS and grants exist; `_verify_sql_catalog` still boots.
- **Tune 0.9 on real data:** run `make source-check` on the 25 funders from #410 a week apart, read every `minor`
  and `changed`, and move the threshold until `minor` holds no real fact change. Record the result in #411.
  The same reading gives the numbers section 8 needs to decide on its two options.

## 6. Not in this plan

- `research_queue`, the scheduled runner, the daily budget cap, cost per run (phase 1 of #411).
- Triggers from news, open calls and the financial-year calendar (phase 3).
- Near-duplicate hashing (SimHash). The 0.9 ratio covers the same need until it proves too slow or too noisy.
- Dropping `entity_research.sources_read`.
- The evidence check and the judge: options only, in section 8.

## 7. Open questions

1. **Local runs with Storage off** write snapshots with `archive_key` NULL, so step 5 can only say `changed`.
   Acceptable for local, or should the check refuse to run without Storage?
2. **Robots and the source registry can change.** A URL readable at research time may be refused now. The plan says
   `unverified`; should it instead flag the findings, since Sangam may no longer be allowed to cite that page?
3. **Where the check runs.** Fetching 1,500 × ~15 sources is ~20k requests: fine for a nightly job, not for a
   Vercel function. It runs wherever phase 1's runner runs.
4. **Which metadata fields promote a `minor`.** The plan starts with `title` and `page_count`. Tune it with the 0.9
   threshold on the #410 funders: if a promoted `minor` never turns out to hold a real fact change, drop the field.
5. **Existing archives have no metadata.** Snapshots from before PR 2 get `meta` NULL, so step 6 skips them until
   the next full pull records it.

## 8. Options to think about (not part of this plan)

Two ideas came up while reviewing the change check. Neither is in the PRs above. They are written down so the
decision can be made later, on real data from `make source-check`, rather than guessed now.

**Why they are left out for now.**

- **The evidence check** fuzzy-searches every finding's sentence in the old and new page. That is real work on
  every changed page, and its value depends on `evidence` being verbatim, which nothing enforces today. If most
  findings turn out paraphrased, it costs time and decides little.
- **The judge** only saves money when a changed page turns out to hold nothing new. If most changed pages do need
  research anyway, the judge is a cost on top of the $0.40 update, not instead of it.

**How to decide.** After PR 3 has run on the 25 funders from #410 for a few weeks, count from `source_checks`:
how many `changed` pages led to a partial update that changed nothing, and how many `minor` pages hid a real fact
change. If the first number is high, the judge pays for itself. If the second is, the evidence check does.

### 8.1 Option: the evidence check (no model)

A page can change a lot while every fact Sangam took from it stays true, and change by one number while a fact
becomes false. Page similarity measures the page; this check would measure the facts. If adopted, it runs after
step 5 loads the baseline text, before the similarity test.

```
for each finding f whose source_url is this source:
    in_old = partial_ratio(normalise(f.evidence), baseline text) >= 95
    if not in_old:   f is UNANCHORED   (its sentence was paraphrased or derived; this check can't use it)
    else:            f is INTACT if partial_ratio(normalise(f.evidence), new text) >= 95, else BROKEN
```

- `rapidfuzz.fuzz.partial_ratio` finds the best-matching stretch of the page, so a sentence moved to another
  paragraph is still intact. `normalise` is the same as for `content_hash` (3.2).
- Anchoring against the **old** text first matters: `evidence` is described as "the sentence from the source", but
  nothing checks that it is verbatim, and `derived` or `inferred` findings may not quote at all. A finding whose
  sentence isn't in the baseline either tells us nothing, so it is left to page similarity.
- A **broken** finding is the strongest signal the check has: `changed`, and the partial update is told exactly
  which findings to look at.
- It would add three counts to `source_checks`: `findings_intact`, `findings_broken`, `findings_unanchored`.

The same three counts, summed across the #410 funders, say how much the check can be trusted. If most findings are
unanchored, the save contract should require a verbatim `evidence` sentence; that is a later change to the research
skills, not this plan.

### 8.2 Option: a cheap judge before the partial update

With the evidence check (8.1) in place, one case is left open: the page changed a lot, but every fact is intact. A new 500-word news section looks
like this. No old fact is wrong, but the added text **might** hold a new fact worth taking (a new programme, a new
grant size, an application window) or might be news Sangam doesn't record. Telling those apart takes reading, so a
small model reads it before the $0.40 update is spent.

The judge is `UTILITY_MODEL` (Haiku, low effort), set by `SOURCE_CHECK_JUDGE_MODEL` (default in `config.py`; `off`
turns it off). It is given:

- the **added and removed text** from a paragraph-level diff of baseline vs today;
- the **findings** from this source (field and value, one line each);
- the entity's **open gaps** (`entity_research.gaps`);
- the **fields the research contract asks for** for this entity kind (`research/contract.py`), so "new fact" means a
  fact Sangam has a place for.

It answers one structured question, "does this change add or change a fact for any of these fields?":

```json
{ "meaningful": true, "confidence": "high",
  "reason": "a new programme, 'Teacher Fellowship', with its own eligibility",
  "new_facts": [{"field": "programmes", "excerpt": "In 2026 we launched the Teacher Fellowship ..."}],
  "gaps_it_may_fill": ["how_to_apply"] }
```

`meaningful: false` makes the source `minor` and the reason goes into `detail`. `meaningful: true` makes it
`changed`, and `new_facts` and `gaps_it_may_fill` go to the partial update as hints, so the researcher reads the
added text knowing what to look for. The judge never writes a finding; it only decides whether step 3 runs.

Cost: one Haiku call on a diff, about half a cent, against $0.40 for an update that finds nothing. It would run only on
pages whose text changed a lot with every fact intact, so most entities would never call it. A failed call or a malformed answer counts as `changed`.
The verdict would be stored in a `source_checks.judge` (jsonb) column so it can be read back when tuning.

Where the idea comes from: Firecrawl's Monitor runs a judge only on changed pages, against a plain-language goal, and
returns `meaningful`, `confidence`, `reason` and `meaningfulChanges`. Sangam's goal is sharper than a free-text one:
the findings, gaps and contract fields it already holds. IOEDR's split between updating old evidence and discovering
new evidence is the same line drawn here between 8.1 (broken findings) and 8.2 (new facts).

**The catch.** It
only pays when most changed pages hold nothing new. If most do need research, every one of them pays for the judge
and then for the update.

## References

Each link is where an idea in this plan came from, and the section it shaped.

**Change detection (3.4)**

- IOEDR, *Incremental Open-Ended Deep Research with Structured Harness*,
  [arXiv 2610.11566](https://arxiv.org/abs/2610.11566): the 0.9 similarity gate (Q4), and the split between updating
  old evidence and discovering new evidence (the one-search-per-funder step, and 8.1 vs 8.2).
- Firecrawl, [Change Tracking](https://docs.firecrawl.dev/features/change-tracking): the `new` / `same` /
  `changed` / `removed` statuses the check mirrors; comparing cleaned markdown, not HTML; the warning that changing
  extraction options (`onlyMainContent`, include/exclude tags) makes comparisons unreliable, which is why `extractor`
  records options as well as the version (3.1); whitespace-resistant comparison, behind the normalising step (3.2).
  Its comparison is against the previous scrape, the choice this plan deliberately does not make (the baseline, 3.4).
- Firecrawl, [Monitoring](https://docs.firecrawl.dev/features/monitoring): per-check run status (`partial`,
  `failed`) and `skipped_overlap`, behind `source_check_runs` and the per-entity lock (3.4); a failure streak derived
  from the list of checks rather than a counter (the `unverified` rule); and the judge that runs only on changed
  pages against a goal, returning `meaningful`, `confidence`, `reason` (option 8.2).
- Firecrawl, [How to monitor a website for changes](https://firecrawl.dev/blog/monitor-website-changes-firecrawl):
  a worked example of a goal-based judge on a real page (option 8.2).

**Fingerprints and records (3.1, 3.2)**

- LangChain, [`langchain_core/indexing/api.py`](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/indexing/api.py):
  metadata serialised with `sort_keys=True` before hashing (the fixed `meta` serialisation, 3.2.1); writing the
  data before the record so a crash never leaves a record pointing at nothing (file first, then row, 3.2); and a
  counter-example: it combines the content and metadata hashes into one id, so a metadata-only change counts as a
  change, which is why this plan keeps `content_hash` and `meta_hash` apart. Its `full` cleanup deletes anything not
  seen in a run, the reason a failed fetch is `unverified`, never `dead`.
- LlamaIndex, [`ingestion/pipeline.py`](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/ingestion/pipeline.py)
  (`_handle_upserts`, `_handle_duplicates`): matching on content hash across ids (`DUPLICATES_ONLY`), the same idea as
  "the same report at a new URL is not `new`" (3.4); and `UPSERTS_AND_DELETE`, which drops documents missing from a
  run, the same trap as LangChain's `full` cleanup.

**The partial update (3.5)**

- Salesforce ClaimWriter, [`docs/updates.md`](https://github.com/SalesforceAIResearch/claimwriter-deep-research/blob/main/docs/updates.md):
  facts as durable objects with stable ids, so a source change updates only the affected facts.
- Salesforce ClaimWriter, [`claimwriter/perturb/topdown/fact_edit.py`](https://github.com/SalesforceAIResearch/claimwriter-deep-research/blob/main/claimwriter/perturb/topdown/fact_edit.py):
  the per-source fact delta (`replaced` / `removed_ids` / `added`), the model shown the old and new page with the
  facts previously taken from it, and a relevance score that gates which new facts are kept.

**Libraries the plan relies on**

- [RapidFuzz](https://rapidfuzz.github.io/RapidFuzz/): `fuzz.ratio` for the similarity gate (3.4) and
  `fuzz.partial_ratio` for the evidence check (option 8.1).
- [Trafilatura](https://trafilatura.readthedocs.io/): the extractor `read_page` already uses; its options are what
  `extractor` must record (3.1).
