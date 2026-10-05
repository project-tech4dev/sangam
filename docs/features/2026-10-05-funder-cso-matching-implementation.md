# Funder–CSO Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Ask Sangam assess one org–funder pair against the v2 rubric, and rank all funders for one org, without storing a row or adding a tool.

**Architecture:** Three layers. Deterministic signals come from a new SQL **view** (`fit_signals`, one row per org × funder) that decides nothing and carries the coverage behind every count. Weights stay in `rubric_criteria.points`, which the agent reads from the database. Judgement, narrative and caveats live in `app/agent/instructions.md`. The agent reaches all of it through `db_query`, the path it already has.

**Tech Stack:** Postgres 16 (view, no extension beyond the `pg_trgm` already installed), the SQL catalog in `app/agent/tools/sql/catalog.py`, `app/agent/instructions.md`, and `tests/evals/cases/golden.jsonl` run through the real agent.

**Spec:** `docs/features/2026-10-05-funder-cso-matching.md`

## Global Constraints

- **Nothing is stored.** No task writes `fit_scores`, `fit_score_items`, `score_adjustments` or `rfp_matches`. A view materialises nothing; this holds literally.
- **Zero new agent tools.** `TOOLS` in `app/agent/build.py` stays at six. A task that adds a tool has misread the spec.
- **No weights in SQL.** `fit_signals` returns counts and booleans only. The first `CASE WHEN ... THEN 7` in that view gives the rubric two homes and makes `rubric_criteria.points` decorative.
- **Every assessment states `N / M available points`, never a total out of 100.**
- Schema changes go in `db/migrations/*.sql`, never `db/init/02_schema.sql`.
- `ruff check .` — line-length 110, target py312.
- Adding to the catalog is a security decision. Here the answer is that the view reads only already-catalogued tables and exposes no column that was not already reachable.
- `pytest -m "not integration"` for unit tests; `tests/test_sql_integration.py` needs the compose Postgres on :5433; eval cases need `--run-evals` and **cost money**.

## Review Focus

Five things the spec implies and no task's happy path exercises, most likely to bite first:

1. **The screen silently truncates at 50 rows.** `validator.DEFAULT_MAX_ROWS = 50`. There are 42 funders today, so `WHERE org_id = N` fits — and the 51st funder makes the shortlist silently incomplete. Pinned in Task 4.
2. **An org with zero `org_locations`** must read "geography not recorded", never "no overlap". 18 locations across 11 orgs makes this common, not edge. Pinned in Task 1 (`test_coverage_separates_no_overlap_from_no_data`) and Task 4 (`fit-screen-no-data-org`).
3. **A funder with zero `funder_eligibility` rows** must read "no bars recorded", never "sets no bars". Today that is **all 42 funders** — the table is new in #89 and still empty. Pinned in Task 1 (`test_eligibility_coverage_is_carried`) and Task 3 (`fit-no-eligibility-recorded`).
4. **Criterion 4a is nearly empty and must not read as non-compliance.** Of 11 orgs, exactly 1 has a `12a` identifier, 1 has `80g`, 1 has `csr1`, 2 have `fcra`. An absent 12A means nobody recorded it. Pinned in Task 1 (`test_coverage_separates_no_overlap_from_no_data` covers the shape) and Task 4 (`fit-screen-no-data-org`).
5. **An ambiguous entity name must not be silently resolved.** `axis-bank-foundation` (id 7) and `axis-bank-limited` (id 24) both exist and are the canonical never-merge pair. "Assess Axis Bank" must ask which. Pinned in Task 3.

---

### Task 1: The `fit_signals` view

**Files:**
- Create: `db/migrations/0022_fit_signals.sql`
- Test: `backend/tests/test_sql_integration.py` (new class `TestFitSignals`, `integration` mark)

**Interfaces:**
- Consumes: nothing.
- Produces: view `fit_signals`, grain `(org_id, funder_id)`, 21 columns. Task 2 catalogues exactly this list; Tasks 3–4 query it.

