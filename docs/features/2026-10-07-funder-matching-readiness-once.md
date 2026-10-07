# Funder matching, option A: judge the organisation once, then only what depends on the funder

*Approved 2026-10-07. Builds on `2026-10-07-funder-matching-scored.md`: the gates, weights and
scorer stay; who judges which check, and how the halves meet, changes.*

*Superseded 2026-10-07 by `2026-10-07-funder-matching-in-code.md`: one org-readiness run still
made ~35 open-ended queries, so code now fetches both profiles and judges every check.*

## Context

Scored matching shipped on `feat/matching-engine` (`424a71f..676f103`, design in
`docs/features/2026-10-07-funder-matching-scored.md`). It works the way it was designed, but
"Which funders can KABIL apply to?" ran about **50 queries for 10 candidate funders**, for three
reasons:

1. **12 of the 17 checks are about the organisation alone**: reg_12a, reg_80g, csr_1, darpan, pan,
   reg_no, fcra, audits_3y, itr_7, board, team_cvs and projects_3. All 10 assessors re-read and
   re-judge them.
2. **Assessors can disagree on those 12**, because each judges KABIL's 12A on its own. KABIL's score
   then differs between funders for reasons unrelated to the funder, which breaks the "same checks,
   same score" promise.
3. Each assessor `db_describe_table`s the tables it touches before querying, and `ASSESSOR_MODEL` is
   empty by default (`app/core/config.py:42`), so every assessor runs on the main model.

The user chose **Option A**:
- One `org-readiness` subagent judges the 12 org-only checks **once**.
- Each `funder-assessor` judges only the checks that depend on the funder.
- **Code** merges the two halves and scores them with the existing `scoring.evaluate`.
- The model still judges every check, and no model ever copies another's output.

Target for KABIL: about 3–5 readiness queries plus 10 × 1–2 pair queries, **roughly 15–25 instead
of 50**. Every funder sees identical readiness.

## The design

```
supervisor (funder-matching skill)
  1. resolve org, ONE narrowing db_query                          (unchanged)
  2. task → org-readiness (ONCE, its own message, before any wave)
       returns ReadinessAssessment: 12 org-only checks, cited
       after_agent hook writes state["org_readiness"][org_id] = {checks, assessed_at}
       deepagents merges that key back into the parent's state  (subagents.py:731)
  3. waves of task → funder-assessor
       inherits parent state, so org_readiness comes with it     (subagents.py:806)
       returns PairAssessment: area · theme · programme · turnover? · funder_bar* + funder facts
       after_agent hook: readiness[org_id] + pair → FunderAssessment (existing model)
                         → replaces structured_response → model_dump_json() → supervisor
       no readiness in state → error text "run org-readiness for org N first", never a verdict
  4. funder-shortlist-brief                                        (unchanged)
```

**Reused unchanged:** `FunderAssessment` with its computed gate, score, coverage and rank_key, its
validators (including `_one_check_per_code`, which catches any overlap between the two halves), and
`scoring.evaluate`. The merge simply builds the existing model from two check lists.

### Decisions

- **One state key, declared once.** Add `class AskState(DeepAgentState)` with
  `org_readiness: Annotated[NotRequired[dict[int, dict]], _merge_readiness]`, passed as
  `create_deep_agent(state_schema=AskState)`. deepagents forwards it to raw subagent specs, so the
  channel exists in all three graphs.
  - **The reducer is required.** A wave returns the inherited key from 8 parallel tasks in one
    superstep; a plain channel raises `InvalidUpdateError`.
  - The pattern to copy is `files` with `_file_data_reducer` (`deepagents/middleware/filesystem.py:1114`).
- **The check codes split into two disjoint `Literal`s.**
  - `ReadinessCode`: the 12 above.
  - `PairCode`: area, theme, programme, turnover, funder_bar.
  - `CheckCode` = the union. `Check` is unchanged, with a subclass or validator per side so each
    half refuses the other's codes.
- **FCRA applicability moves to a pair fact.** Readiness always returns `fcra`, since it never sees
  the funder. `PairAssessment` gains `foreign_funder: bool | None`. In `scoring.evaluate`, `fcra`
  counts toward compliance only when `foreign_funder is True`, replacing "only when returned".
  `turnover` stays on the pair side: the bar is the funder's. It is the one pair check that reads
  `org_financials`.
- **Readiness persists per conversation.** The parent state is checkpointed by thread, so a
  follow-up such as "compare X and Y for KABIL" reuses it at no cost.
  - It carries `assessed_at`.
  - The skill says "readiness assessed earlier in this conversation" when it reuses it, and tells
    the supervisor to re-run `org-readiness` after the user imports new data.
- **No describe calls in the hot path.** Both subagent prompts list the exact tables and columns
  they need, and give a query recipe: readiness ~3 joined queries, pair 1–2. `db_describe_table`
  stays available only for recovering from a failed query.
- **No new tool**, so the six-tool pin holds. Ask Sangam now declares two subagents.

## Milestones (one commit each, on `feat/matching-engine`)

**M0: design doc.** Write this plan as `docs/features/2026-10-07-funder-matching-readiness-once.md`,
and add a one-line "superseded in part" note to the scored doc. *Gate:* committed before any code.

**M1: schemas, merge and a spike that pins the mechanism (no model calls).**
- `app/agent/assessment.py`:
  - add `ReadinessCode` / `PairCode`;
  - add `ReadinessAssessment` (org_id, org_name, checks, gaps);
  - add `PairAssessment` (org_id, funder_id, funder_name, funder_type, section_135_bound,
    foreign_funder, shared_districts, reasons, checks, gaps);
  - add `merge(readiness: dict, pair: PairAssessment) -> FunderAssessment`, a pure function: gaps
    pair-first, then readiness.
  - `FunderAssessment` gains `foreign_funder`. It is no longer anyone's `response_format`.
