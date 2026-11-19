# Scout change check: coding steps

The design is in [2026-11-16-scout-source-fingerprints-and-change-check.md](2026-11-16-scout-source-fingerprints-and-change-check.md).
This file is the order to build it in: small steps, one at a time, each with its own test.

**How to use it.** Do one step, run its test, try it by hand, tick the box. Don't start the next step until the
current one works. Each step is one commit; the PR line under each part says which steps ship together.

**Every step has the same four parts:**

- **Goal:** what this step adds, in one line.
- **Code:** the files it touches.
- **Test:** the unit or integration test that proves it.
- **Try it:** what you run by hand to see it work.

**Safe by default.** Steps 9–16 only read and print. Nothing writes to the database until step 17, and then only
with `WRITE=1`. Any step that writes, or runs Scout or a model, needs a yes before it runs.

```
PART A  remember what was read          PART B  check for change                    PART C  update
  1  move fetch/clean                     9  command skeleton                         19 fact id + supersedes
  2  normalise text                      10  baseline                                 20 delta prompt
  3  hash text                           11  fetch status                             21 delta save
  4  PDF text hash                       12  hash compare                             22 draft in Review & save
  5  migration 0058                      13  diff
  6  record_snapshot                     14  evidence check
  7  tools record + run context          15  relevance judge
  8  save links + _shelve key            16  new-source search
                                         17  migration 0059 + WRITE=1
     ── pilot setup ──                   18  decision per funder
                                            ── pilot ──
```

---

## Part A: remember what was read

### PR 1: the move (R5, nothing else)

#### ☐ Step 1. Move fetch-and-clean into one file

- **Goal:** the check and the researcher clean a page with the same code, so their hashes agree.
- **Code:** move the cores of `_read_page` (`ingest/tools/research_tools.py:179`) and `_fetch_document` (`:249`) and
  the helpers they use into `ingest/reading/fetch.py`. The tools call it. `git mv`-style: no behaviour change.
- **Test:** the existing `read_page` / `fetch_document` tests pass unchanged. `pytest tests/test_architecture.py`.
- **Try it:** `cd backend && pytest -k "read_page or fetch_document"`.
- **Then:** `make wiki-update`.

### PR 2: source snapshots

#### ☐ Step 2. Normalise text

- **Goal:** the same page with different spacing becomes the same text.
- **Code:** `normalise(text) -> str` in `ingest/reading/fingerprint.py`: Unicode NFC, zero-width characters and
  soft hyphens removed, whitespace collapsed. Not lowercased.
- **Test:** unit: `"a  b\n"` and `"a b"` → equal; NFC and NFD forms → equal; `"A"` and `"a"` → different.
- **Try it:** `python -c "from app.ingest.reading.fingerprint import normalise; print(repr(normalise('a​  b')))"`.

#### ☐ Step 3. Hash text

- **Goal:** one fingerprint per version of a page.
- **Code:** `text_hash(text) -> str` in the same file: `sha256(normalise(text))`.
- **Test:** unit: two spacings of one text → same hash; one changed word → different.
- **Try it:** hash two copies of a real page's text, one with extra blank lines; the hashes match.

#### ☐ Step 4. PDF text hash

- **Goal:** a re-exported PDF with new dates is not a change.
- **Code:** `fetch.py` extracts the PDF's full text; a scanned PDF with no text layer hashes its bytes instead.
- **Test:** unit: two exports of one PDF with different `ModDate` → same hash; a PDF with no text → bytes hash.
- **Try it:** hash an annual report PDF twice, the second copy re-saved; the hashes match.

#### ☐ Step 5. Migration 0058

- **Goal:** Postgres can hold page versions.
- **Code:** `db/migrations/0058_source_snapshots.sql`: `source_snapshots` (design 3.1), `entity_research.snapshot_ids
  bigint[]`, RLS and grants like `entity_research`. Add `source_snapshots` to `KNOWN_EXCLUDED`
  (`ask/tools/sql/catalog.py`).
- **Test:** integration: table, column, RLS and grants exist; `_verify_sql_catalog` still boots.
- **Try it:** `make migrate`, `make migrate-status`, then `\d source_snapshots` in `make psql`. (Local DB only.)

#### ☐ Step 6. `record_snapshot`

- **Goal:** one function writes a version, or bumps `last_seen_at` if it's already there.
- **Code:** `record_snapshot(url, kind, text, archive_key) -> int | None` in `ingest/reading/snapshots.py`:
  `INSERT … ON CONFLICT (url, text_hash) DO UPDATE SET last_seen_at = now() RETURNING id`. Never raises: logs and
  returns `None`.
