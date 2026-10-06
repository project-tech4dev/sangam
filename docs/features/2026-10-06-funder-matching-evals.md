# Evaluating funder matching: is the code right, is the matching good, does the agent say it right

*Draft v1 — 2026-10-06. Companion to `2026-10-06-funder-matching-engine.md`.*

## Goal

**Every change — to the criteria file, an evaluator, the prompt or a skill — is caught by a
test before it reaches a fundraiser, and the cheap tests catch most of it.**

Matching can be wrong in four different places. Each needs its own kind of test:

| question | what can be wrong | tier | costs |
|---|---|---|---|
| Does the engine do what the YAML says? | an evaluator bug; unknown scored as fail | **1 — engine** | free, no model |
| Did a criteria edit move the right funders? | `years: 3 → 2` moved 40 funders, not the expected 4 | **2 — criteria diff** | free, no model |
| Is the matching actually *good*? | the ranking disagrees with a programme lead | **3 — ground truth** | free to run; costs people's time to label |
| Does the agent report it faithfully? | wrong tool, invented number, "not eligible" for unknown, skill never loaded | **4 — agent** | money — real model calls |

The order matters. Tiers 1–3 never call a model, so they run on every PR. Tier 4 runs on
the `canary` tag per PR and in full before a merge to `master`.

## What exists today

| piece | file | can it test matching? |
|---|---|---|
| eval runner | `backend/tests/evals/harness.py` — `run_agent()` returns the answer, the `db_query` SQL and citations | partly: it **cannot see other tool calls or skill reads** |
| gates | `score()`: `gold_sql`, `expected_value`, `required_citations`, `forbidden_citations`, `must_mention`, `must_not_mention`, `must_decline` | phrase gates yes; **no trajectory gates** |
| cases | `backend/tests/evals/cases/golden.jsonl` (+ the shortlist/assessment cases from `509d73c`, `cee7fce`) | rewritten for the tools |
| gating | `--run-evals`, `--eval-tag`, `expected_failure` → `xfail(strict=True)` | reused as-is |
| unit test rule | no database; `client_for` + monkeypatched repositories | reused for tier 1 |

## Tier 1 — the engine is right

**Pure evaluator tests** — `backend/tests/test_matching_rules.py`, no database. Every evaluator
in `app/matching/rules.py` is tested in all its states with hand-built evidence:

> **The rule:** zero rows is *unknown*, never *fail*.
> **Example:** KABIL with no `org_financials` rows gets `audited_3y: unknown — 0 of 3 years
> recorded`. With one audited year recorded it gets `unknown — 1 of 3`. Only a recorded
> `credential_events` row with `event='cancelled'` turns 12A into `fail`.
> **Why it matters:** this is the one bug that makes the ranking lie, so every evaluator gets an
> explicit zero-rows case.

Four properties hold for every evaluator, parametrised over the registry so a new rule inherits
them:

| property | test |
|---|---|
| **zero evidence → unknown** | empty evidence → `state == "unknown"` |
| **monotonic** | adding a supporting row never moves met → unknown or unknown → fail |
| **params are honoured** | the same evidence at `years: 3` and `years: 2` gives different states where it should |
| **cites what it used** | every `met`/`fail` carries at least one row reference |

**Loader tests** — `tests/test_matching_config.py`: an unknown rule name, a misspelt param
(`yeers`), a duplicate `code`, an `applies` value outside the three, and a `has_document` naming a
type missing from `document_types` all **refuse to load**.

**Golden pairs** — `backend/tests/matching/cases/*.yaml`, integration-marked. A fixture
database built by a fixture SQL file — not the seed, which research keeps changing — holds about
six orgs and twelve funders designed to hit every branch. Each case states the expected state per
check:

```yaml
- org: fixture-assam-education        # districts in Assam, education tags, 12A, no financials
  funder: fixture-pan-india-csr       # stated pan-India, education clause, no footprints
  criteria: tests/matching/criteria.test.yaml   # pinned, so a real edit never breaks it
  expect:
    stage1: {area: unknown, theme: met, programme: unknown, passes: true}
    stage2: {reg_12a: met, csr_1: unknown, audited_3y: unknown, turnover: no_bar_recorded}
```

**Scale test** — integration-marked. Insert 200 synthetic funders, run `match_funders`, and
assert **three queries** (a counting wrapper on the connection) and under one second. It fails
the day someone adds a per-funder query.

## Tier 2 — a criteria edit moves what it should

`make match-diff FROM=<active version> TO=<draft version>` loads both versions from `criteria_sets`, runs both
over **every org × every funder** in the chosen database, and prints what moved:

```
criteria v4 (active) → v5 (draft)        audited.years: 3 → 2
  KABIL      HDFC Bank        audited_3y  unknown → met      (2 audited years recorded)
  Goonj      SBI Foundation   audited_3y  unknown → met
  stage-1 survivors unchanged · 2 checks moved across 11 orgs × 42 funders
```

The diff goes in the PR description for any criteria change. That makes review concrete: the
reviewer reads *which funders moved*, not just *which number changed*. No model, so it is free;
it is pure engine code over the database.

## Tier 3 — the matching is good

Tiers 1 and 2 prove the code does what the YAML says. They cannot say the YAML is right. That
needs human judgement, collected once and reused.

**A labelled set** — `backend/tests/matching/labels.yaml`. A programme lead labels about 30
org × funder pairs. The pairs mix strong fits, clear non-fits and thin-data funders:

```yaml
- org: kabil
  funder: hdfc-bank-limited
  would_approach: yes            # yes | no | not enough known
  must_flag: [csr_1, audited_3y] # gaps a reviewer would raise
  labelled_by: programme-lead
  labelled_at: 2026-10-08
```

`make match-quality` reports, against the labels:

| metric | meaning | first target |
|---|---|---|
| stage-1 recall | of the pairs labelled *yes*, the share that survive stage 1 | ≥ 0.9 — the funnel must not drop real fits |
| precision@10 | of each org's top 10, the share labelled *yes* | tracked, no threshold yet |
| gap recall | of `must_flag` checks, the share the engine reports as unmet or unknown | ≥ 0.9 |
| unknown honesty | of pairs labelled *not enough known*, the share the engine puts in the *not enough recorded* block | 1.0 |

**The 8 hand scores as a sanity check.** `fit_scores` holds 8 manual rubric scores for KABIL
against four funders. The engine's ordering of those four should broadly agree with them. This is
reported, not gated: rubric v2 and the criteria file measure different things.

Stage-1 recall is the gate. A funnel that drops a funder the team would approach is worse than
one that keeps too many, because stage 2 and the fundraiser can still discard the extras.

## Tier 4 — the agent says it right

### Harness changes — `backend/tests/evals/harness.py`

`run_agent()` today keeps only `db_query` SQL. It grows a **trajectory**: every tool call's name
and arguments, read from the `AIMessage.tool_calls` already in `state["messages"]`. A skill read
is a `read_file` call whose path starts `/skills/`. `CaseResult` gains `tools: list[str]` and
`skills: list[str]`, and `score()` gains five gates:

| gate | fails when | example |
|---|---|---|
| `expected_tools` | a listed tool was never called | shortlist must call `match_funders` |
| `forbidden_tools` | a listed tool was called | shortlist must not call `db_query` — no rebuilding the funnel |
| `max_tool_calls` | more calls than the budget | shortlist ≤ 2 |
| `skills_read` | a listed skill's `SKILL.md` was not read | readiness question reads `application-readiness` |
| `faithful_to_tool` | the answer names a funder or a number absent from the tool output | invents "₹50 lakh minimum", or ranks a funder the tool never returned |

`faithful_to_tool` is the important one. Two checks, both plain string work, no judge model:

- every `[funder:N]` in the answer appears in a `match_funders`/`explain_match` result;
- every number with a unit in the answer (`3 years`, `₹1 crore`, `5 of 7`) appears in a tool
  result.

### Cases — `backend/tests/evals/cases/matching.jsonl`

A new file, loaded by the existing `load_cases()`. The shortlist and assessment cases already in
`golden.jsonl` move here and get trajectory gates.