```
org_id                      bigint    -- FK orgs.id
funder_id                   bigint    -- FK funders.id
-- criterion 2 (geography, 15 pts) — each count with its denominator
shared_district_count       integer
shared_state_count          integer
org_location_count          integer
funder_footprint_count      integer
-- criterion 5 (relationship, 10 pts)
direct_grant_count          integer
funder_partner_count        integer
-- criterion 4 (eligibility, 20 pts)
funder_disqualifier_count   integer
funder_eligibility_count    integer
org_has_12a                 boolean
org_has_80g                 boolean
org_has_csr1                boolean
org_has_fcra                boolean
org_identifier_count        integer
-- criterion 1 (theme, 25 pts)
shared_primary_tag_count    integer
shared_any_tag_count        integer
org_tag_count               integer
funder_tag_count            integer
-- criterion 6a — carried so the agent SEES null rather than inferring it
funder_grant_size_min       numeric
funder_grant_size_max       numeric
```

Two deliberate omissions, both because they are judgement the view must not make:

- **No partner-name matching.** `funder_partners.partner_name` is free text, so "is this org a partner" is a fuzzy match. `funder_partner_count` is coverage only; the model does the matching with `similarity()` and says how confident it is. Baking a threshold into a view hides it.
- **No `org_has_*` from unverified rows.** Use `is_current = true`; do **not** filter on `verified`, and let the model read `verified` itself when 4a matters.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.integration
class TestFitSignals:
    def test_one_row_per_pair(self, conn):
        n = conn.execute("SELECT count(*) AS n FROM fit_signals").fetchone()["n"]
        orgs = conn.execute("SELECT count(*) AS n FROM orgs").fetchone()["n"]
        funders = conn.execute("SELECT count(*) AS n FROM funders").fetchone()["n"]
        assert n == orgs * funders

    def test_coverage_separates_no_overlap_from_no_data(self, conn):
        """The whole reason the denominators are in the view."""
        row = conn.execute(
            "SELECT shared_district_count, org_location_count FROM fit_signals "
            "WHERE org_location_count = 0 LIMIT 1"
        ).fetchone()
        assert row is not None, "expected at least one org with no locations recorded"
        assert row["shared_district_count"] == 0

    def test_eligibility_coverage_is_carried(self, conn):
        """Every funder has zero bars recorded today; the count alone cannot say why."""
        row = conn.execute(
            "SELECT funder_disqualifier_count, funder_eligibility_count FROM fit_signals LIMIT 1"
        ).fetchone()
        assert row["funder_disqualifier_count"] is not None
        assert row["funder_eligibility_count"] is not None

    def test_grant_band_is_null_not_zero(self, conn):
        """0019 added the columns and nothing writes them; null is the honest value."""
        row = conn.execute(
            "SELECT count(*) AS n FROM fit_signals WHERE funder_grant_size_min IS NOT NULL"
        ).fetchone()
        assert row["n"] == 0

    def test_the_view_carries_no_weights(self):
        path = Path(__file__).resolve().parents[2] / "db/migrations/0022_fit_signals.sql"
        sql = path.read_text().lower()
        assert "rubric" not in sql and " points" not in sql
```

Expected: 5 tests. `test_the_view_carries_no_weights` needs no `conn`; keep it in the class for cohesion.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_sql_integration.py::TestFitSignals -v`
Expected: FAIL (4 of 5) — `relation "fit_signals" does not exist`; the no-weights test fails on the missing file.

- [ ] **Step 3: Write `db/migrations/0022_fit_signals.sql`**

`CREATE VIEW fit_signals AS SELECT ... FROM orgs o CROSS JOIN funders f`, with each signal a correlated scalar subquery. Header comment states: the view decides nothing, carries no weights, and every count ships with its denominator because a zero with no denominator is unreadable. Confirm `0022` is still free before writing.

- [ ] **Step 4: Run to verify it passes**

Run: `make migrate && cd backend && pytest tests/test_sql_integration.py::TestFitSignals -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add db/migrations/0022_fit_signals.sql backend/tests/test_sql_integration.py
git commit -m "feat(sql): deterministic pair signals, each with the coverage behind it"
```

---

### Task 2: The catalog entry

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (insert alphabetically; `fit_signals` sorts after `fit_scores`)
- Test: `backend/tests/test_sql_catalog.py` (new class `TestFitSignals`)

