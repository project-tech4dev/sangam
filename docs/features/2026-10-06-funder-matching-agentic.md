# Funder matching, agentic: the agent judges, code only fetches and checks shape

*Approved 2026-10-06. Supersedes `2026-10-06-funder-matching-engine.md` (the deterministic engine,
built through M3 on `feat/matching-engine` and then removed) and its evals plan
`2026-10-06-funder-matching-evals.md`, whose agent-eval tier becomes milestone A4 here.*

## Context

`feat/matching-engine` has the deterministic engine committed through M3: about 4,100 lines,
covering `app/matching/` (evaluators, engine, loader, registry, service, CLI), YAML criteria,
migration `0023_criteria_sets`, five tools, and their tests. The user's verdict: *"too much custom
logic — I need a mainly agentic approach."*

The working tree of this worktree already shows all of that deleted, uncommitted. **The user
confirmed the deletion is theirs and intended**, so A1 commits it.

**Goal:** matching is done by agents reading the database the way they already do. The criteria
are an editable markdown checklist, not YAML plus evaluators. The only new code is a
structured-output schema, one subagent's wiring, and tests.

## The design

```
USER: "Which funders can KABIL apply to?"
  │
ASK SANGAM (supervisor)  ── loads skill: funder-matching (the procedure)
  │ 1. find KABIL: db_query                                  (existing tool)
  │ 2. narrow 200 → ~25: ONE db_query on place + theme       (existing tool)
  │ 3. task → funder-assessor × 25, in waves of MAX_PARALLEL_RESEARCH
  │        each assessor: reads KABIL + one funder via db_query,
  │        applies the criteria in its prompt,
  │        returns FunderAssessment (structured, validated)
  │ 4. rank by the assessors' verdicts, write up             (skill: funder-shortlist-brief)
  ▼
answer with citations
```

This is Import's proven shape (`ingest/agent.py:124-181`): one entity per isolated subagent, a
markdown prompt beside the code, and a `response_format` that makes the reply JSON.

## Written vs agentic

| need | engine plan (written code) | agentic plan |
|---|---|---|
| narrow 200 funders | stage-1 SQL in `evidence.py` | the supervisor writes one `db_query`; the skill gives the shape |
| judge one funder | ~15 evaluator functions + combinators | an assessor subagent reads and judges |
| criteria | YAML + loader + `criteria_sets` table + CLI | **`prompts/funder_assessor.md`**, a plain checklist edited by PR |
| unknown ≠ fail | `basis` logic in code | a rule in the assessor prompt + an enum in the schema |
| ranking / weights | a scorer + ranking key | **tiers, no numbers** (decided): each assessor returns `strong` / `possible` / `weak` / `not_enough_recorded` with reasons; the supervisor groups by tier |
| profiles (`get_org` / `get_funder`) | tool wrappers over the resolver | `db_query`, as before |
| explain one pair / compare | `explain_match` | one or more assessor calls; the supervisor lays them out |
| scale | constant query count | N assessor calls per shortlist (costs below) |

## What we write

| file | what | size |
|---|---|---|
| `app/agent/prompts/funder_assessor.md` | **the criteria**: fit (area, theme, programme), then compliance (12A, 80G, CSR-1, FCRA, Darpan), financial (3 audits, ITR-7, turnover), governance (board, CVs), programme (3+ projects); the unknown ≠ fail rule; cite every check | prose |
| `app/agent/assessment.py` | `FunderAssessment`: `funder_id`, `checks[]` (`code`, `outcome` met/fail/unknown, `basis`, `cites`), `fit_tier` (`strong` / `possible` / `weak` / `not_enough_recorded`), `reasons[]`, `gaps[]` | ~50 lines |
| `app/agent/build.py` | a `funder-assessor` subagent: tools `db_list_tables`, `db_describe_table`, `db_query`; `response_format=FunderAssessment`; its own `filesystem(keep=...)`; model from `ASSESSOR_MODEL` (a cheap one) | ~30 lines |
| `app/agent/skills/` + `/skills/` route | copied from Import (`ingest/agent.py:77-87, 207`): `funder-matching` (the procedure), `funder-shortlist-brief`, `funder-comparison` | markdown |
| `app/agent/instructions.md` | constraints only: matching questions go through the assessor; never call unknown a fail; repeat assessor cites | a few lines |
| tests | the subagent runs only its three tools (the `TestASubagentRunsOnlyTheToolsItsSpecDeclares` pattern); the schema validates; the prompt names its tools | small |
| evals | trajectory gates: the assessor was called, no unknown reported as ineligible, faithful to the assessments | cases |

**Tier rules live in the assessor prompt**, in words, not numbers:
- `strong`: shares area **and** theme, and no compliance check fails.
- `possible`: shares one of area or theme, and no compliance check fails.
- `weak`: no shared area or theme, or a check fails on positive evidence.
- `not_enough_recorded`: too little is known about either side to judge.

The weights (40/25/15/10/10) and the score range are dropped.

## What goes

`app/matching/`, `criteria/*.yaml`, `match_tools.py`, `profile_tools.py`, `match_render.py`, their
tests, the matching make targets, `pyyaml`, and the five tools (the agent returns to 6).

`0023_criteria_sets.sql`: if it was applied to any database, removing it needs a `0024` that drops
the table, not a deleted file. Migrations are append-only.

## Honest costs

| | engine | agentic |
|---|---|---|
| model calls per shortlist | 1 | 1 supervisor + ~25 assessors (cheap model) |
| latency | seconds | waves of 8 → ~3–4 waves, roughly 1–3 minutes |
| same question twice | identical | can differ at the margin; evals measure agreement across 3 runs |
| changing criteria | YAML + `make criteria-activate` | edit the markdown, run `make evals TAG=matching` |
| connections | — | assessors share the pool; bounded by the `MAX_PARALLEL_RESEARCH` / `DB_POOL_MAX_SIZE` rule |

## Milestones

| | ships | gate |
|---|---|---|
| A1 | remove the engine (commit the deletion, plus a `0024` if `0023` was applied); prompt back to facts-via-SQL | `pytest -m "not integration"` green; tool pins back to 6 |
| A2 | `funder-assessor` subagent, `FunderAssessment`, criteria prompt | the subagent tool-set test; one assessor call on KABIL × HDFC returns valid JSON |
| A3 | Ask skills mechanism + `funder-matching`, `funder-shortlist-brief`, `funder-comparison` | a shortlist trace shows narrow → waves of assessors → write-up |
| A4 | evals: trajectory gates, agreement across runs, unknown honesty | `make evals TAG=matching` |

## Verification

```bash
cd backend && pytest -m "not integration" && ruff check .
make up && make evals TAG=matching        # COSTS MONEY: real supervisor + assessor calls
```

Manual: ask *"Which funders can KABIL apply to?"* in `/ask`. The trace shows one narrowing
`db_query`, then assessor calls in waves, then an answer that says *not recorded*, never
*ineligible*, for unknowns.