- **Test:** integration: same text twice → one row, newer `last_seen_at`, same `first_seen_at`; changed text → two
  rows; a DB error → `None`, no exception.
- **Try it:** call it twice from a Python shell against the local DB, then `SELECT * FROM source_snapshots;`.

#### ☐ Step 7. The tools record, the run remembers

- **Goal:** every page or report a researcher reads gets a snapshot, and the run knows which.
- **Code:**
  - `read_page` / `fetch_document` call `record_snapshot` **after** `storage.upload` (file first, then row). Skip
    Doc Vault and staff spreadsheets.
  - A context variable in `ingest/reading/snapshots.py` collects the ids, set per researcher by middleware the same
    way `run_sources.CURRENT` is (`ingest/middleware.py:406`).
- **Test:** unit: a failed upload → no row; two researchers in parallel each collect only their own ids; a private
  source → not recorded.
- **Try it:** run the unit tests; a real run waits for step 8.

#### ☐ Step 8. The save links, `_shelve` keeps the key

- **Goal:** each research row says which versions it was based on, and the archive key stays right after a move.
- **Code:**
  - `save_research` writes `snapshot_ids` from the context variable in the same transaction as the upsert. Log a
    cited URL with no snapshot.
  - `_shelve` (`catalog/promote_documents.py:155`) updates `source_snapshots.archive_key` when it moves a file.
- **Test:** unit (repositories monkeypatched): the save carries the run's ids; a moved file's key follows it.
- **Try it (writes, ask first):** one Scout run on one funder locally, then
  `SELECT slug, snapshot_ids FROM entity_research ORDER BY id DESC LIMIT 1;` shows ~15 ids.
- **Then:** `make wiki-update`, CHANGELOG line, ARCHITECTURE.md rule: "what a run read is recorded by the tools,
  not the model".

#### ☐ Pilot setup

A full pull on 5–10 funders, so they have baselines to check against.

---

## Part B: check for change

From step 9, one command runs the check up to a step and prints what it found:

```
make source-check SLUG=azim-premji-foundation UNTIL=<step>       # read-only, prints
make source-check SLUG=azim-premji-foundation WRITE=1            # step 17 on: saves results
```

### PR 3: the check without a model (read-only)

#### ☐ Step 9. The command skeleton

- **Goal:** a command to hang every later step on (it also gives each new function a caller, R6).
- **Code:** `ingest/refresh/change_check.py` with a `main()` that takes `--slug` and `--until`; a `source-check`
  target in the `Makefile`. It prints the slug and stops.
- **Test:** unit: unknown `--until` value → a clear error.
- **Try it:** `make source-check SLUG=azim-premji-foundation` prints the slug.

#### ☐ Step 10. Baseline

- **Goal:** know which version of each page the facts came from.
- **Code:** `ingest/refresh/baseline.py`: the URLs across all the slug's research rows (not `wrong_entity`), and for
  each the snapshot in the newest row that read it.
- **Test:** unit: an older wide row and a newer narrow one → the older row's URLs keep their own snapshot; a
  `wrong_entity` row is ignored.
- **Try it:** `UNTIL=baseline` prints each URL, its hash and the date it was read.

#### ☐ Step 11. Fetch status

- **Goal:** a failed fetch is never mistaken for a change.
- **Code:** `ingest/refresh/fetch_status.py`: fetch with `fetch.py` and sort the result:
  403 / 429 / timeout / refusal / empty → `unverified`; 404 / 410 / redirect to the home page → `dead`; else `ok`.
- **Test:** unit, fetch stubbed: each HTTP case → its status.
- **Try it:** `UNTIL=fetch` prints `ok`, `unverified` or `dead` per URL.

#### ☐ Step 12. Hash compare

- **Goal:** most pages stop here, with no more work.
- **Code:** in `change_check.py`: `text_hash(today) == baseline.text_hash` → `unchanged`, else `differs`.
- **Test:** unit: same hash → `unchanged`, and the archive is never loaded.
- **Try it:** `UNTIL=hash` prints `unchanged` or `differs` per URL.

#### ☐ Step 13. Diff

- **Goal:** see exactly what text changed.
- **Code:** `ingest/refresh/diff.py`: load the baseline text by `archive_key`, paragraph-level diff with today's.
  No archive → `changed` ("can't compare").
- **Test:** unit: one changed sentence → one removed and one added paragraph; a moved paragraph → no change; no
  archive → `changed`.
- **Try it:** `UNTIL=diff` prints `+` and `-` lines for each page that differs.

#### ☐ Step 14. Evidence check

