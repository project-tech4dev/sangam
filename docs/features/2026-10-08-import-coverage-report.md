# Import: coverage report, write confirmation, stop and start over

Status: Draft v1 · 2026-10-08

## Context

After a research run, staff cannot see what Import *should* have found but didn't. Today the
only signal is `not_found`: a free list of concept names the model chooses to write. It has
three problems:
- It is often wrong. On the local SBI run it lists `csr_year` as not found, yet three
  `csr_year` findings exist.
- It is often rejected. Three of the four researchers today had `save_research` refused
  because the model put sentences in `not_found`.
- It cannot say *why* something is missing.

The goal is that every Import research run ends with a coverage report, computed in Python
and printed in the chat. For each entity it shows:
- what the catalog expects, by concept, by fiscal year and by field;
- what was pulled;
- what is missing and why: blocked, not stated, not attempted, or found but not written;
- all of it as percentages.

Two more milestones were added later in the same conversation:
- **M3** fixes today's three Import bugs: the catalog written without confirmation, a
  declined workbook still being read, and the dossier returning the wrong funder.
- **M4** lets staff stop a turn and start over clean.

User decisions:
- Every catalog write waits for an explicit Approve.
- Start over keeps research already saved.

Coverage decisions:
- Measure concepts and fields.
- Score year-bound concepts per requested year.
- Show the report in the agent's chat only (no UI card).
- Give each missing item one of 4 reasons.

**Scope:** research runs only, meaning `entity-researcher` → `save_research` → catalog write.
The adapter pipeline (`plan_import`/`run_import_now`, `india_csr`, `gdelt`) has no concept
model and is out of scope.

## Definition (worked on the real local SBI run, `entity_research` #2)

- **Cell.** A concept the entity kind expects (`concepts_for(kind)`). Year-bound concepts
  get one cell per requested year. A concept is year-bound if its finding subclasses
  `YearlyFinding`: `csr_year`, `csr_spend`, `footprint`, `partner`, `programme_spend`,
  `org_financials`.
- **Funder, 3 years.** 8 one-off concepts + 5 year-bound × 3 = **23 cells**.
- **SBI result.**
  - Year cells found: csr_year 3/3, csr_spend 3/3, footprint 2/3, partner 1/3,
    programme_spend 2/3, so 11/15.
  - One-off concepts found: identity, program, metric and document, so 4/8.
  - **Concepts: 15 of 23 (65%).**
- **Missing 8 (35%).**
  - Not stated, 3 (13%): eligibility_guideline, rfp, contact.
  - Not attempted, 5 (22%): stated_geography (in neither findings nor not_found),
    footprint FY24-25, partner FY22-23 and FY24-25, programme_spend FY24-25.
  - Blocked, 0. Today there is no structured way to record it.
- **Fields.** For each expected concept, fields filled = expected fields (`expected_fields`)
  set non-null on at least one of its findings, out of all expected fields for the kind. A
  concept with nothing found contributes all of its fields as missing.
- **Required fields** are reported separately. For example, a csr_spend finding with no
  `amount` cannot be written, whatever its field %.
- **Found, not written.** The cell has findings, but a dry-run catalog write would hold or
  skip it. Example: programme_spend with domain 'others' not in tags.
  - This applies to **funders only**. `promote()` drops the plan gate for orgs
    (`promote.py:1112`), so an org cannot be dry-run, and the report says so.

Target output, which the supervisor prints verbatim:
```
Coverage: SBI Foundation (funder), FY2022-23 to FY2024-25
Concepts 15/23 (65%) · Fields 52/91 (57%)
Missing 8 (35%): not attempted 5 (22%) · not stated 3 (13%) · blocked 0 · found, not written 0

concept            years  fields  missing
csr_year           3/3    5/8     –
footprint          2/3    3/5     FY2024-25 not attempted
partner            1/3    7/13    FY2022-23, FY2024-25 not attempted
eligibility_guide. –      0/1     not stated: sbifoundation.in is JS-rendered, no text
stated_geography   –      0/2     not attempted
csr_spend FY2023-24: 1 line missing required `domain` (cannot be written)
```

## Design

**1. Structured gaps replace free `not_found`.** `backend/app/ingest/research_records.py`
- Add `Gap{concept, fiscal_year: str|None, field: str|None, reason: Literal["not_stated","blocked"], detail: str}`
  with `extra="forbid"`. Validators:
  - `concept` must be in `concepts_for(entity_kind)`.
  - `fiscal_year` is only allowed on a year-bound concept.
- `EntityResearch` changes:
  - New field `gaps: list[Gap]`.
  - New field `years: list[str]`, the fiscal years asked for.
  - `not_found` stays, for back-compat, and is derived on save. It holds a concept only when
    all of that concept's cells are gaps.
