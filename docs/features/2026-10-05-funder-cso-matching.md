# Funder–CSO matching, as a procedure rather than a subsystem

## Context

The ask: build funder↔CSO matching with agents — which tools we need, and how it extends
Ask Sangam. Two depths are in scope and one is not:

- **(a) Deep assessment of one pair.** FFRH staff name an org and a funder; the agent works
  the full rubric and explains each criterion with citations.
- **(b) Shortlist for a fundraiser.** "Which of these funders should we approach?" — a ranked
  screen across all funders for one org.
- **(c) Weekly RFP triage** is explicitly out. `rfp_matches` exists, is empty, and stays that
  way. Nothing below writes it.

**Nothing is stored.** Decided up front: an assessment the agent produces is a tool result and
an answer, not a row. `fit_scores` keeps its 8 hand-made rows and gains none. This is the
constraint that makes the rest of the design simple, and the one risk it creates is named in
M3.

### What already exists, which is most of it

**The rubric is built, and it is data.** `rubrics` v2 — 7 criteria, 15 sub-criteria, 100
points — with every row carrying a `guiding_question` in plain English:

| | criterion | pts |
|---|---|---|
| 1 | Thematic/Sector Alignment (1a primary 15, 1b secondary 10) | 25 |
| 2 | Geography (2a regional 8, 2b district 7) | 15 |
| 3 | Target Population (3a beneficiary 10, 3b scale 5) | 15 |
| 4 | Eligibility & Compliance (4a legal/registrations 8, 4b funder gates 7, 4c transparency 5) | 20 |
| 5 | Relationship/Warmth (5a direct 6, 5b warm intro 4) | 10 |
| 6 | Funding Size & Type Fit (6a size 5, 6b structure 5) | 10 |
| 7 | Funder Capacity & Trend (7a financial 3, 7b stability 2) | 5 |

**Scoring is modelled end to end and performed entirely by hand.** `fit_scores` (8 rows,
`scored_by='manual'`, temporally versioned) → `fit_score_items` (88 rows, each with a
`justification`) → `score_adjustments` (5 rows, with `reason` and `adjusted_by`). The API reads
and adjusts; **nothing in `backend/app` creates a `fit_score`** — only `seed/seed.py` does.

**Every table the rubric needs is already in the SQL catalog.** All 18 checked, including
`rubrics` and `rubric_criteria` themselves, and `funder_eligibility` as of #89. The agent can
already read the rubric and write the joins. Nothing is invisible to it.

So the gap is not capability. It is three things:

1. **No procedure.** A 22-criterion assessment is a multi-step method, and `instructions.md`
   has no method for it — only rule 4, which tells the agent how to *quote* a stored score.
2. **Round trips.** Assembling one pair's evidence across eight tables is many queries, and the
   prompt's own standard is "two or three is normal for a question with parts; a dozen means
   you are exploring when you should have planned."
3. **The data cannot support the whole rubric, and the agent has no way to know that.**

### The third one, concretely

