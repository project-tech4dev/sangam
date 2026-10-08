# Funder matching in code: org profile, funder profile, compare

*Approved 2026-10-07. Supersedes the subagent half of `2026-10-07-funder-matching-readiness-once.md`;
the checks, gates, weights and scorer of `2026-10-07-funder-matching-scored.md` stay.*

## Context

Even with readiness-once live, one `org-readiness` subagent ran about 35 open-ended `db_query` calls for KABIL. Three things drive that, and a better prompt fixes none of them:

1. It re-confirms rows it already has.
2. It chases citation markers. `db_query` attaches one only when an id column is projected, so the model re-queries "get citation row for 12a".
3. It wanders, for example "sanity check unused".

The user's direction:
- a tool for the funder side;
- a tool for the org side;
- then compare.

**And code does the comparing** (chosen in the question just now), which is the "very deterministic checks" the feature started from.

**Result:** one tool call, `compare_fit`, scores a whole shortlist.
- No subagents.
- No model judging any check.
- Seconds instead of minutes.
- The same answer every run.

## The shape

```
supervisor
  ├ db_query: resolve "KABIL" → org_id 9                   (1 call)
  └ compare_fit(org_id=9, funder_ids=None | [7, 2])        (1 call)
        org_profile(9)            one SQL round, once        ┐ app/repositories/matching.py
        funder_profiles(ids|all)  one SQL round, bulk        ┘ (hand-written SQL, read-only txn)
        rules.judge(org, funder)  → list[Check]               app/agent/rules.py   (pure)
        FunderAssessment(...)     → gate · score · rank_key   assessment.py + scoring.py (unchanged)
  → funder-shortlist-brief / funder-comparison skill writes it up
```

**With `funder_ids` omitted, `compare_fit` also does the narrowing.**
- It scores every funder that shares a place or a theme.
- It counts the rest as "nothing in common recorded" or "nothing recorded".
- So the skill's narrowing `db_query` goes away.

### `org_profile(org_id)`

A dataclass, filled by about 8 fixed SELECTs on one connection.

| field | contents |
|---|---|
| `org` | id, name |
| `districts`, `states` | district → state through `locations.parent_id` |
| `sector_tags`, `csr_slugs` | `tags.meta->>'maps_to'` |
| `programs` | each with its tag ids |
| `identifiers` | by id_type: status, id_value, is_current, valid_until, evidence, source_type |
| `financials` | fiscal_year, total_income, is_audited |
| `documents` | doc_type |
| `office_bearers` | count |
| `partner_lines` | funder_activity partner lines naming the org: id, relationship_status, end_date |

### `funder_profiles(funder_ids | None)`

The same idea, in bulk (`= ANY(%s)`), so the cost is about 6 queries however many funders there are.

| field | contents |
|---|---|
| `funder` | id, name, funder_type, section_135_bound |
| places | districts, states, pan-India, and regions with their member states; `funder_activity` footprint lines plus funder_locations, excluding the `registered` role |
| `registered` | the registered location's country, which gives `foreign_funder` |
| tags | sector tags, csr_sector slugs |
| `eligibility` | the paragraphs under "Its own bar" and "Disqualifiers" in the `funder_eligibility` document |

### `rules.py`: profile pair → checks

Pure functions, one per check. Every met or fail cites `[org:N]`, `[funder:N]` or `[activity:N]` from the profile, which satisfies `Check`'s validators.

**Fit**

- `area`:
  - level `district` on a shared district, otherwise `state`, otherwise `pan_india` on a country row, otherwise `regional` on a region containing an org state;
  - `fail` when both sides have places and none is shared;
  - `unknown` when either side has none;
  - `shared_districts` is the count.
- `theme`:
  - `met` on a shared sector tag or a shared Schedule VII slug;
  - `fail` when both sides have tags and none is shared;
  - otherwise `unknown`.
- `programme`:
  - `unknown` when the org has no programs;
  - `met` when a program's tag is in the shared set;
  - `fail` when `theme` failed, or when every program is tagged and none is shared;
  - otherwise `unknown`.

**Organisation's own checks**

- `reg_12a`, `reg_80g`, `csr_1`, `darpan`, `pan`, `reg_no`, `fcra`:
  - `met` on a current identifier row (id_type `12a`, `80g`, `csr1`, `darpan`, `pan`, `reg_no`, `fcra`) with status `registered` or `provisional` and an id_value;
  - `fail` when a current row is cancelled, expired, suspended or surrendered, or a held row's `valid_until` is past;
  - `unknown` / `claimed` when the held row's evidence is `claimed`, and `unknown` when held and lapsed rows conflict;
  - `unknown` / `searched_not_found` on `not_found`;
  - `unknown` / `not_researched` otherwise (`applied`, `check_blocked`, no row).
