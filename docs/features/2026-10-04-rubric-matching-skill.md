# Score a funder against the rubric we already have

## Context

Ask Sangam answers questions by writing its own SQL. It cannot today answer the question a
fundraiser actually has — *"which funders should we approach, and how good is the fit?"* — as a
repeatable procedure. Doing it well means selecting candidate funders by thematic and programme
overlap, then scoring each one against the rubric the product already uses, with a cited
justification per criterion.

The registry has exactly **8 fit scores, all for one org (KABIL) against four funders**, hand-rated
by a single person. Every other org shows "Not yet scored against the cohort". The goal is to let
the agent produce that assessment on demand for any org × funder pair, and — only when a human
chooses — persist it alongside the hand-rated ones, clearly marked as model-produced.

**Decisions taken:**
- Direction: **org → funders**. Matches `fit_scores`, which is an (org, funder, rubric) triple.
- Rubric: **the stored v1/v2 criteria**, read from `rubric_criteria`. Not a new rubric, and not
  prompt text.
- Provenance: **a separate, clearly-marked tier.**

### Three facts that make this cheaper than it looks

**1. The stored rubric is already a matching rubric.** v1 criterion 1 is *Thematic / Sector
Alignment* at 25 points — the heaviest weight — with Geography (15), Target Population (15) and
Funding Size & Type (10) behind it. "Funders funding in our thematic" is literally criterion 1.
Nothing new needs defining.

**2. v2's sub-criteria map onto the data model almost exactly.** v2 splits criterion 1 into
`1a Primary theme match` (15) and `1b Secondary/cross-cutting theme match` (10) — and
`funder_tags.role` / `org_tags.role` are `primary | secondary`. The join *is* the criterion.

**3. The provenance tier needs no migration.** `fit_scores.scored_by` is
`text NOT NULL DEFAULT 'manual'` (`db/init/02_schema.sql`), and the repo already has a house
convention for exactly this, written at `db/init/02_schema.sql:203`:
```sql
matched_by text,   -- 'manual' | 'model:<name>' | user uuid
```
So a model-produced score is `scored_by = 'model:<name>'`. Today every one of the 8 rows says
`manual`, so the tiers are distinguishable from day one.

---

## Design

### The shape: the agent proposes, a person saves

Ask Sangam **stays read-only**. Its read path has four layers (catalog allowlist → pure validator
→ read-only transaction → `prepare=True`), and the app connects to Postgres **as the database
owner, which is a superuser** — so the catalog is the only line of defence. A write capability
must not be a flag on `PsycopgExecutor` or a relaxation in `validator.py`; loosening either
removes the guard for every query.

So the save is a **separate path that never touches `db_query`**:

```
model scores against rubric_criteria (db_query, read-only)
   └─ propose_fit_score(...)          ← validates, returns a verdict, writes NOTHING
         └─ frontend renders the proposal from step.args
               └─ person clicks "Save this assessment"
                     └─ POST /api/scores  →  repositories/scores.py  →  INSERT
```

**Why the proposal is a tool and not prose.** The frontend already receives every tool call as
`TraceStep {tool, args, result}` (`frontend/lib/useAgentChat.ts`). Putting the proposal in
`args` means the save card renders from structured data with **no text parsing** — and the tool's
`result` is a validation verdict the model can act on when it gets a criterion wrong.

### This widens Ask Sangam's tool surface, deliberately

Ask Sangam goes from **6 tools + `read_file`** to **7 tools + `read_file` + `ls`**. Three
statements in the repo become false and are part of the change, not collateral:

- `CLAUDE.md`: *"The agent has exactly six tools"* → seven, and the paragraph explaining the
  `search_orgs` deletion needs a sentence on why this one is not a curated query plan (below).
- `backend/app/agent/harness.py:22-23`: *"Sangam Import needs `read_file` to load a skill and Ask
  Sangam must not"* → both now load skills.