- `app/agent/scoring.py`: an `evaluate(..., foreign_funder)` parameter; `fcra` applicability
  follows it.
- `app/agent/state.py` (new): `AskState`, `_merge_readiness`, and the two `after_agent` hooks:
  `record_readiness` (readiness subagent) and `merge_with_readiness` (pair subagent).
- Tests:
  - `tests/test_assessment.py`:
    - the code sets are disjoint and their union is `CheckCode`;
    - each half refuses the other's codes;
    - `merge` output validates and scores like a hand-built `FunderAssessment`.
  - `tests/test_scoring.py`: `fcra` is in the denominator only when `foreign_funder` is True.
  - `tests/test_readiness_state.py` (new):
    - the reducer merges two orgs and tolerates 8 identical parallel writes;
    - `record_readiness` writes the key;
    - `merge_with_readiness` replaces `structured_response` with a scored `FunderAssessment`, and
      returns the error text when readiness is missing;
    - **spike:** a minimal `create_deep_agent` run on a fake chat model with one isolated
      subagent shows that a key written by the subagent's hook reaches the parent state, and that
      a sibling subagent launched afterwards receives it. If this fails, stop and re-plan before
      M2.

*Gate:* `cd backend && pytest -m "not integration" && ruff check <touched files>`.

**M2: wire both subagents, prompts and skills.**
- `app/agent/build.py`:
  - add `READINESS` (tools `ASSESSOR_TOOLS`; `ToolStrategy(ReadinessAssessment, handle_errors=True)`;
    its own `filesystem_tools(backend)`; middleware `[record_readiness]`);
  - `ASSESSOR` → `ToolStrategy(PairAssessment)` plus `[merge_with_readiness]`;
  - pass `state_schema=AskState`;
  - `ASSESSOR_MODEL` applies to both subagents;
  - update the descriptions.
- `app/agent/prompts/org_readiness.md` (new): the 12 org-only checks moved verbatim from
  `funder_assessor.md` (the unknown ≠ fail rules, "a count below a bar is not evidence"), its table
  and column list, a 3-query recipe, and its three tools named.
- `app/agent/prompts/funder_assessor.md`:
  - keep only the funder facts and area, theme, programme, turnover and funder_bar;
  - add `foreign_funder`;
  - add the table and column list and a 1–2 query recipe;
  - it still names no gate or score.
- Skills:
  - `funder-matching`: a new step between narrowing and waves, "run org-readiness once, in its own
    message, and wait"; reuse it from earlier in the thread unless the user imported data since;
  - `funder-comparison`: the same readiness-first step;
  - `funder-shortlist-brief`: one line, "readiness is judged once for the organisation; it is the
    same for every funder".
- `app/agent/instructions.md` rules 11–13: readiness first, then waves; a "run org-readiness
  first" reply means launch it, never judge it yourself.
- `CLAUDE.md`, matching paragraph: two subagents and the state handoff, one sentence each.
- Tests that go red and get updated:
  - `test_harness.py::test_ask_sangam_advertises_exactly_the_funder_assessor` → two subagents;
  - `TestASubagentRunsOnlyTheToolsItsSpecDeclares` walks `org-readiness` too;
  - a new test that the `org_readiness` channel exists in all three compiled graphs;
  - `test_prompt.py`: the readiness prompt names its tools and has no gate, score or tier words;
    the assessor prompt no longer names a readiness code.
- Evals:
  - harness gate `readiness_before_pairs`: the readiness ToolMessage index is before the first
    merged reply, and there is exactly one readiness run per org;
  - add both gates to `match-kabil-shortlist`.

*Gate:* unit suite green, then the user runs the KABIL × Oil India comparison case live.

## Files

| file | change |
|---|---|
| `backend/app/agent/assessment.py` | code split, `ReadinessAssessment`, `PairAssessment`, `merge`, `foreign_funder` |
| `backend/app/agent/scoring.py` | `foreign_funder` decides `fcra` |
| `backend/app/agent/state.py` | **new**: `AskState`, reducer, two hooks |
| `backend/app/agent/build.py` | second subagent, middleware, `state_schema` |
| `backend/app/agent/prompts/org_readiness.md` | **new** |
| `backend/app/agent/prompts/funder_assessor.md` | pair checks only, schema list, recipe |
| `backend/app/agent/skills/funder-{matching,comparison,shortlist-brief}/SKILL.md` | readiness-first step |
| `backend/app/agent/instructions.md`, `CLAUDE.md` | a line each |
| `backend/tests/test_{assessment,scoring,readiness_state,harness,prompt}.py`, `tests/evals/*` | as above |

## Verification

```bash
cd backend && pytest -m "not integration" && ruff check app/agent tests
```

**The user's step, outside the code:** set `ASSESSOR_MODEL=anthropic:claude-haiku-4-5` in `.env`. It
now covers both subagents and is the largest single saving on tokens.

Live check (the user runs it; it tests this branch's code in-process, which the docker `/ask` does
not):

```
! set -a; . /Users/siddhantsingh/Documents/sangam/.env; set +a; cd /Users/siddhantsingh/Documents/sangam/.claude/worktrees/matching-engine/backend && TEST_DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam /Users/siddhantsingh/Documents/sangam/backend/.venv/bin/python -m pytest tests/evals --run-evals --eval-tag matching -q -p no:warnings
```

Success looks like:
- one `org-readiness` run before the first wave;
- every funder's readiness checks identical;
- the gate, score and rank_key present in each reply;
- about 15–25 `db_query` calls in total for KABIL (count them in the trace, or add a counter to
  `CaseResult`).