- `detail` takes the sentences the model keeps trying to write. For example,
  `{concept:"rfp", reason:"blocked", detail:"sbifoundation.in is JS-rendered; no text on any path"}`.
- `ResearchSummary.not_found` is unchanged, so `brief.py`'s "Looked for, not found" keeps
  working.

**2. Migration `db/migrations/0035_research_coverage.sql`.**
- `ALTER TABLE entity_research ADD COLUMN gaps jsonb NOT NULL DEFAULT '[]', ADD COLUMN years text[] NOT NULL DEFAULT '{}'`.
- This is additive. `verify_against_db` (`app/agent/tools/sql/catalog.py:991`) only fails on
  catalogued columns missing from the DB, so `catalog.py` needs no change.

**3. Pure coverage module: `backend/app/ingest/coverage.py`.**
- Entry point: `compute(research: EntityResearch, years, write_plan: dict|None) -> Coverage`,
  plus `render(Coverage) -> str`.
- Reuses `concepts_for`, `expected_fields`, `REQUIRED` and `recent_fiscal_years` from
  `app/ingest/expectations.py`.
- No pool and no async, the same shape as `validator.py`.
- Precedence when assigning a reason to a cell:
  1. found, not written
  2. found
  3. a gap's reason
  4. not attempted

**4. Supervisor tool `coverage_report(slug)` in `backend/app/ingest/tools/catalog_tools.py`.**
- Loads the day's latest `entity_research` row. Its years come from `row.years`, falling back
  to `recent_fiscal_years()`.
- For a funder, it runs `promote(conn, row, gate=Gate(plan=True))` to get the write plan,
  exactly as `compare_with_catalog` does (`catalog_tools.py:460-492`).
- Returns `render(...)`.
- Never raises: it returns `"coverage_report failed: …"`.
- Registered in four places:
  - `TOOLS` in `app/ingest/agent.py`
  - `app/ingest/instructions.md`
  - `frontend/features/ingest/lib/toolLabels.ts` ("Coverage report")
  - `save_research` returns the derived `not_found`

**5. Making it mandatory belongs in the prompts, not the skill.** Constraints never live in
skills.
- `app/ingest/instructions.md`: after each researcher returns, and again after each catalog
  write, call `coverage_report(slug)` and print its output verbatim. Never restate it as
  prose or recompute the numbers.
- `app/ingest/prompts/entity_researcher.md`: for every expected concept/year you looked for
  and did not get, add a `gap`. Use `blocked` when the source could not be read (403,
  JS-only, a staff file failed) and `not_stated` when it was read and says nothing. Pass
  `years`.
- `app/ingest/skills/catalog-write-report/SKILL.md`: one short section on where the coverage
  table sits in the report and on not paraphrasing it.

**Reused:**
- `expectations.concepts_for`, `expected_fields`, `REQUIRED` and `recent_fiscal_years`
- `promote(…, gate=Gate(plan=True))` and `_comparison()` (`catalog_tools.py:447`)
- `EntityResearch.by_concept`

## Milestones (each is one PR)

The plan is first committed as `docs/features/2026-10-08-import-coverage-report.md` on a
feature branch in a worktree.

- **M1, backend computes it.** Gap/years schema, migration 0035, `coverage.py`, the
  `coverage_report` tool and its registration.
  - Fix only the existing tests this breaks, such as `_known_concepts` and the
    tool-registered/tool-named checks. No new tests.
  - Exit gate: `pytest -m "not integration"` and `ruff check .` are green; `make migrate`
    applies 0035 locally; the tool run against local `sbi-foundation` and
    `infosys-foundation` prints a table matching the worked numbers above.
- **M2, the agent prints it.** Changes to `instructions.md`, `entity_researcher.md`, the
  `catalog-write-report` skill and `toolLabels.ts`.
  - Exit gate: one live local Import run ("Funding profile for SBI Foundation") ends with the
    coverage table after research and again after the write, with at least one `blocked`
    gap recorded, and `save_research` accepted on the first try.