- `harness.py:47-50`: *"On Ask Sangam it is inert"* → it reads real files under `/skills/`.

`backend/tests/test_harness.py::test_ask_sangam_holds_its_six_tools_and_the_mandatory_one` pins
the exact name set and **must be updated in the same PR**. That test is the thing standing between
us and silently widening the surface; it should fail, loudly, and be changed on purpose.

**Why this is not another `search_orgs`.** The four deleted tools wrapped *fixed queries* — a
cached query plan the model could not adapt, and a second place for data caveats to go stale.
`propose_fit_score` runs **no SQL against the catalog at all** on the model's behalf: it looks up
only the rubric definition. The model still writes every evidence query itself through `db_query`;
the tool type-checks a conclusion it has already reached and hands it to the UI. There remains ONE
path to the data.

### `propose_fit_score` — the contract

```python
async def propose_fit_score(
    org_id: int, funder_id: int, rubric_version: str = "v1",
    items: list[ScoreItem] = [], notes: str = "",
) -> str
```

It reads `rubrics`/`rubric_criteria` (via `get_pool()`, as agent tools do) and checks:
every `code` exists in that rubric · each `score` ≤ that criterion's `points` · for a rubric with
sub-criteria, items sit on **leaves only** · the stated total equals the sum.

Both conventions hold. Errors are **return values**:
`"propose_fit_score failed: '1a' is not a criterion of rubric v1 (codes: 1–7)."`
Rows are **cited**:
`"Proposal valid: 7 criteria, 68/100 for [org:3] against [funder:1]. Not saved — a person decides."`
Markers stay inside `{org, funder}`, so `test_tools_emit_the_markers_we_think_they_do` is unaffected.

One Pydantic model in `app/schemas/scores.py` is **both** the tool's argument shape and the
route's request body — one definition, two consumers, no drift.

### Default to rubric v1

v1 is 7 flat criteria; v2 is 7 parents over 15 leaves. Seeded `funder_tags` rows are **all
`role='primary'`** (`seed/seed.py:338`), so v2's criterion `1b Secondary/cross-cutting theme
match` has no funder-side signal to score against. Default `rubric_version="v1"`; keep it a
parameter so v2 works once funder tagging carries roles.

### The saved score must not silently outrank the hand-vetted one

`LATEST_SCORES_SQL` in `backend/app/repositories/funders.py:8-19` picks the displayed score with
`DISTINCT ON (r.version) … ORDER BY r.version, fs.scored_at DESC` — **newest wins, and `valid_to`
is ignored entirely**. Saving a model score today would make it the figure the Registry shows for
that funder, replacing a human's. Two changes, both required:

- `LATEST_SCORES_SQL` prefers a human row: `ORDER BY r.version, (fs.scored_by <> 'manual'), fs.scored_at DESC`.
- `FitScoreOut` already exposes `scored_by`; `frontend/features/registry/ScoreCard.tsx` renders
  the tier so a model score is never mistaken for a vetted one.

**The correction tier comes free.** `POST /scores/{id}/adjustments` already exists and is
currently unconsumed — it logs `criterion_id`, `old_score`, `new_score`, `reason` and the
adjuster's uuid. A reviewer fixing a model-proposed criterion is exactly that route's purpose.

### The skill

`backend/app/agent/skills/funder-fit-scoring/SKILL.md` — the first skill Ask Sangam has.
Frontmatter `name` must equal the directory name and the `description` says **when** to use it
(`test_harness.py:199` asserts it starts "Use when"). The body carries the procedure: read the
rubric from the database rather than assuming it, select candidates by thematic overlap, score
each criterion against its `guiding_question` with a cited justification, call
`propose_fit_score`.

**Constraints do not live in the skill.** Progressive disclosure means the model *chooses* whether
to load it, so anything that must always hold goes in `app/agent/instructions.md`: that
`propose_fit_score` exists, and that it proposes rather than saves.
`test_a_tool_is_never_reachable_only_through_a_skill` enforces the first half for Import; this
plan adds the Ask Sangam twin.

**A `## Signals` section states what the data cannot support**, so the model does not score on
silence. Honest limits today:

| Criterion | Signal | State |
|---|---|---|
| 1 Thematic | `org_tags ⋈ tags ⋈ funder_tags` | **Works** — 10/10 orgs, 4/4 funders tagged |
| 3 Geography | `org_locations` ∩ `funder_footprints` | Footprints sparse; `funder_locations.role='priority'` is *stated*, not evidence |
| 5 Relationship | `grants`, `funder_partners` | `grants` = 4 rows, no writer; `funder_partners.org_id` **all NULL** → use `similarity(partner_canonical, orgs.name)` |
| 6 Funding size | `funders.grant_size_min/max`, `intake_mode` | **Invisible** until M1 |
| "similar programme" | `programs`, `program_tags`, `chunks` | **Weakest by far.** `programs` is 4 rows, all funder-owned; `program_tags` and `chunks` are empty; no embedding path exists. This half rests on `similarity()` over 4 rows — the skill must say so rather than imply a match |

Two SQL constraints the skill must name: **`WITH RECURSIVE` is rejected** by the validator
(self-join `locations` on `parent_id`, two levels), and **`unnest()` is denied** (use
`= ANY(aliases)`). `locations.name` is UPPER CASE — compare with `ILIKE`.

---

## Milestones

Each is a PR with an exit gate. This document is M0. **M1 and M2 are independently valuable** and
land before any harness change.

### M1 — make the matching inputs visible to the agent
Pure catalog work in `backend/app/agent/tools/sql/catalog.py`, no migration.
- Add to the `funders` table entry: `intake_mode`, `funds_external`, `typical_duration_months`,
  `grant_size_min`, `grant_size_max`. These shipped in `db/migrations/0019_…sql` and are **live
  but uncatalogued**, so the agent cannot read them — they are precisely criteria 2 and 6.