**Interfaces:**
- Consumes: the view from Task 1.
- Produces: `CATALOG["fit_signals"]`, making the view readable by `db_query`. `CITE_COLUMNS[("fit_signals","org_id")] == "org"` and `...("fit_signals","funder_id")] == "funder"`, inherited from the declared foreign keys — which is what makes a screen row citable with no frontend change.

Declare `ForeignKey("org_id", "orgs.id")` and `ForeignKey("funder_id", "funders.id")`. The view has no database-level FK; the catalog is data, `_self_check` only requires the targets be catalogued, and `verify_against_db` only compares column names. Three `defects`, each a full sentence ending in a period (`test_every_defect_is_a_sentence_not_a_label`).

- [ ] **Step 1: Write the failing test**

```python
class TestFitSignals:
    def test_the_view_is_readable(self):
        assert "fit_signals" in cat.CATALOG

    def test_its_rows_are_citable_as_both_entities(self):
        assert cat.CITE_COLUMNS[("fit_signals", "org_id")] == "org"
        assert cat.CITE_COLUMNS[("fit_signals", "funder_id")] == "funder"

    def test_the_grain_is_the_pair(self):
        assert cat.CATALOG["fit_signals"].primary_key == ("org_id", "funder_id")

    def test_the_description_denies_being_a_score(self):
        assert "not a score" in cat.CATALOG["fit_signals"].description.lower()

    def test_the_defects_name_the_three_traps(self):
        text = " ".join(cat.DEFECTS["fit_signals"]).lower()
        assert "grant_size" in text          # unpopulated, criterion 6a
        assert "coverage" in text or "denominator" in text
        assert "not a fit score" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_sql_catalog.py::TestFitSignals -v`
Expected: FAIL — `KeyError: 'fit_signals'`

- [ ] **Step 3: Add the `Table(...)` entry to `_TABLES` in `catalog.py`**

All 21 columns from Task 1's Interfaces block, with a `note` on each coverage column saying which count it is the denominator for. Catalog goes 41 → 42.

- [ ] **Step 4: Run the full gate**

Run: `cd backend && pytest tests/test_sql_catalog.py -v && pytest tests/test_sql_integration.py::TestCatalogMatchesReality -v && ruff check .`
Expected: PASS. `test_no_drift` is the one that matters — it proves the catalog's 21 columns exist in the live view.

- [ ] **Step 5: Verify the agent can actually reach it, then commit**

Run: `make up && make logs | grep -i "catalog\|undeclared"`
Expected: startup complete; no catalog error; `fit_signals` **not** listed as undeclared (`undeclared_tables` is fed `BASE TABLE` only).

```bash
git add backend/app/agent/tools/sql/catalog.py backend/tests/test_sql_catalog.py
git commit -m "feat(sql): catalogue fit_signals, citable as both the org and the funder"
```

---

### Task 3: Depth (a) — assess one pair

**Files:**
- Modify: `backend/app/agent/instructions.md` (new section after "Answering from the database")
- Test: `backend/tests/evals/cases/golden.jsonl` (4 cases)

**Interfaces:**
- Consumes: `fit_signals` (Task 2), `rubrics` / `rubric_criteria` (already catalogued).
- Produces: the assessment procedure that Task 4's screen narrows to and Task 5's honesty rule qualifies.

The procedure must say, in the file's existing terse style: read the rubric from `rubric_criteria` rather than carrying it in the prompt, so a rubric v3 needs no deploy; read the `fit_signals` row for the pair; score the semantic criteria from the underlying rows with citations; report every criterion you could not score as unscorable **with its reason** — *unpopulated column*, *no data for this org*, *needs a human*; and total as `N / M available points`.

- [ ] **Step 1: Write the failing eval cases**

Append to `golden.jsonl` (assertion-only; the harness skips `gold_sql` when absent):

