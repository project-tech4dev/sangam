# Scout (Sangam Import) — fix what the review found

## Context

A review of the Import agent found the design sound but the prompts and some claims wrong:

- **Prompts contradict themselves.** Example: `instructions.md` line 23 says call `funder_dossier` first; line 349 says `choose_sources` is "your first call, alone".
- **A write path has no approval pause.** `run_import_now` (used by the "Get the latest CSR news" task) writes the catalog with no pause, yet the prompt and `agent.py` claim "one path from research to the catalog".
- **Nothing measures Import.** There are zero Import evals, so drift is found in production. Example: #158 loosened three `save_research` rules after real findings were refused.

- **Scout goes silent mid-run.** A question asked while it researches gets no answer at all.

Decisions made:
- `run_import_now` gets an approval pause.
- An Import canary eval is added to `make evals`.
- Mid-run questions get a live status answer from the run's real state.

Not a separate fix: the validation drift (#158's three loosened `save_research` rules) is what the M3 eval is for.

## Architecture: before and after

**Before** (master @ 3e02fb6)

```
person ── ScoutChat ──(AG-UI, one run at a time)──► Import supervisor (Opus)
  │  composer: while isRunning, submit() returns silently   │  prompt: two "first calls",
  │                                                        │  "8 tools" (has 11), two output rules
  │                                                        │
  │  SourcesCard ◄── pause: choose_sources                 ├─ task ─► entity-researcher ×8 (Sonnet)
  │                                                        │            prose budget "8 searches/6 docs"
  │                                                        │            vs ReadingLimit(20)
  │                                                        │            rubric may grade after call_limit ended it
  │                                                        ├─ task ─► vault-reader / workbook-reader
  │  SaveQuestions ◄── pause: promote_research ◄── task ─► catalog-writer (Haiku) ──► catalog
  │                                                        │
  │                (no pause)                              └─ run_import_now (staff_only) ───────► catalog
  │
  evals: Ask only, nothing runs Import
```

**After**

```
person ── ScoutChat ──(AG-UI)──► Import supervisor (Opus)
  │                                │  prompt: one order (choose_sources → dossier → plan → delegate → report),
  │                                │  no tool count, one output rule, truthful "two writes, both paused"
  │  SourcesCard ◄── pause: choose_sources
  │                                ├─ task ─► entity-researcher ×8     one budget: the enforced ReadingLimit
  │                                │                                   rubric skips a run that call_limit ended
  │                                ├─ task ─► vault-reader / workbook-reader      (unchanged)
  │  SaveQuestions ◄── pause: promote_research ◄── catalog-writer ──► catalog
  │  ImportApproval ◄── pause: run_import_now (after plan_import) ──────► catalog   ◄ NEW (M2)
  │
  │  while isRunning:                                                               ◄ NEW (M4)
  └─ POST /api/ingest/threads/{id}/ask-live ─► live_status.py (Haiku, read-only)
        reads: checkpoint (aget_state) + entity_research since run start + live steps from browser
        "how far is Axis?" → answered now     "also add HDFC" → queued, auto-sent when the run ends

  make evals TAG=import ─► real Import run, 1 funder + 1 NGO, asserts the saved entity_research row  ◄ NEW (M3)
```

---

Work in a worktree (`../sangam-scout-fixes`, branched off `origin/master` @ `3e02fb6`, which includes #162 Import tagging and migration 0043), since other sessions share the checkout. Before any code, commit this plan as `docs/features/2026-10-11-scout-review-fixes.md` on the branch. Four milestones, four PRs.

---

## M1 — The prompts say one thing, and say it truthfully (PR 1)

Backend only. No new tests; fix only the existing ones a change breaks.

**`backend/app/ingest/instructions.md`**
- **One run order.** Order: `choose_sources` → `funder_dossier` → say what you'll look for → delegate → report. Rewrite "Every run" (l.21–41) and the Tools entry (l.349) so both say the same.
- **No tool count.** Drop "Eight of your own" (l.330). `TOOLS` has 11 and the count will drift again.
- **Truthful write paths.** Example: "there are two writes, both paused for a person: `promote_research` via the catalog-writer, and `run_import_now` for a news/adapter pull".
  - Fixes l.287: "that is still `run_import_now`" is wrong; the catalog-writer does it.
  - Fixes l.330–333: "the only catalog row you write…".
- **One output rule.** Replace the three-part "Output" spec (l.173–192) with what the screen actually needs:
  - per organisation: status and fact count;
  - `coverage_report` verbatim;
  - `compare_with_catalog`'s `older_or_undated` / `close_match` lines;
  - conflicts word for word;
  - no next-steps menu.
  Merge it with "Tell the user what was saved" (l.288).
- **Shorter concept tables.** Cut the 13-concept funder table and the org table (l.116–147) to one line each listing concept names. The supervisor judges coverage, and `coverage_report` prints the detail. Keep "Never merge a company with its foundation".
- **Keep the phrases tests pin** (`tests/test_ingest.py` l.257–322, l.1015):
  - every `TOOLS` name;
  - `{{MAX_PARALLEL_RESEARCH}}`;
  - "no limit on how many organisations";
  - "keep going until the list is done";
  - "Sangam Import";
  - "catalog-writer".

**`backend/app/ingest/prompts/entity_researcher.md`**
- **One passage on tags.** #162 added "**Tags** ride on three findings…" just above the older item 9 ("tags — themes. Keep the company's wording separately…"). Merge them into one item.
  - Keep #162's rules: codes from the schema, at most three, `tag_note` required.
  - Keep the old "Building Human Capital is not Education" example.
- **One budget.** Replace "about eight searches and six documents" with: read the strongest few sources; a hard reading limit stops you and you save what you have. The enforced limit is `ReadingLimit(settings.research_page_limit)`, and a number in prose drifts from it.

**`backend/app/ingest/agent.py`**
- Fix the `TOOLS` comment (l.121–127) so it no longer claims a single path to the catalog.

**`backend/app/ingest/middleware.py`: rubric vs call limit**
- **The collision.** When `call_limit` ends a run, `ModelCallLimitMiddleware` (exit "end") appends `AIMessage("Model call limits exceeded: …")`. `ResearchRubric.after_agent` then still grades and may `jump_to="model"`, which the limit ends again. The result is a wasted Haiku grade and a misleading "revise" log.
- **The fix.** In `ResearchRubric.after_agent`/`aafter_agent`, return `None` when the last AI message starts with that prefix.
- **Confirm the prefix first.** Check it against `langchain/agents/middleware/model_call_limit.py` l.60.

**Exit gate**
- `cd backend && pytest -m "not integration"` is green and `ruff check .` is clean.
- Read the diff of `instructions.md` top to bottom. No two lines may disagree on order, writes or output.

---

## M2 — `run_import_now` pauses for a person (PR 2)

**Backend**
- `backend/app/ingest/agent.py` `INTERRUPT_ON`: add `"run_import_now": {"allowed_decisions": ["approve", "reject"], "description": "Approve this import before it writes"}`.
  - **Order.** The supervisor should call `plan_import` before it, so the card can show what will be pulled. Say so in `instructions.md`.
  - **Reject.** Rejecting means nothing is written, and the supervisor says so.
- `test_import_roles.py` calls the tool function directly, so it is unaffected. Check any test asserting `INTERRUPT_ON == {...}`.

**Frontend**
- **New card.** Add `frontend/features/ingest/components/ImportApproval.tsx`, modelled on `SaveQuestions.tsx`:
  - `useInterrupt`, enabled only when `action_requests` has `name === "run_import_now"`;
  - it shows goal, funders, years, sources and has Approve / Reject;
  - Approve resolves `{decisions: [{type: "approve"}]}`;
  - it uses `PauseSignal`.
- **Mount it** in `ScoutChat.tsx` beside `SourcesCard` / `SaveQuestions` (around l.203).
- **Styles.** Reuse `ReviewCard`'s classes. No new tokens and no inline styles.
- **Design system.** Per CLAUDE.md, sync the Import page in "Sangam Design System v2" (`ui_kits/sangam-web/`) in the same PR. See `docs/DESIGN_SYSTEM.md`.

**Exit gate**
- `pytest -m "not integration"`, `npm run lint` and `npm run build` are green.
- Locally (`make up`, as staff), the "Get the latest CSR news" task shows the approval card before any write.
- Reject leaves `funder_activity` / `news_mentions` row counts unchanged (`make psql`).

---

## M3 — An Import canary in `make evals` (PR 3)

Third test tier: real agent, costs money, skipped without `--run-evals`.

**Cases**
- File: `backend/tests/evals/cases/import/canary.jsonl`.
  - **Why a subfolder.** `load_cases` globs only `cases/*.jsonl`, so a subfolder keeps these out of the Ask suite.
- One funder (e.g. Axis Bank Foundation) and one NGO from the seed with a public site.
- Fields: `{id, request, slug, expect_kind, expect_concepts_any, tags:["import","canary"]}`.

**Harness**
- File: `backend/tests/evals/import_harness.py`, reusing `message_text` from `harness.py`.
- Open the module pool the way `test_agent_evals.py::agent_pool` does (l.33–49).
- Set `chat_scope` (`app/core/security.py`) to a staff `CallerScope`. Without it every gated tool refuses (`app/ingest/caller.py::scope`).
- Build with `build_ingest_agent(settings, InMemorySaver())` and `ainvoke` the request.
  - **Expect a pause.** The run pauses on `choose_sources`. Resume with `Command(resume={"decisions": [{"type": "approve"}]})` (web + library).
  - **Timeout.** 900 s per case: one org takes minutes, not the 180 s Ask allows.

**Test**
- File: `backend/tests/evals/test_import_evals.py`, marked `eval`.
- Skip with a reason when `TAVILY_API_KEY` is unset, since search returns "SEARCH UNAVAILABLE".
- Assert on the saved `entity_research` row for `slug`, not on prose:
  - `save_research` returned "Saved as entity_research";
  - `entity_kind == expect_kind`;
  - at least one finding;
  - at least one of `expect_concepts_any` found;
  - every gap has `reason` in {blocked, not_stated} and a non-empty `detail`;
  - `ResearchSummary.fact_count` equals the saved findings count;
  - every tagged `program`/`identity`/`org_identity` finding carries a `tag_note`, per #162's `Tagged` mixin.
- Run: `make evals TAG=import`. The existing Makefile target already passes `--eval-tag`. Add one line to CLAUDE.md's evals block.

**Exit gate**
- `make evals TAG=import` passes against the local stack.
- Then break it on purpose (set `expect_kind` wrong in a case) to prove the assertion bites, and revert.
- Cost is noted in the PR body.

---

## M4 — Scout answers while it works (PR 4)

**Why it's silent today**
- `submit()` (`frontend/features/ingest/ScoutChat.tsx:130`) returns when `isRunning`, with no feedback.
- Behind that, the supervisor is blocked inside its parallel `task` calls for the whole wave (up to 15–20 min), so the running graph cannot take a new message.
- Decision: a side route answers at once from the run's real state, and leaves the running graph untouched.

**Backend: one route, read-only**
- **Route.** `POST /api/ingest/threads/{thread_id}/ask-live` in `backend/app/api/routes/ingest.py`.
  - Body: `{question, since, steps}`, where `steps` is the WorkingBoard's live steps, trimmed to `{lane, tool, label, done}`.
  - Access: `require_user`, and only `import-` threads.
- **Gather.** New module `backend/app/ingest/live_status.py`, not a tool, so it lives outside `tools/`. It pulls:
  - **the checkpoint**, via `threads_repo.can_open` and `graph.aget_state` (the same pair `routes/threads.py::saved_messages` uses): what was asked, the `choose_sources` answer, which `task`s were launched;
  - **saved research**: `entity_research` rows with `researched_by = caller` and `researched_at >= since`, with slug, status and fact count, passed through `caller.without_private` for a non-staff caller;
  - **the browser's `steps`**, for subagent progress the parent checkpoint can't show until a wave returns.
- **Answer.** One `UTILITY_MODEL` call with a short prompt in `backend/app/ingest/prompts/live_status.md`. It returns `{answer, kind}`:
  - `kind: "status"` answers from that state, e.g. "Axis Bank Foundation: 5 pages read, not saved yet; Tata Trusts: saved, 41 facts".
  - `kind: "instruction"` for anything that changes the run, e.g. "also add HDFC". It never acts.
- **Schemas.** Request and response go in `backend/app/schemas/ingest.py`. No table and no checkpoint write, so live replies are not kept on reload.

**Frontend**
- **Send while running.** In `ScoutChat.tsx`, `submit()` posts to the route instead of returning when `isRunning`. The composer stays usable, and the hint reads "Scout is researching; ask about progress".
- **Show the reply** inline as a live note under the running turn. Reuse the existing reply classes; no inline styles.
- **Queue instructions.** On `kind: "instruction"`, hold the text and say "Scout will pick this up when the current researchers finish". Auto-`send()` it once `isRunning` goes false.
- **Design system.** Sync the Import page in the same PR, as in M2.

**Exit gate**
- Lint, build and backend unit tests are green.
- Locally, during a 2-organisation run:
  - "how far along is Axis?" answers in seconds and names what was really read or saved;
  - "also add HDFC" is queued, then runs as the next turn;
  - the running researchers are not interrupted (their saves still land).

---

## Verification (all four)

- `cd backend && pytest -m "not integration" && ruff check .`
- `cd frontend && npm run lint && npm run build`
- `make up && make seed` (`make up` runs migrate first, which the backend needs to boot). Then run one real Scout import as staff: one funder, then the news task. Read its `sangam_import` trace in Langfuse to confirm:
  - `choose_sources` is the first tool call;
  - no "confirm sources" chatter;
  - `run_import_now` paused;
  - the researcher had no rubric grade after a call-limit stop.
- `make evals TAG=import`.
- During that run, ask "how far along is it?" and get an answer in seconds; "also add X" is queued and runs as the next turn.