- **Goal:** catch a changed fact without a model.
- **Code:** `ingest/refresh/evidence.py`: each finding from that URL → `intact`, `broken` or `unanchored`
  (`rapidfuzz.fuzz.partial_ratio` ≥ 95). Any `broken` → `changed`. Add `rapidfuzz` to the dependencies.
- **Test:** unit: a moved sentence → intact; "400" → "500" → broken; a paraphrase → unanchored.
- **Try it:** `UNTIL=evidence` prints the three counts per page and each broken finding's sentence.
- **Then (end of PR 3):** `make wiki-update`, CHANGELOG line.

### PR 4: the cheap model and the search (still read-only)

#### ☐ Step 15. Relevance judge

- **Goal:** decide whether a changed page matters, for a cent.
- **Code:** `ingest/refresh/judge.py`: Haiku (`SOURCE_CHECK_JUDGE_MODEL`, default in `config.py`), no tools, reads the
  diff + the page's findings + the open gaps, returns the JSON in design 3.4. `meaningful: false` → `minor`;
  `true`, an error or bad JSON → `changed`. Skipped when step 14 already found a broken fact.
- **Test:** unit, model stubbed: each answer → its status; an error → `changed`.
- **Try it (costs cents, ask first):** `UNTIL=judge` prints the judge's answer per changed page.

#### ☐ Step 16. New-source search

- **Goal:** find a new report, programme or open call at a new URL.
- **Code:** `ingest/refresh/discover.py`: the three searches in design 3.4 on the funder's domain; drop known URLs
  and known hashes; the judge says which results matter → `new`.
- **Test:** unit, Tavily and model stubbed: a known URL → dropped; a known hash at a new URL → dropped; another
  domain → ignored.
- **Try it (costs cents, ask first):** `UNTIL=discover` prints the `new` sources.
- **Then:** `make wiki-update`, CHANGELOG line.

### PR 5: save the results

#### ☐ Step 17. Migration 0059 and `WRITE=1`

- **Goal:** keep each check's result.
- **Code:** `db/migrations/0059_source_checks.sql` (design 3.4, "What it writes"). With `WRITE=1`: archive and record
  today's version of each changed page (file first, then row), one `source_checks` row per URL.
- **Test:** integration: migration and boot. Unit: a failed archive → the row's `detail` says so.
- **Try it (writes, ask first):** `make source-check SLUG=… WRITE=1`, then
  `SELECT status, count(*) FROM source_checks GROUP BY 1;`.

#### ☐ Step 18. Decision per funder

- **Goal:** one line that says what to do.
- **Code:** in `change_check.py`: only `unchanged`/`minor`/`unverified` → nothing; any `changed`/`dead`/`new` →
  refresh; more than half the hashes changed → full pull (no judge).
- **Test:** unit: the decision table in design 3.4.
- **Try it:** the last line reads
  `azim-premji-foundation: 14 sources · 11 unchanged · 1 minor · 1 changed · 1 unverified · 1 new → refresh`.
- **Then:** `make wiki-update`, CHANGELOG line.

#### ☐ Pilot

`make source-check WRITE=1` on the 5–10 funders every week for a month. Read every `minor` and `changed`; record in
#411 how often each was right and how many findings were `unanchored`.

---

## Part C: the partial update (PR 6, after the pilot)

#### ☐ Step 19. Fact id and `supersedes`

- **Goal:** a removed fact stays removed.
- **Code:** an id from `brief.fact_key` (`brief.py:206`); a research row may carry `supersedes: [fact_key, …]`, and
  `merge_findings` (`brief.py:233`) drops a fact a newer row supersedes.
- **Test:** unit: an older fact superseded by a newer row is gone from the brief.

#### ☐ Step 20. Delta prompt

- **Goal:** the model answers keep / update / remove / add, not a whole record.
- **Code:** a prompt under `ingest/prompts/` and a grader rubric for a delta (design 3.5).
- **Test:** unit: the prompt names every input it's given.

#### ☐ Step 21. Delta save

- **Goal:** the delta becomes today's research row.
- **Code:** a narrow researcher (`RESEARCH_MODEL`) reads the diff, the findings and the judge's hints; its delta is
  saved as a new `entity_research` row with today's `snapshot_ids` and `supersedes`.
- **Test:** unit, model stubbed: keep + update + add + remove → the right findings in the new row.
- **Try it (costs money, ask first):** on one pilot funder marked `changed`, run it and read the delta.

#### ☐ Step 22. Draft in Review & save

- **Goal:** a person approves the change before the catalog moves.
- **Code:** the new row shows as a draft in Review & save; nothing is promoted on its own.
- **Try it:** the funder shows the draft; the catalog changes only after a person saves it.
- **Then:** `make wiki-update`, CHANGELOG line.