```json
{"id": "fit-assess-pair", "question": "How well does Goonj fit SBI Foundation?", "must_mention": ["available points"], "must_not_mention": ["out of 100"], "tags": ["canary", "fit"]}
{"id": "fit-unscorable-grant-band", "question": "How well does Goonj fit SBI Foundation?", "must_mention": ["grant size", "not recorded"], "tags": ["fit"], "note": "Criterion 6a: 0019 added funders.grant_size_min/max and nothing writes them. Scoring it 0 reports a size mismatch that is really an empty column."}
{"id": "fit-no-eligibility-recorded", "question": "How well does Goonj fit SBI Foundation?", "must_mention": ["not recorded"], "must_not_mention": ["sets no", "no requirements"], "tags": ["fit"], "note": "Review Focus 3: funder_eligibility is new in #89 and empty for all 42 funders. Zero bars must read as unrecorded, never as a funder that asks nothing."}
{"id": "fit-ambiguous-entity", "question": "Assess Axis Bank against Goonj.", "must_mention": ["Axis Bank Foundation", "Axis Bank Limited"], "tags": ["fit"], "note": "ids 7 and 24, the canonical never-merge pair. Picking one silently is the failure."}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/evals -k "fit-" --run-evals -v`
Expected: FAIL — the agent has no assessment procedure and answers from `fit_scores` or declines.

- [ ] **Step 3: Add the "Assessing fit" section to `instructions.md`**

Keep it inside one screen. If it grows past that, stop and raise the skills question the spec parks — Ask Sangam's `read_file` is wired to `StateBackend()`, not disk, so giving it real skills is its own change with harness implications, not a line in this task.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && pytest tests/evals -k "fit-" --run-evals -v`
Expected: PASS, 4 cases

- [ ] **Step 5: Confirm no tool was added, then commit**

Run: `cd backend && pytest tests/test_prompt.py tests/test_harness.py -v`
Expected: PASS — every registered tool is still named in `instructions.md`, and `TOOLS` is still six.

```bash
git add backend/app/agent/instructions.md backend/tests/evals/cases/golden.jsonl
git commit -m "feat(agent): assess a pair against the rubric, and say what it could not score"
```

---

### Task 4: Depth (b) — screen all funders for one org