- Add missing `defects`: `grants` ("4 rows and no writer — absence is not evidence a funder funds
  nobody"), `funder_partners.org_id` / `funder_csr_spend.agency_org_id` ("NULL on every row; the
  join returns zero"), `tags` ("only `kind='sector'` has rows").

*Why this is separate:* it is a **security decision** by the repo's own rule, it benefits every
question the agent answers, and it is reviewable without the rest.
*Gate:* `verify_against_db()` passes at boot against staging; `pytest tests/test_sql_catalog.py`.

> Worth noting for later, not fixing here: `verify_against_db` computes
> `{catalog columns} - live` and is therefore **one-directional** — a column added by migration to
> an already-catalogued table is invisible with no warning. That is how these five went unnoticed.

### M2 — the tool
`app/agent/tools/fit_tools.py` (new, matching the `tools/` package rule) · the shared Pydantic
model in `app/schemas/scores.py` · register in `app/agent/build.py` · describe in
`app/agent/instructions.md` · label in `frontend/features/ask/lib/toolLabels.ts`.

Tests: `test_prompt.py::test_prompt_names_every_registered_tool` passes · update
`test_harness.py` to the 7+1 name set · new cases for a bad code, an over-max score, a v2 parent
instead of a leaf, and a sum mismatch.

*Tool before skill, deliberately:* the always-on prompt must name a tool before any SKILL.md does.
*Gate:* `pytest` green; a real `/ask` turn produces a valid proposal and nothing is written.

### M3 — Ask Sangam reads skills from disk, and the skill
Today it cannot, twice over: `build.py:45` hands a bare `StateBackend()` to
`FilesystemMiddleware`, and no `skills=` is passed so no frontmatter index is ever injected.
- A `skills_backend(dir)` helper in `harness.py` (beside `SKILL_READING_TOOLS`, which it pairs
  with), returning the `CompositeBackend` shape that `app/ingest/agent.py:_backend()` already
  uses. Both agents then call it instead of keeping two copies.
- In `build.py`: pass that object as **`backend=`** to `create_deep_agent` — required, because
  `SkillsMiddleware` is built from the top-level `backend`, not from the middleware's — plus
  `skills=[SKILLS_ROUTE]` and `filesystem_tools(backend, keep=SKILL_READING_TOOLS)`.
- Write `app/agent/skills/funder-fit-scoring/SKILL.md`.
- Correct the three now-false statements in `CLAUDE.md` and `harness.py`'s docstring.
- Add `read_file`/`ls` labels to `features/ask/lib/toolLabels.ts`, mirroring the ingest map. (That
  file has an **orphaned comment** where the removed `HIDDEN_TOOLS` set used to be — delete it.)

Tests: a round-trip test like `test_harness.py::test_the_route_round_trips` · the Ask Sangam twin
of `test_a_tool_is_never_reachable_only_through_a_skill` ·
`test_neither_agent_can_write_a_file_or_run_a_command` must still pass.

**Honest cost:** `skills=` injects ~40 lines of deepagents "Skills System" boilerplate into
**every** Ask request, plus one index line per skill — paid on every question, including ones
that will never score a funder.

*Gate:* asking "which funders should KABIL approach?" loads the skill and produces a cited
scorecard.

### M4 — the save
`POST /api/scores` in `app/api/routes/scores.py` + `create_score` in `app/repositories/scores.py`,
following `create_adjustment` exactly: Pydantic body, hand-written parameterised SQL, one
transaction for `fit_scores` + `fit_score_items`.

Non-negotiables: **`scored_by` is stamped server-side** as `f"model:{settings.model}"` and never
read from the body · the route **re-validates against `rubric_criteria`** rather than trusting the
client · a duplicate `(org, funder, rubric, scored_at)` returns **409**, not a 500.
Then `LATEST_SCORES_SQL`, `ScoreCard.tsx`, and the save card in `features/ask/`.

*Gate:* save a proposal; `GET /api/scores?org=kabil` shows it with `scored_by` set; the Registry
still displays the hand-vetted v1 score as primary.

### M5 — evals
Two or three cases in `backend/tests/evals/cases/golden.jsonl` with `tags: ["rubric"]`, including
one where the honest answer is a **refusal to score** criterion 6 for a funder with no
`grant_size_*` — "zero rows is an answer" applies to scoring too.
*Gate:* `make evals TAG=rubric`.

---

## Verification

```bash
make up && make seed && make migrate      # 0019 must be applied for M1's columns to exist
cd backend && pytest -m "not integration" # unit tier
pytest tests/test_harness.py tests/test_prompt.py tests/test_scores.py
pytest -m integration                     # needs the compose Postgres on :5433
ruff check .
cd ../frontend && npm run lint && npm run build   # type errors surface here, never in next dev
make smoke
```

End to end, at http://localhost:3000/ask: *"Which funders should KABIL approach, and how good is
the fit?"* Expect the trace to show `read_file` (the skill), several `db_query` calls, then
`propose_fit_score`; a scorecard with a citation on every criterion; a **Save** affordance; and
after saving, the row visible via `GET /api/scores?org=kabil` marked `model:…` — with the
Registry still showing the human score as primary.

**Confirm nothing was written before the save:** run the question with the save card ignored, then
`make psql` → `SELECT count(*) FROM fit_scores;` is unchanged at 8.

## Open question, deferred

Auth is a stub — `get_current_user` resolves every request to one seeded user, and the deployed
backend is publicly reachable. `POST /scores` is the first route where that matters more than it
does for reads: anyone who can reach the API can write a fit score. It does not block this work
(the write is validated, provenance-stamped and reversible), but it belongs on the list of things
that must land before this is shown to anyone outside the team.
