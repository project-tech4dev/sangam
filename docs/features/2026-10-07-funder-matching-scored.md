# Funder matching, scored: the agent finds the facts, code decides gate, score and order

*Approved 2026-10-07. Supersedes the tier decision ("tiers, no numbers") in
`2026-10-06-funder-matching-agentic.md`; the assessor subagent and the skills from that plan stay.*

*Later the same day, `2026-10-07-funder-matching-readiness-once.md` split the assessor: the 12
organisation-only checks are judged once by `org-readiness`, and code merges them with each
funder's checks before scoring.*

## Context

Funder matching today (`feat/matching-engine`, approved 2026-10-06 in
`docs/features/2026-10-06-funder-matching-agentic.md`) has a `funder-assessor` subagent read the DB
and return cited `met / fail / unknown` checks plus a **model-chosen tier** (strong / possible / weak /
not_enough_recorded). The weights were dropped.

The user now wants the framework they pasted, applied **deterministically**: checks → groups →
gates (Fit → Statutory → Turnover) → a score out of 100 (Fit 40 · Compliance 25 · Financial 15 ·
Governance 10 · Programme 10) with partial credit for area → a fixed ranking order. They chose
(2026-10-07):

- **Agent finds, code scores.** Reading and judging each check stays agentic (that part was most of
  the 4,100-line engine that was deleted). Gates, weights, partial credit and the order become a
  small pure function: the same checks always give the same verdict and score.
- **Readiness framework now; the sector-weight table (banks / manufacturers / IT / pharma) later.**
  The weight table needs a funder industry, plant locations and target population. None of those are
  recorded yet.