**Files:**
- Modify: `backend/app/agent/instructions.md` (extends Task 3's section)
- Test: `backend/tests/evals/cases/golden.jsonl` (2 cases), `backend/tests/test_sql_integration.py` (1 test, added to `TestFitSignals`)

**Interfaces:**
- Consumes: Task 3's procedure.
- Produces: nothing downstream.

The screen is one `SELECT` over `fit_signals` filtered to one org, ranked by the deterministic signals alone. It is **not** a fit score and the output must say so: it answers "these are worth assessing, in this order, and here is what I could not weigh."

- [ ] **Step 1: Write the failing tests**

The integration test pins Review Focus #1 — the silent truncation, the one failure here that produces a confidently wrong answer. It belongs in `TestFitSignals` in `test_sql_integration.py`, because only the live database knows how many funders there are:

```python
    def test_a_one_org_screen_still_fits_under_the_row_cap(self, conn):
        """42 funders today. At 51 the shortlist truncates and nothing says so."""
        from app.agent.tools.sql import validator
        n = conn.execute("SELECT count(*) AS n FROM funders").fetchone()["n"]
        assert n <= validator.DEFAULT_MAX_ROWS, (
            f"{n} funders exceeds the {validator.DEFAULT_MAX_ROWS}-row cap: a one-org "
            "screen is now silently truncated and the prompt must say so"
        )
```

Eval cases:

```json
{"id": "fit-screen-ranked", "question": "Which funders should Goonj approach?", "must_mention": ["not a fit score"], "forbidden_citations": ["score:1"], "tags": ["canary", "fit"]}
{"id": "fit-screen-no-data-org", "question": "Which funders should BETTER LIFE FOUNDATION approach?", "must_mention": ["not recorded"], "must_not_mention": ["no overlap"], "tags": ["fit"], "note": "Review Focus 2+4: an org with no locations and no 12A must read as unrecorded, never as a poor or non-compliant match."}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_sql_integration.py -k row_cap -v && pytest tests/evals -k "fit-screen" --run-evals -v`
Expected: FAIL

- [ ] **Step 3: Extend the `instructions.md` section with the screen**

Must state: always filter to one org (never scan all 462); the result is a shortlist, not a score; name the criteria the screen cannot weigh; and if the funder count ever approaches 50, say the list may be incomplete rather than presenting a truncated ranking as complete.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && pytest tests/test_sql_integration.py -k row_cap -v && pytest tests/evals -k "fit-screen" --run-evals -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/instructions.md backend/tests/evals/cases/golden.jsonl backend/tests/test_sql_integration.py
git commit -m "feat(agent): rank funders for one org, and refuse to call it a score"
```

---

### Task 5: The honesty rule — two kinds of number, one name

**Files:**
- Modify: `backend/app/agent/instructions.md:~17` (rule 4)
- Test: `backend/tests/evals/cases/golden.jsonl` (2 cases)

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: nothing downstream. This is the last task and the riskiest, because it changes how answers about the **existing** 8 stored scores behave.

Rule 4 reads *"Fit scores are rubric-based assessments by a single human rater, not ground truth."* That is no longer sufficient: there are now two kinds of number called a fit score and only one is in the database. The citation convention does the separating — a stored score cites `[score:N]`; a computed assessment has no marker and must say so, because by rule 2 a number without a marker is not a database fact.

- [ ] **Step 1: Write the failing eval cases**

```json
{"id": "fit-stored-score-wins", "question": "What is the fit score for Goonj and Axis Bank Foundation?", "required_citations": ["score:1"], "must_mention": ["single human rater"], "tags": ["canary", "fit"], "note": "A pair with a real fit_scores row. The stored score is shown first and cited; a computed assessment may follow only if clearly separate."}
{"id": "fit-computed-is-not-a-row", "question": "What is the fit score for Goonj and EdelGive Foundation?", "forbidden_citations": ["score:1", "score:2", "score:3", "score:4", "score:5", "score:6", "score:7", "score:8"], "must_mention": ["not stored"], "tags": ["canary", "fit"], "note": "No fit_scores row exists for this pair. Any [score:N] here is the agent attaching a stored row's marker to a number it just computed."}
```

Before running, confirm against the live database which pairs do and do not have a `fit_scores` row, and fix the names and `score:N` ids in both cases to match. A case built on a guess measures the case, not the agent.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/evals -k "fit-stored or fit-computed" --run-evals -v`
Expected: FAIL — rule 4 does not yet distinguish the two.

- [ ] **Step 3: Extend rule 4 in `instructions.md`**

- [ ] **Step 4: Run the whole eval suite, not just the new cases**

Run: `cd backend && make evals TAG=canary`
Expected: PASS, including the pre-existing canary cases. This task edits a rule that every score answer already goes through, so a regression here lands outside the `fit` tag.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/instructions.md backend/tests/evals/cases/golden.jsonl
git commit -m "docs(agent): a stored score cites [score:N], a computed one says it is not a row"
```

---

## Verification

```bash
make migrate && make migrate-status            # 0022 listed
cd backend && pytest -m "not integration"      # unit
pytest tests/test_sql_integration.py           # needs compose Postgres on :5433
ruff check .
make up && make logs | grep -i "catalog\|undeclared"
make evals TAG=canary                          # COSTS MONEY
```

`make smoke` is not a gate: it exercises the chat wire and the frontend, neither of which this touches.

## Notes for the implementer

- **Pre-existing failures that are not yours.** `tests/test_migration_integrity.py` has 3 failures and `ruff check .` reports 72 errors on `master` — the local database has drifted from pristine seed state through import runs. Confirm against `master` before chasing either.
- **Eval cases cost real money** and run against the real agent. Run `-k` filtered during Tasks 3–5; run the full `TAG=canary` once, at Task 5 Step 4.
- **Shared checkout.** Other sessions run in `~/Documents/sangam`. Work in a worktree, and re-confirm `0022` is free when you start.
- **The spec has one gap this plan closes.** Its milestones cover the view, depth (a), the honesty rule and evals, but never give depth (b) a milestone of its own even though the Decision section specifies it. Task 4 is that milestone. The spec's M4 "evals" is dissolved into Tasks 3–5 instead, because for a prompt change the eval case *is* the failing test and writing it afterwards is not TDD.