- `audits_3y`:
  - `met` on 3 audited years, or 3 audit documents (`audited_financials`, `financial_statement(s)`);
  - `fail` only when a recent year is recorded `is_audited = false`;
  - otherwise `unknown`, noting "N of 3".
- `itr_7`, `team_cvs`: `met` on a matching doc_type, otherwise `unknown`.
- `board`: `met` on 3 or more office bearers, otherwise `unknown`, noting "N of 3".
- `projects_3`:
  - `met` on 3 or more concluded partner lines (`relationship_status = concluded` or ended) plus completed programs;
  - otherwise `unknown`, noting "N of 3".

**The funder's own bars**

- `funder_bar`: one check per bar paragraph, always `unknown`, with note "needs review (document N): <criterion>".
  - Free text cannot be judged in code, and the write-up names it. There are none locally today.
- `turnover`: not emitted until bars are structured.

**Reasons** are generated lines such as "Shares Udalguri district [org:9] [funder:7]".

The doc-type and credential value sets are module constants, so a new spelling is a one-line change.

## Milestones (one commit each, on `feat/matching-engine`)

**M0: design doc.**
- `docs/features/2026-10-07-funder-matching-in-code.md`, from this plan.
- A "superseded" line on the readiness-once doc.
- *Gate:* committed before code.

**M1: profiles, rules and the tool, with no change to the agent wiring.**
- `app/repositories/matching.py`:
  - `org_profile` and `funder_profiles`;
  - read-only transaction plus `statement_timeout`, the same guards as `sql/executor.py`.
- `app/agent/rules.py`: `judge(org, funder) -> PairResult(checks, shared_districts, foreign_funder, reasons)`.
- `app/agent/tools/matching_tools.py`: `compare_fit(org_id, funder_ids=None)`.
  - It builds a `FunderAssessment` per funder (existing model, computed gate, score and rank_key).
  - It returns them sorted by rank_key, plus the two not-assessed counts, as compact JSON.
  - It catches every exception and returns `"compare_fit failed: …"`.
- Tests:
  - `tests/test_rules.py` (pure, KABIL-shaped fixtures):
    - each check's met, fail and unknown paths;
    - a missing row is never fail;
    - area levels;
    - the programme-follows-theme rule.
  - `tests/test_matching_tools.py`: the tool with the repository monkeypatched.
  - `tests/test_matching_sql.py` (`integration`): KABIL × Axis gives area met at district (Udalguri), and identifiers met with `[org:9]`.
- *Gate:* `pytest -m "not integration"`, `pytest -m integration tests/test_matching_sql.py`, and ruff.

**M2: wire it in, and remove the subagents.**
- `build.py`:
  - `TOOLS` gains `compare_fit` (7 tools);
  - remove `READINESS`, `ASSESSOR`, `subagents=` and `state_schema`.
  - With no subagents there is no `task` tool.
- Delete:
  - `state.py`, `prompts/org_readiness.md`, `prompts/funder_assessor.md`;
  - `ReadinessAssessment`, `PairAssessment` and `merge` in `assessment.py`;
  - `test_readiness_state.py`.
- Keep `Check`, `FunderAssessment` and `scoring.py`.
- Skills:
  - `funder-matching`: resolve the org, then `compare_fit(org_id)`, then load funder-shortlist-brief.
  - `funder-comparison`: resolve the ids, then `compare_fit(org_id, [ids])`.
  - `funder-shortlist-brief`: "needs review" bars go in their own line.
- `instructions.md`:
  - rules 12–16 now say "compare_fit judges; never judge fit yourself; repeat its output";
  - describe the tool there (a test requires every tool to be named).
- `frontend/features/ask/lib/toolLabels.ts`: `compare_fit`, labelled "Comparing funders".
- `CLAUDE.md`:
  - the tool count is seven;
  - the matching paragraph is rewritten;
  - "ONE path to the database" gains its one exception: `compare_fit` reads through `repositories/matching.py`, because the checklist is fixed, so the query is fixed.
- Tests:
  - `test_harness.py`: 7 tools, no `task`, no subagents.
  - `test_prompt.py`: the subagent prompt tests are deleted.
  - Evals:
    - `assessments_in` reads the `compare_fit` ToolMessage;
    - the `readiness_before_pairs` gate becomes `compare_fit_once`.
- *Gate:* the unit suite and ruff, then `npm run lint` in the frontend.

## Verification

- `docker restart sangam-backend-1`, then ask "How does KABIL fit Axis Bank Foundation?". The trace should show:
  - the skill read;
  - one `db_query` to resolve the ids;
  - one `compare_fit`;
  - the answer.
- "Which funders can KABIL apply to?" should take the same 4 steps, with the shortlist in rank_key order.
- Run it twice: the gates and scores should be identical.
- Live evals (the user runs them): `--eval-tag matching`.