- **`programme` = the NGO runs its own programme in the shared theme** (today's prompt checks the
  funder's programme; that changes).
- No external research.

**What the data will show (local DB, 2026-10-07; staging not checked):** 43 funders, 11 orgs.
- `funder_eligibility` has 0 rows, so the turnover gate never fires.
- 12A, 80G and CSR-1 are each recorded for 1 org, so the statutory gate will read **Unverified**
  for almost every corporate funder.
- No org has audited financials, so 15 points will be unknown everywhere.
- Footprints (32 funders) and themes (15 funders) carry the signal.

Expect the first shortlists to be mostly "Unverified, ranked by fit". The `gaps` list then says
what data to record. That is the honest output, not a bug.

## The design

```
funder-matching skill (unchanged shape): resolve org → ONE narrowing db_query → waves of funder-assessor
  funder-assessor (agentic, read-only SQL)   →  checks[]: code · outcome · basis · cites · note
                                                 + area level, shared_districts, funder_type, section_135_bound
  FunderAssessment @computed_field (pure)    →  gate · gate_reasons · score · breakdown · coverage
  deepagents serialises it with model_dump_json()  → computed fields reach the supervisor for free
funder-shortlist-brief: Eligible → Unverified → Removed, ordered by the ranking key
```

There is **no new tool, middleware or table**: the six-tool pin holds. Verified in
`deepagents/middleware/subagents.py:733-736`: a structured response goes back as
`structured.model_dump_json()`, which includes computed fields. `ToolStrategy` builds the model's
schema in validation mode, which leaves them out, so the model is never asked to fill them.

### Gates (code, `app/agent/scoring.py`)

| gate | checks | applies | pass | fail | otherwise |
|---|---|---|---|---|---|
| Fit | area, theme, programme | always | any `met` | all three `fail` | unverified |
| Statutory | reg_12a, reg_80g, csr_1, audits_3y | `funder_type` in {corporate_csr, corporate_foundation} or `section_135_bound`. **Three-valued:** type NULL/`other` and s135 NULL → the gate is `unverified`, never skipped, so an unknown funder cannot outrank a known corporate | all `met` | any `fail` | unverified |
| Turnover | turnover | only when the assessor returned a `turnover` check (a bar is recorded) | `met` | `fail` | unverified |
| Funder bars | each `funder_bar` | when present | all `met` | any `fail` | unverified |

The overall gate is `fail` if any gate fails, else `unverified` if any is unverified, else `pass`. A
required statutory check that the assessor left out counts as `unknown`. Applicability is decided
in code from `funder_type`, never by the model. `corporate_foundation` is included because CSR money
routed through a foundation still requires CSR-1. That is a deliberate widening of the paste's
"corporate_csr"; flag it at review.

### Score (out of 100; only `met` earns; not-applicable checks drop out of their group's denominator)

| group | weight | checks (equal share inside the group) |
|---|---|---|
| Fit | 40 | area 20 (district 1.0 · state 0.6 · pan_india 0.3 · regional 0.3 **only when the NGO's state lies in that region**), theme 12, programme 8 |
| Compliance | 25 | reg_12a, reg_80g, csr_1, darpan, pan, reg_no, fcra (fcra only if foreign) |
| Financial | 15 | audits_3y, itr_7, turnover (if a bar exists) |
| Governance | 10 | board, team_cvs |
| Programme experience | 10 | projects_3 |

The assessor reports the **best** area level when several apply (district > state > pan_india >
regional). A region that does not contain the NGO's state is `fail` with the row cited, or `unknown`
when the region's member states are not recorded. `programme` cannot be `met` when `theme` is `fail`:
it means a programme in the *shared* theme.

- `coverage` = known checks ÷ applicable checks.
- `breakdown` gives the points per group.
- The weights live in one dict in `scoring.py`. Changing them is a PR with a test diff, like the
  criteria prompt.

### Ranking key (the shortlist skill sorts by it, in this order)

1. gate: pass, then unverified. Failed funders are listed under "Removed" with the cited row
   (gate fail = positive evidence only, so this never happens on missing data).
2. score, descending
3. coverage, descending
4. shared_districts, descending
5. funder_id, ascending

`rank_key` is one more computed field: a zero-padded string such as `"1-087-082-003-00002"`, with
the gate encoded so that pass sorts first. The supervisor sorts on that one string rather than on
five columns. The sort itself is still the supervisor's, the one place an LLM still touches the
result, and evals assert it.

## Milestones (one PR each, on `feat/matching-engine`)

**M0: design doc.** Commit this plan as `docs/features/2026-10-07-funder-matching-scored.md`. In the
agentic doc, add a header note that its "tiers, no numbers" decision is superseded.
*Gate:* the doc is committed before any code.

**M1: scorer and schema (pure, no DB).**
- `backend/app/agent/scoring.py` (new). `WEIGHTS`, `AREA_CREDIT`, `STATUTORY_FUNDER_TYPES`,
  `gate(checks, funder_type, s135) -> (status, reasons)` and
  `score(checks, ...) -> (total, breakdown, coverage)`. It sits beside `validator.py` in spirit:
  no pool, no async, no settings.
- `backend/app/agent/assessment.py` changes:
  - Drop `fit_tier`.
  - Add these to `Check`: `level: Literal["district","state","pan_india","regional"] | None`. A
    validator requires it on a `met` area and forbids it on other codes.
  - Add these to `FunderAssessment`: `funder_type: str | None`, `section_135_bound: bool | None`,
    `shared_districts: int = 0`.
  - Add `@computed_field` properties `gate`, `gate_reasons`, `score`, `breakdown`, `coverage` and
    `rank_key`. Each calls into `scoring.py`.
  - Avoid a circular import: `scoring.py` takes plain `(code, outcome, level)` tuples, so it
    imports nothing from `assessment.py`.
  - Keep `extra="forbid"`. A model that echoes `gate` or `score` is rejected, and `ToolStrategy`
    retries.
- `backend/app/agent/build.py`: change the ASSESSOR `description` from tiers to "returns cited
  checks; gate and score are computed".
- Tests:
  - `tests/test_scoring.py`: table-driven, built from hand-made `Check`s. Cover each gate rule,
    unknown → unverified (never fail), not-applicable → dropped from the denominator, area 20/12/6,
    and an all-met assessment scoring 100.
  - `tests/test_assessment.py`, updated:
    - `FunderAssessment.model_json_schema()` (validation mode) contains no computed field;
    - `model_dump_json()` does contain them;
    - input carrying `gate` or `score` is rejected;
    - the `level` validator.
  - In `tests/test_scoring.py`, two more cases: an unknown funder_type puts the statutory gate at
    `unverified`; and `rank_key` sorts lexicographically in key order.

*Gate:* `cd backend && pytest -m "not integration" && ruff check .` is green.

**M2: prompt and skills.**
- `app/agent/prompts/funder_assessor.md`:
  - delete "The tier" section;
  - `programme` becomes the NGO's `programs` (org_id) tagged with the shared theme;
  - a stated pan-India / regional coverage becomes `area met` with `level`, no longer `unknown`;
  - return `funder_type`, `section_135_bound` and `shared_districts` with their cites;
    `shared_districts` comes only from the assessor and is never passed in;
  - add the best-level rule, the regional-containment rule and "programme needs the shared theme";
  - "This file is the criteria" becomes "This file defines the checks; how they gate and score is
    `scoring.py`";
  - the prompt never names gate, score or weights;
  - keep the unknown ≠ fail rules verbatim.
- `skills/funder-shortlist-brief/SKILL.md`:
  - sections become Eligible / Unverified (with "what to verify") / Removed (gate fail plus the
    cited row) / Not assessed / What to record next;
  - order by the key above;
  - quote the score and coverage as given, never recomputed;
  - delete the "no scores" rule.
- `skills/funder-comparison/SKILL.md`: a gate and score column instead of the tier.
- `skills/funder-matching/SKILL.md`: step 3 counts a country-level `funder_locations` row as a
  shared place. Today's "pan-India is a candidate only when it shares a theme" goes, so those
  funders are assessed and can earn their 30%. That costs little: only 9 funders have
  `funder_locations` rows.
- `app/agent/instructions.md` (rules 12–16): repeat the gate and score as computed; never compute
  or adjust one.
- `CLAUDE.md` "Funder matching is agentic" paragraph: add the one-liner "the assessor judges checks;
  `scoring.py` turns them into gate, score and order".
- `tests/test_prompt.py`: update the tier pins to the new vocabulary, and pin that the prompt names
  no weights (they live in code).

*Gate:* the M1 commands are green. One real run on KABIL × HDFC returns valid JSON with
`gate`/`score` present in the ToolMessage, checked in the Langfuse trace.

**M3: evals.** Add cases to `backend/tests/evals/cases/`, tagged `matching`:
- a funder failing a gate never appears under Eligible or Unverified;
- no unknown is reported as "ineligible";
- the shortlist order matches the key, checked by parsing the assessor ToolMessages from the trace;
- the gate is identical across 3 runs.

*Gate:* `make evals TAG=matching`.

**Later (not this plan): sector weights.** This needs:
- a `funders.industry` column (migration plus catalog entry, a security decision per CLAUDE.md);
- new checks `warmth` (grants / funder_partners), `funding_size` (grants.amount, csr_spend) and
  `capacity_trend` (funder_csr_years, which 14 funders have for 2+ years);
- `target_population` and plant proximity data.

After that, `WEIGHTS` becomes a dict keyed by industry.

## Files

| file | change |
|---|---|
| `backend/app/agent/scoring.py` | **new**: gates, weights, score, coverage |
| `backend/app/agent/assessment.py` | drop `fit_tier`; add `level`, funder fields, computed fields |
| `backend/app/agent/build.py` | ASSESSOR description only |
| `backend/app/agent/prompts/funder_assessor.md` | tier section out; programme, area level, funder fields |
| `backend/app/agent/skills/funder-{matching,shortlist-brief,comparison}/SKILL.md` | new vocabulary and ordering |
| `backend/app/agent/instructions.md`, `CLAUDE.md` | a line each |
| `backend/tests/test_scoring.py` (new), `test_assessment.py`, `test_prompt.py` | as above |
| `docs/features/2026-10-07-funder-matching-scored.md` | M0 |

## Verification

```bash
cd backend && pytest -m "not integration" && ruff check .
make up && make evals TAG=matching          # COSTS MONEY
```

Manual check: in `/ask`, ask "Which funders can KABIL apply to?". The trace should show one
narrowing query, then waves of assessors, each ToolMessage carrying `gate`, `score` and `coverage`.
The answer should list Eligible, then Unverified, then Removed, in key order, and say "not recorded"
(never "ineligible") for unknowns.