| id | question | gates | tags |
|---|---|---|---|
| `shortlist-one-call` | Which funders fit KABIL? | `expected_tools: [match_funders]`, `forbidden_tools: [db_query]`, `max_tool_calls: 2`, `faithful_to_tool` | canary |
| `shortlist-unknowns-named` | Which funders fit Goonj? | `must_mention: [not enough recorded]`, `must_not_mention: [poor fit, low fit]` | canary |
| `readiness-unknown-not-ineligible` | What does KABIL need for HDFC Bank? | `expected_tools: [explain_match]`, `must_not_mention: [not eligible, ineligible]`, `skills_read: [application-readiness]` | canary |
| `readiness-statutory-first` | What does KABIL need for HDFC Bank? | `must_mention: [CSR-1]`; CSR-1 named before ITR-7 (an `order` gate) | — |
| `comparison-skill` | Compare HDFC Bank and SBI Foundation for KABIL | `skills_read: [funder-comparison]`, `expected_tools: [explain_match]` | — |
| `criteria-version-stated` | Which funders fit KABIL? | `must_mention: [criteria v]` plus the active version number | — |
| `no-threshold-invented` | What turnover does HDFC require? | `faithful_to_tool`, `must_mention: [no bar recorded]` | canary |
| `ambiguous-org` | Which funders fit the Assam trust? | `max_tool_calls: 1`, asks which org | — |
| `profile-one-call` | Tell me about KABIL | `expected_tools: [get_org]`, `forbidden_tools: [db_query]`, `max_tool_calls: 1`, `must_mention: [not recorded]` | canary |
| `find-funders-by-place` | Which CSR funders give in Assam? | `expected_tools: [find_funders]`, `forbidden_tools: [db_query]`, `faithful_to_tool` | canary |
| `find-orgs-unknown-separate` | Which NGOs in Assam have 12A? | `expected_tools: [find_orgs]`, `must_mention: [not recorded]`, `must_not_mention: [do not have 12A]` | — |
| `match-orgs-reverse` | Which NGOs fit HDFC Bank? | `expected_tools: [match_orgs]`, `forbidden_tools: [db_query]`, `skills_read: [ngo-shortlist-brief]` | — |
| `fact-stays-sql` | How much did HDFC spend in FY23? | `expected_tools: [db_query]`, `forbidden_tools: [match_funders]` | — |

**Gate on behaviour, not on exact rankings.** Tier 4 runs against the seeded local database,
and research changes that data every week. A case asserting *"HDFC is ranked 3rd"* goes red for
the wrong reason. Exact states belong to tier 1's fixtures; tier 4 asserts that the right tool
ran, nothing was invented, and unknowns stayed unknown.

### Write-up quality — optional judge

Whether a readiness list is *useful* is a judgement. `MATCH_EVAL_JUDGE_MODEL`, off by default
like `SQL_AUDIT_MODEL`, scores the skill outputs against a short rubric: actionable, ordered,
statutory first, no padding. It is reported, never gated, until enough runs show it agrees with
a person.

## Milestones

Each lands with the engine milestone it tests (engine plan, §Milestones).

| | ships | with engine | gate |
|---|---|---|---|
| E1 | evaluator unit tests, the four properties, loader tests | M1, M2 | `pytest -m "not integration"` |
| E2 | fixture database + golden pairs + scale test | M2 | `pytest -m integration tests/matching` |
| E3 | `make match-diff` | M2 | runs on a one-line YAML edit; output in PR |
| E4 | harness trajectory + five gates + `matching.jsonl` | M3, M3b | `make evals TAG=canary` |
| E5 | labelled set + `make match-quality` | after M3, once a programme lead has labelled 30 pairs | stage-1 recall ≥ 0.9 |
| E6 | optional judge | after E4 | reported only |

E1–E3 cost nothing and cover the riskiest bugs, so they come first. E5 depends on people's time
and can trail without blocking anything.

#### E4 in detail — the harness change

- `harness.py`: collect `(name, args)` for every `AIMessage.tool_calls` entry; derive `skills`
  from `read_file` paths under `/skills/`; add the five gates to `score()`.
- `tests/evals/test_harness_gates.py` (no model, no database): feed `score()` hand-built
  `CaseResult`s and assert each gate passes and fails when it should — the harness gets tested
  before it tests the agent.
- `CITATION` already matches `funder` and `org`; no new marker.

## Verification

```bash
cd backend
pytest tests/test_matching_rules.py tests/test_matching_config.py tests/evals/test_harness_gates.py
pytest -m integration tests/matching                     # fixture DB, golden pairs, 3-query scale test
make match-diff FROM=<active> TO=<draft>                              # after a YAML edit
make match-quality                                       # once labels.yaml exists
make evals TAG=canary                                    # COSTS MONEY
make evals                                               # full, before a master merge
```

## Open questions and risks

1. **Who labels tier 3, and when?** About 30 pairs is a few hours for a programme lead. Until
   then, tier 3 has no data and stage-1 recall is unmeasured.
2. **Labels age.** A pair labelled *not enough known* becomes wrong once research lands. Each label
   carries `labelled_at`, and `match-quality` warns when the evidence behind a pair changed since.
3. **`faithful_to_tool` is string matching.** "three years" vs "3 years" needs normalising, which
   `sql_compare.answer_contains_value` already does for numbers — reuse it.
4. **Eval spend.** The canary set is four cases; measure the cost of the first run and record it here.
   The full set runs before a merge, not per push.
5. **Skill-read gates may flake.** The model decides whether to load a skill. If `skills_read`
   fails intermittently, the fix is the skill's frontmatter description, not loosening the gate.
