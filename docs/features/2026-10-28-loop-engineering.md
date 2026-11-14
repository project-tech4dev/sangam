# Loop engineering: make the evals, checks and pulls Sangam already has run as loops

Status: **Draft v1**, 2026-10-28. No branch yet. Builds on `2026-10-16-ask-efficiency.md` (its targets
are the metric for M2) and on the research in
[ai-learnings: loop-engineering.md](https://github.com/siddhant3030/ai-learnings/blob/loop-engineering-research/research/loop-engineering.md)
(§4 techniques, §5 event-driven / verification / hill-climbing). Paths are relative to `backend/` unless
they say otherwise.

## 1. Goal

**Every change to an agent is scored before it merges, every "check" either gates or is labelled
advisory, and every run has a spending ceiling.**

Loop engineering means designing the system that prompts and checks the agents, instead of doing it
by hand. The research's rule for the order: **build the verifier first, then improve the agent against
it, then automate when it runs.** Sangam is unusually far along: the eval harness, Langfuse experiments
and per-span tracing exist. What's missing is wiring them into loops.

| measure | today | target |
|---|---|---|
| Ask cost / model calls / tool calls (canary set) | $0.87 / 21 / 26 (trace `5bfdbc85`) | under $0.25 / under 8 / under 8 |
| Ask eval cases | 11 (`tests/evals/cases/golden.jsonl`) | 30–50, split train / held-out |
| Run-to-run noise on the canary set | not measured | measured; known before any change is judged |
| Evals in CI | none (`.github/workflows/ci.yml`) | `make evals TAG=canary` on PRs touching `app/agent/` |
| Human verdicts scored in Langfuse | 0 (only `answer_audit`) | `suggest_edit` outcome + section edits |
| Runs with a spending ceiling | none (call caps only) | Ask, Pitch, Import |
| Scheduled agent pulls | 0 (`make calls-pull` / `news-pull` by hand) | 1 daily, report-only |

## 2. What exists today

**Evals.** `tests/evals/` (`make evals [TAG=canary|cost|import]`). The grader in `harness.py:150-216` is
fully deterministic: it re-runs the gold SQL, checks required and forbidden citations, `must_mention`,
`must_decline` and `max_calls`. `experiment.py` posts each run to the Langfuse dataset `ask-golden` as a
`branch-sha` run, with pass rate, model and tool calls, tokens and seconds. About $0.10 per case. The
Import canary has 2 cases and takes about 15 minutes with Tavily.

**Tracing.** `integrations/tracing.py` names the traces `sangam_ask`, `sangam_import`, `sangam_proposal`
and `sangam_proposal_reader`, and puts the caller, org and model on every span. The only score posted is
`answer_audit` (`agent/middleware.py:199`).

**Checks inside the agents.**

| check | where | gates? |
|---|---|---|
| sqlglot validator, allowlist, read-only transaction | Ask (`docs/SQL_AGENT.md`) | yes |
| `trace.check`: every number, place and name sits in a cited fact | Pitch (`proposals/trace.py:79`) | yes |
| `SaveRefusal`: no field left without a finding or a gap | Import (`ingest/middleware.py:190`) | yes |
| `answer_audit`: Haiku second opinion | Ask (`agent/middleware.py:199`) | **no**: adds a caveat only |
| `research_rubric`: Haiku grader, one revision | Import (`ingest/middleware.py:509`) | partly; self-contradicts (§3.2) |
| Section grade 0–2 | Pitch (`proposals/tools/writing_tools.py:110`) | no |

**Limits.** Ask: 25 model calls, 5 failed SQL attempts, 3 `compare_fit`. Import: call budgets, 8
parallel researchers. Pitch research: at most `max_parallel_research` researchers at once
(`proposals/readers.py:311`). No model has an effort or thinking setting (`core/config.py`,
`agent/models.py`), and no run has a token or dollar ceiling.

**Scheduled work.** One cron, `/health` every 5 minutes (`vercel.json`). No queue, worker or webhook.

## 3. Plan

### 3.0 Prerequisites

- Merge the Ask eval M1 and the caller-on-every-span tracing. Both are marked "(unmerged)" in
  `docs/CHANGELOG.md`, and M1 and M2 below depend on them.
- Find out what happened with `.claude/scheduled_tasks.lock` (8 Oct). Someone appears to have tried
  `/loop` once.

### 3.1 M1: Hill-climbing loop on Ask

The loop: make one change, score it, keep it if the score improves on both sets, revert it if not,
repeat. Method from Anthropic's `/claude-api hillclimb` and Cline's hill-climbing guide.

1. **Measure noise.** Run `make evals TAG=canary` 3–5 times on an unchanged branch (about $1 each).
   Record the spread of the pass rate and of cost per case. A change smaller than the spread isn't
   evidence of anything.
2. **Grow the set from production.** Pull 20–40 `sangam_ask` traces from Langfuse where `answer_audit`
   was 0 or cost was over $0.50, and write them up as golden cases with gold SQL. Split them at random
   with a fixed seed into **train** (the climber reads these failures) and **held-out** (never read
   while tuning).
3. **Climb, one change per round.** Keep a change only if the held-out pass rate doesn't drop and cost
   or calls go down. If train improves while held-out stays flat, treat it as overfitting and revert.
   Order of changes:
   1. The fixes `2026-10-16-ask-efficiency.md` already found: clearing old tool output breaks the
      prompt cache, `compare_fit` output is dropped and re-called, and the model guesses table names.
   2. **Effort and thinking for each model tier.** Add the setting to `core/config.py` and
      `agent/models.py`, then tune it per agent and subagent.
   3. Tool descriptions, then the system prompt.
4. **Put the score in CI.** Run `make evals TAG=canary` on PRs that touch `app/agent/`, and post the pass
   rate and cost against `master` as a PR comment. It needs `ANTHROPIC_API_KEY` as a CI secret, at about
   $1 per run.

Don't climb on the Import canary yet: 2 cases at about 15 minutes each, with live web calls, is too slow
and too noisy.

### 3.2 M2: Make the soft checks real

- **`answer_audit`: decide gate or advisory.** Either allow one bounded retry when the verdict is `warn`,
  or keep it advisory and label it so in ARCHITECTURE.md. Today it looks like a check but doesn't act like
  one.
- **`research_rubric`: calibrate it.** It sometimes returns `needs_revision` while passing every
  criterion (patched in `ingest/middleware.py:440-465`). Do two things:
  - Run the rule-based checks in plain code first, so Haiku only judges what rules can't.
  - Add 3–5 worked examples with per-criterion scores to its prompt so its verdicts line up with yours.
- **Score the human verdicts already collected.** Post these to Langfuse as scores on the
  `sangam_proposal` trace:
  - the `suggest_edit` outcome: SAVED, KEPT or FEEDBACK (`writing_tools.py:153-197`);
  - whether a person edited a section after it was drafted;
  - whether they edited it after it was graded.

  They are the calibration set for the 0–2 section grader and the source of hard cases for a Pitch eval
  later.

### 3.3 M3: Spending ceilings

- Add a token or dollar ceiling per run to Ask, Pitch and Import, next to the call caps. When it's hit,
  stop and tell the person, and don't fall back to a bigger model.
- Pitch public research: cap how many angles one run launches. Concurrency is capped, the total isn't.

### 3.4 M4: One scheduled pull, report-only

- Run the RFP Watch pull (`ingest/calls/pull.py`) once a day on a schedule, writing into the existing
  staff review queue (`api/routes/ingest.py:109`). A person approves everything (report-only).
- Make it a loop rather than a cron job: each run reads what earlier runs found and skips call IDs
  already seen or already reviewed.
- Log tokens and cost for each run. Move up to letting it write without review only after a few weeks of
  the reviewers agreeing with it.
- News pull next, the same way.

## 4. Not doing

- **No LLM judge in the eval grader.** It's deterministic now, which is the strong version.
- **No autonomy above report-only** for anything that writes to the catalog.
- **No event triggers yet** (for example, a Sentry error starting a fix). There's no webhook setup, and
  review time is the scarce resource.
- **No hill-climbing on Import or Pitch** until each has an eval set of its own.

## 5. Open questions

1. CI cost: run evals on every agent PR, or only when a label is added?
2. Who writes the gold SQL for the new production cases, and how many cases a week is realistic?
3. `answer_audit`: retry or advisory? A retry adds latency to every flagged answer.
4. Where should the daily pull run, given there's no worker: a Vercel cron, a GitHub Actions schedule,
   or a Claude Code routine?