- **M3: fix today's Import bugs.** Three bugs, all seen in today's runs.
  - **A. The catalog is written without a yes.** Every catalog write now waits for staff.
    - The rule in `instructions.md:292-298` launches the writer with no go-ahead.
      `promote_research` is not paused; only `list_bucket_files` and
      `select_source_files` are (`agent.py:224-233`).
    - SBI was all "new" (case 5), so nothing asked and all 34 rows were written.
    - Fix:
      1. Add a human-in-the-loop pause on `promote_research` in the `catalog-writer`
         spec. Use the same mechanism `save_questions()` uses (`agent.py:249`).
         Allowed decisions are approve and reject.
      2. Add a `ConfirmWrite` card in `frontend/features/ingest/components/`, built with
         `useInterrupt` like `SaveQuestions.tsx`. It shows the entity, the planned table
         and row counts from `compare_with_catalog`, and the coverage line. It has
         Approve and Reject buttons.
      3. Rewrite `instructions.md:292-298`: the writer only runs after the card is
         approved, and "don't write" from staff means don't launch the writer.
      4. Update `docs/features/2026-10-08-import-update-or-ask.md` line 79 so it no
         longer says "the pause, not the prompt". Every write now pauses.
  - **B. A declined staff workbook is still read.** When `read_source_rows` gets no
    `documents`, it reads *every* registered workbook (`staff_sources.py:302`,
    `documents.py:136-145`).
    - Fix:
      1. With no `documents`, read nothing and return "no staff files were selected
         for this run". Change the docstring in `pipeline_tools.py:409-434` and
         `entity_researcher.md:20` to match.
      2. When staff reject the picker, the supervisor's task text says "no staff
         files". The researcher then calls nothing, and the coverage report marks
         staff-sourced cells `blocked: staff declined`.
  - **C. `funder_dossier` returns the wrong funder.** It does
    `similarity(name, %s) >= 0.4 … rows[0]` (`catalog_tools.py:66-80`). "Infosys
    Foundation" vs "SBI Foundation" is about 0.48 on "foundation" trigrams.
    - Fix: resolve the name through `matcher.py` (exact, alias, then
      `core_similarity >= CORE_FLOOR` with boilerplate stripped).
      - A trigram-only hit becomes "close names in the catalog: SBI Foundation [funder:1]
        — not the same unless you confirm". It is never rendered as that funder's
        dossier.
  - Fix existing tests only. Exit gate:
    - Re-run "Funding profile for Infosys Foundation" locally.
    - The dossier says "no match, close: SBI Foundation".
    - Rejecting the workbook picker leaves no `staff dataset` citation.
    - The writer pauses on the Approve card, and Reject writes nothing to `funders`.
- **M4: cancel the turn and restart clean.** Today there is no Stop and no New chat.
  `threadId` is a `useMemo` per mount (`ImportWorkspace.tsx:23`). A thread waiting on a
  picker re-sends the same interrupt forever, so a restart needs a new thread.
  - **Stop**
    1. `useAgentChat` (`frontend/lib/useAgentChat.ts`) exposes
       `stop = () => copilotkit.stopAgent({agent})`.
    2. The Send button becomes **Stop** while `isRunning`.
    3. The abort travels through the route's runner to FastAPI. Starlette cancels the
       stream, so the graph and its `task` subagents are cancelled with it.
  - **Start over**
    1. `threadId` becomes state in `ImportView.tsx`.
    2. "Start over" stops any run, makes a fresh `import-<uuid>`, and remounts
       `<ImportWorkspace key={threadId} threadId={threadId}/>`. Pickers, the board and
       milestones start empty.
    3. It confirms first if a run is live: "Stop the run and start over? Research
       already saved is kept."
  - **Saved work is kept.** Per decision, `entity_research` and committed catalog rows
    stay. Both are atomic per entity: `save_research` writes in one transaction and
    `promote_research` uses one transaction per row.
  - **Abandoned adapter runs.** Wrap `run_import`'s gather in `ingest/runner.py:110`
    with `try/except CancelledError` (and other errors). On those, set
    `ingest_runs.status='failed'` and `notes='cancelled'`, then re-raise. Today nothing
    ever writes `failed`.
  - **Design system.** The Stop and Start over controls change an Import screen, so the
    same PR updates the "Sangam Design System v2" Import page (`docs/DESIGN_SYSTEM.md`)
    in step.
  - Exit gate:
    - Start SBI research, press Stop mid-researcher. No further checkpoints appear on the
      thread and the board shows "stopped".
    - Start over gives an empty chat on a new thread id, and a new request runs normally.
    - A cancelled `run_import_now` leaves its `ingest_runs` row `failed`.
    - `npm run lint && npm run build` are green.

## Verification

- `cd backend && pytest -m "not integration" && ruff check .`
- Check migrations:
  - `make migrate` then `make migrate-status`, locally.
  - Staging then shows 3 pending (0033, 0034, 0035). Applying them is a separate,
    backed-up step and is not part of this work.
- Call the tool directly in the backend container against local `entity_research`
  (SBI #2, Infosys #1) and compare it with the worked example.
- Run Import live on the local stack and confirm the report appears after research and
  after the write.
- `cd frontend && npm run lint && npm run build` for the label change.