| criterion | pts | computable | from |
|---|---|---|---|
| 4b funder hard gates | 7 | **yes** | `funder_eligibility` (#89) |
| 2 geography | 15 | yes | `funder_footprints` (320) ∩ `org_locations` (18) |
| 5 relationship/warmth | 10 | yes | `funder_partners` (403), `grants` (4) |
| 4a legal form + registrations | 8 | mostly | `org_identifiers` (24) |
| 1 theme, 3 population | 40 | no — semantic | `org_tags` (82), `funder_tags` (48), `programs` |
| 4c transparency, 6b structure, 7 capacity | 17 | no — judgement | documents, `funder_csr_spend` |
| **6a grant size** | **5** | **NO — and not for want of judgement** | `funders.grant_size_min/max` exist and **nothing populates them** |

Criterion 6a is the one to look at twice. Migration `0019` added `grant_size_min` and
`grant_size_max`; a repo-wide grep finds them in that migration and `docs/DATA_PLATFORM.md`
**and nowhere else** — no finding, no writer, no catalog entry. They are empty and will stay
empty until someone writes the ingest path. An assessment that silently scores 6a as 0 reports
"this funder's grant size does not fit" when the truth is "nobody has recorded what it gives."

That is the same failure the repo already has a rule against —
`instructions.md` rule 10, *"0 rows from a column that is unpopulated means 'not recorded',
never 'does not exist'"* — applied to a number instead of a row count.

## Decision

**Three layers, each holding the thing it is actually good at, and nothing stored.**

| layer | holds | lives in |
|---|---|---|
| signals | deterministic facts about a pair, plus the coverage behind each | a SQL **view** |
| weights | how many points each criterion is worth | `rubric_criteria.points` — already data |
| judgement | the semantic criteria, the narrative, the caveats | the model, via `instructions.md` |

### Zero new agent tools

The six stand. This is the design's best property and the repo argues for it in its own words:
four hand-written tools (`search_orgs`, `get_funder`, `get_grants`, **`get_fit_scores`**) were
deleted because *"they were a cached query plan rather than a capability, and a worse one"* —
and because two paths to the same rows meant two places to keep correct. A `score_fit(org,
funder)` tool would be that mistake with a new name: it returns a verdict, which is precisely
the thing that goes stale when the rubric changes.

A **view** is the opposite. It decides nothing, returns no verdict, and the agent reaches it
through the one path it already has: `db_query`. It adds no tool, no prompt surface, no second
code path, and no row.

Feasibility was checked, not assumed:

- `undeclared_tables()` is fed `information_schema.tables WHERE table_type = 'BASE TABLE'`
  (`core/lifespan.py:146`), so a view is **never** flagged as undeclared.
- `verify_against_db()` reads `information_schema.columns` with **no** type filter
  (`catalog.py:1070`), so a declared view's columns are drift-checked exactly like a table's.
  Changing the view without changing the catalog raises at boot, which is the behaviour we want.
- `Table.primary_key` is consumed only by `_self_check` and `db_describe_table`'s output. For a
  pair view, `('org_id', 'funder_id')` is a truthful statement of grain, not a placeholder.

### Every signal carries its own coverage

The view returns, for each signal, both the overlap **and the denominator behind it**:
`shared_district_count` *and* `org_location_count` *and* `funder_footprint_count`. Without the
second pair, zero overlap and zero data are the same number, and the agent will confidently
report a geographic mismatch for an org whose districts nobody has entered — 18 `org_locations`
across 11 orgs makes that the common case, not the edge case.

This is rule 10 pushed down into the schema so the model cannot get it wrong by omission.

### Two depths, one rubric

Both read the same view and the same `rubric_criteria.points`, so the two numbers are
comparable instead of being two unrelated scores a fundraiser has to reconcile.

- **(b) Screen** — one `SELECT` over the view for one org across all funders, ranked by the
  deterministic subtotal alone. It is explicitly **not** a fit score and must never be
  presented as one: it is "these are worth assessing, in this order, and here is what I could
  not weigh."
- **(a) Assess** — the view row for one pair, plus two or three queries for the semantic
  criteria. Roughly four queries for a full 22-criterion assessment, which sits inside the
  prompt's existing standard.

### Scored out of what was available, never out of 100

An assessment where 6a cannot be computed is not a score out of 100. Every output states
`N / M available points`, lists which criteria were unscorable, and says why for each —
*unpopulated column*, *no data for this org*, *needs a human*. A single number out of 100 with
a silent hole in it is worse than no number, because it is comparable-looking.

## Milestones

Four, each its own PR with an exit gate. M1 is the only one that touches SQL; M2–M4 are prompt
and evals, which is the shape you want when the answer is "a procedure, not a subsystem."

### M0 — the plan is on the branch

This document, committed to `docs/features/` on `docs/funder-cso-matching` before any code,
per the repo's convention (`2026-10-04-funder-eligibility.md`, `2026-10-04-org-writer.md`).

### M1 — the signals view, and the agent can read it

**Exit gate:** `db_query` returns 462 rows from `fit_signals` (11 orgs × 42 funders); the
backend boots with the catalog verified against the view; `make migrate-status` lists `0022`.

1. **`db/migrations/0022_fit_signals.sql`** — `CREATE VIEW fit_signals`, one row per
   `orgs × funders`, carrying only deterministic facts and their coverage. Sketch:

   ```sql
   CREATE VIEW fit_signals AS
   SELECT o.id AS org_id, f.id AS funder_id,
     -- criterion 2, with its denominators
     <shared_district_count>, <shared_state_count>,
     <org_location_count>, <funder_footprint_count>,
     -- criterion 5
     <direct_grant_count>, <shared_partner_count>, <funder_partner_count>,
     -- criterion 4
     <funder_disqualifier_count>, <funder_eligibility_count>,
     <org_has_12a>, <org_has_80g>, <org_has_csr1>, <org_has_fcra>, <org_identifier_count>,
     -- criterion 1
     <shared_tag_count>, <org_tag_count>, <funder_tag_count>,
     -- criterion 6a: carried so the agent can SEE they are null, not infer it
     f.grant_size_min, f.grant_size_max
   FROM orgs o CROSS JOIN funders f;
   ```

   A view materialises nothing, so "store nothing" holds literally. 462 rows is trivial; if the
   cohort grows an order of magnitude this becomes a materialised view, which is a later
   decision and not this one.

   **No weights in the view.** It returns counts and booleans only. The moment a `CASE WHEN
   shared_district_count > 0 THEN 7` appears in that SQL, the rubric has two homes and
   `rubric_criteria.points` is decorative — the same failure `{{MAX_PARALLEL_RESEARCH}}` exists
   to prevent in the prompts.

2. **`app/agent/tools/sql/catalog.py`** — the `fit_signals` entry: grain
   `('org_id', 'funder_id')`, a `description` saying it is a derived view of deterministic
   signals and **not** a score, and `defects` carrying the two caveats that matter —
   `grant_size_min/max` are unpopulated, and a zero overlap must be read against its coverage
   column. Catalog goes to 42.

   Adding to the catalog is a security decision per CLAUDE.md. The answer here is easy: the
   view reads only tables already in the catalog and exposes no column that was not already
   reachable.

### M2 — depth (a): one pair, assessed

**Exit gate:** a real question through the agent — "how well does \<org\> fit \<funder\>?" —
returns all 22 criteria with a cited justification each, a `N / M available points` total, and
an explicit unscorable line for 6a naming the unpopulated column. In four queries or fewer.

3. **`app/agent/instructions.md`** — the assessment procedure. The file is 35 lines and tightly
   written; this adds one section, not a rewrite. It must say: read the rubric from
   `rubric_criteria` rather than carrying it in the prompt (so a rubric v3 needs no deploy);
   read `fit_signals` for the pair; score the semantic criteria from the underlying rows with
   citations; and report unscorable criteria as unscorable.

   **Open question for implementation, not for this plan:** whether this belongs in
   `instructions.md` or wants the skills mechanism. Sangam Import loads procedures from
   `skills/<name>/SKILL.md` and Ask Sangam does not have that — it carries `read_file` only
   because `FilesystemMiddleware` refuses to build without it, and it is wired to
   `StateBackend()`, which is virtual state, not disk. Giving Ask Sangam real skills means
   changing that backend, which has harness implications (`app/agent/harness.py`) and is its
   own change. **Start in `instructions.md`**; if the procedure grows past roughly a screen,
   that is the signal to do the skills work properly rather than bloating a prompt every
   question pays for.

### M3 — the honesty rule, which is the risk this design creates

**Exit gate:** asked for "the fit score" of a pair that **has** a stored `fit_scores` row, the
agent shows the stored human score first, labelled, and offers the computed one as separate and
clearly not a row. Asked about a pair with no stored row, it never implies one exists.

4. **`app/agent/instructions.md` rule 4** currently reads *"Fit scores are rubric-based
   assessments by a single human rater, not ground truth."* With this change that sentence is
   no longer sufficient: there are now **two kinds of number** with the same name, and only one
   of them is in the database.

   Rule 4 extends to distinguish them by construction — a stored score cites `[score:N]`, a
   computed assessment **has no citation marker and must say so**, because it is not a row. The
   citation convention does the work: a number without `[score:N]` is, by the repo's own rule,
   not a database fact.

   This is the single thing most likely to go wrong with "store nothing," and it is worth its
   own milestone rather than a line inside M2.

### M4 — evals, because this is a prompt change and prompts regress silently

**Exit gate:** `make evals TAG=canary` green, with the new cases in it.

5. **`tests/evals/`** — golden questions through the real agent, `eval` mark, skipped unless
   `--run-evals`. Four cases, chosen because each pins a specific way this design fails:
   - a pair with a stored score → the stored one is shown and labelled (M3);
   - a pair with no stored score → an assessment with no `[score:N]` anywhere;
   - an org with **zero** `org_locations` → criterion 2 reads "not recorded", not "no overlap";
   - any pair → 6a is reported unscorable, naming the unpopulated column.

   The third and fourth are `expected_failure` candidates if they fail for data reasons: a case
   marked `xfail(strict=True)` passes the day the underlying data is fixed, pytest reports XPASS
   as a failure, and the marker gets deleted. That is the repo's existing mechanism for "this is
   a data bug, not a code bug", and it fits here exactly.

## Verification

```bash
# M1
make migrate && make migrate-status          # 0022 listed
make psql <<'SQL'
SELECT count(*) FROM fit_signals;            -- 462
SELECT * FROM fit_signals WHERE org_id = 1 AND funder_id = 7;
SQL
make up && make logs | grep -i "catalog\|undeclared"   # verified, nothing undeclared
cd backend && pytest -m "not integration" && pytest tests/test_sql_integration.py && ruff check .

# M2 / M3 — through the real agent, not a unit test
#   "how well does <org> fit <funder>?"      -> 22 criteria, N/M points, 6a unscorable
#   "what's the fit score for <scored pair>?" -> stored score first, cited [score:N]
#   "which funders should <org> approach?"    -> ranked screen, labelled NOT a fit score

# M4
make evals TAG=canary
```

`make smoke` is not a gate: it exercises the chat wire and the frontend, and nothing here
touches either.

## Deliberately not in scope

- **Writing anything.** No `fit_scores` row, no `rfp_matches` row, no `scored_by='agent'`. If
  persistence is wanted later, the shape is already obvious and already built: Sangam Import's
  `save_research` → `promote_research` → hand-written writers, with `score_adjustments` as the
  human-override log. That is a third agent, not a tool on this one.
- **(c) weekly RFP triage.** `rfp_matches` keeps its zero rows.
- **Populating `grant_size_min/max`.** Criterion 6a stays unscorable until an ingest path fills
  those columns. The research half already exists — `funder-intake-research` field 8 is *"Grant
  size, duration and co-funding share. Hard numbers only"* — so unlike the other no-home fields
  this one has **both** the question and the columns, and only the finding → record → writer
  path in between is missing. **It is the single highest-value follow-up**: 5 points of the
  rubric, and the only criterion blocked by absent plumbing rather than absent judgement.
- **A frontend surface.** This extends the Ask workspace through conversation. A ScoreCard that
  renders a computed assessment is a separate design and would need the design system first.

## Working notes

- **Shared checkout.** Other sessions run in `~/Documents/sangam`; this branch was cut in a
  worktree off `origin/master` at `13f2a38`. Confirm `0022` is still the free migration number
  at implementation time.
- **#89 is merged**, so `funder_eligibility` is on `master` and criterion 4b has real data
  behind it. The staging migration it needs has **not** been run — see the deploy note below.
- **Both Vercel projects are paused** (`x-vercel-error: DEPLOYMENT_PAUSED`); production has
  served 503 since 1 Oct and the last deployment to reach `READY` is `a31d6ff`. Nothing in this
  plan can be verified against the deployed stack until that is resolved.
