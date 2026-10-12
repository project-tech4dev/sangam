# Media & Signals — an agentic layer on the news pull (Draft v1)

## Context

PR #173 (`feat/media-signals`) ships the news pipeline as fixed code. `app/ingest/news/pipeline.py`
runs search → filter → one Haiku call per link → Sonnet grouping → bars in code. It is cheap (about $6 per
pull for everyone) and repeatable. Its judgement is narrow, though: one model call per snippet, with no way to
check a hard case, and nothing that tells anyone what the news means.

We agreed on a hybrid. The pipeline stays the backbone, and agents go only where judgement is open-ended:

| part | what it adds | where it runs |
|---|---|---|
| **B. Planner** | Scout plans topic-only pulls ("FCRA news only") | Scout supervisor, a new `feeds` argument |
| **C. Verifier** | a bounded agent re-judges borderline links before they are stored | inside the pull |
| **D. Analyst** | "what changed for Org X" with the primary source | Ask Sangam skill |

These stay in code, unchanged: the bars, the last-searched dates (watermarks), deduplication, the
classification cap, the approval card ⏸, and staff "hide".

User decisions (12 Oct 2026):
- The verifier runs inside the pull.
- The verifier is a deep agent.
- The analyst is an Ask skill.
- B is in.
- The cleanup of #173's leftovers is in.
- All of it ships as **one PR stacked on `feat/media-signals`**, one commit per milestone.

## Goal

**A borderline news match is checked by reading before it is shown, and anyone can ask Sangam what changed in
an organisation's news, with the source.** Success:
- Fewer wrong public matches on profiles. Example: "Pratham Motors" never shows on Pratham's page.
- Fewer right matches lost below the bar.
- A pull still finishes inside 1800 s.
- Nothing in #173 changes behaviour while the verifier is switched off.

## Architecture

```
 Scout supervisor (Opus)
   │  "FCRA news only"      ★B  run_import_now(sources="tavily_news", feeds="fcra")
   ▼
 approval card ⏸  plan line ★ "+ up to 40 checks, about $3"
   ▼
 pipeline: search → filter → Haiku classify ──┬─ clear verdict ───────────────┐
                                              └─ ★C needs_check(v, bars)      │
                                                   ▼                          │
                                    verifier (create_deep_agent, Sonnet)      │
                                    tools: read_page, search_public_sources   │
                                           (+ read_file, the library floor)   │
                                    limits: 3 pages, 8 calls, run deadline    │
                                    returns EntityVerdict + evidence          │
                                    any error / over budget → keep Haiku's    │
                                                   ▼                          ▼
                                      save_score (same prompt_version) → stories → BARS (code)
                                                   ▼
                                      news tables (unchanged schema)
                                                   ▼
 Ask Sangam ★D  skill news-brief: db_query news tables → fetch_url the main link → brief with [news:N]
```

**The key trade-off:** the verifier replaces the Haiku verdict *before* `save_score`, under the same
`prompt_version`. Every reader stays as it is: `unstoried`, `upsert_entity_link`, the routes and the frontend.
- **Cost:** a link scored before this ships is not re-checked. Bumping `PROMPT_VERSION` later re-checks everything.
- **Rejected alternative:** a second score row (`signals-v2+verify`). It would need a new reader, and a downgrade
  path, because `upsert_entity_link` only raises scores.

## Blast radius (built by hand from `catalog.py`, `CLAUDE.md` and `0044_news.sql`)

| surface | hop | why affected | status |
|---|---|---|---|
| `app/ingest/news/pipeline.py` `_classify_all`, `Deps` | 0 | the verifier hook | in scope |
| `app/ingest/news/bars.py` | 0 | `needs_check()`, pure | in scope |
| `app/ingest/news/classify.py` `EntityVerdict` | 0 | optional `verified`, `evidence`, `evidence_url` fields, defaulting to off, so old jsonb still validates | in scope |
| `app/ingest/news/verify.py` + `prompts/verify.md` | 0 | new | in scope |
| `app/ingest/news/windows.py`, `schemas/news_runs.py`, `routes/news_runs.py` | 1 | plan line: check count and cost; `feeds` param | in scope |
| `app/ingest/tools/pipeline_tools.py` `run_import_now`, `_news_pull`, `_news_plan_line` | 1 | `feeds` argument | in scope |
| `app/ingest/instructions.md` (adapter path) | 1 | one line on `feeds` | in scope |
| `frontend/features/ingest/components/ImportApproval.tsx` | 2 | pass `feeds`, show checks in the plan line (text only) | in scope, plus the Design System `Import.jsx` text sync |
| `app/core/config.py` | 1 | `news_verify_*` settings | in scope |
| `app/agent/skills/news-brief/SKILL.md`, `app/agent/instructions.md` rule 13 | 0 | the analyst | in scope |
| `adapters/gdelt.py`, `adapters/india_csr.py`, `runner._ingest_india_csr`, `records.NewsMention`, `YIELD_KINDS` | 1 | dead since #173 parked them (cleanup, Milestone 1) | in scope |
| `data/sources/media.json` | 1 | 22 entries still yield `news_mention` | in scope |
| `routes/ingest.py:48-59` (`has_adapter`) | 2 | reads `ADAPTERS`; still correct when it is empty | unaffected |
| `news_link_scores.verdict` jsonb | 1 | carries the evidence; no migration | in scope |
| SQL catalog | — | no new table or column, so nothing new is exposed | unaffected |
| `news_story_entities`, the routes, StoryCard, InTheNews | 2 | read the same columns | unaffected (no "checked" badge; deferred) |
| Import harness tests (`test_harness.py` subagent sets) | — | the verifier is a standalone deep agent, not one of Import's subagents, so the subagent sets don't change | unaffected |
| `app/agent/harness.py` `install()`, `filesystem()` | 1 | reused; the verifier shares the global per-provider profile | in scope (reused as is) |
| `test_every_tool_defined_is_also_registered` | — | reuses tools that are already registered; no new tool | unaffected |
| `board.ts` `HELPERS` | — | no new `task` subagent type | unaffected |

## Low-level design

### C. Verifier (`backend/app/ingest/news/verify.py`)

- **A deep agent, like every other agent in the repo** (decided 12 Oct 2026, over plain `create_agent`).
  `build_verifier(settings)` calls `harness.install()` first (no general-purpose subagent), then
  `create_deep_agent(...)` with:
  - `model=resolve_model(settings.research_model)`.
  - `tools=[read_page, search_public_sources]`, both from `app/ingest/tools/research_tools.py`.
  - `backend=StateBackend()`: virtual and empty.
  - `middleware=[filesystem(backend, keep=REQUIRED_MINIMUM), ReadingLimit(news_verify_page_limit),
    call_limit(news_verify_call_limit), fallback(research, model)]`.
    - `filesystem(...)` (`app/agent/harness.py`) cuts the preset's eight tools to `read_file`, the library's floor.
    - `ReadingLimit`, `call_limit` and `fallback` are reused from `app/ingest/middleware.py`.
  - `system_prompt=prompts/verify.md`, `response_format=VerifiedVerdict`.
  - No `subagents`, no `skills`, no `checkpointer`, no `interrupt_on`.
- **The preset keeps:**
  - `SummarizationMiddleware`, idle at 8 calls.
  - `PatchToolCallsMiddleware`, which repairs a call cut off by `call_limit`.
  - `AnthropicPromptCachingMiddleware`, which caches the verifier prompt across up to 40 checks a run.
- **Tool surface: `read_page`, `search_public_sources`, `read_file`.** Nothing writes.
- **Built once per run** in `Deps.from_settings`, not per link, and invoked with `ainvoke` per check.
- **No `RunSources`:** the person approved web reading on the news card, and the card says so.
- **Structured output:** check that `response_format` works on the research tier with `ProviderStrategy`. `group.py:90`
  notes that it rejects forced tool calls.
- **`verify(agent, subject, hit, haiku_verdict) -> EntityVerdict`**
  - Prompt input: `profile_for(subject)` (from `feeds.py`), the hit, and Haiku's verdict as a "first read".
  - Output: an `EntityVerdict` with `verified=True` and `evidence` (one own-words line, 200 characters or fewer).
    `evidence_url` is the page that settled it.
- **`prompts/verify.md`:** judge the namesake first. Read the item's own page if the snippet is thin, then the
  organisation's site or one search to confirm place, people or work. Never quote. When unsure, lower the match.
  Do not raise it.
- **`bars.needs_check(v, subject_kind, bars, low)`** is pure. It is true for entity subjects only, when either:
  - `low ≤ match < public_match`. Example: 0.55 is checked, 0.85 is not.
  - Or `stance == "negative"` and `listed_match ≤ match < negative_match`, because negative news is high stakes.
- **Hook in `pipeline._classify_all.one()`,** after `classify_entity`:
  - Verification runs only when all three hold: `deps.verifier`, `needs_check(...)`, and both a verify budget and
    time before `deadline` remain.
  - Then `v = await verify(...)` runs in a semaphore of `parallel_verify` and inside `asyncio.wait_for`.
  - On any exception or timeout, the Haiku verdict stands.
  - Each check is logged as a run item with `kind="news_verify"`:
    - `confirmed`: kept as is.
    - `changed`: the match moved more than 0.15.
    - `skipped`: over budget, over time or failed, with the reason.
- **`Deps`** gains `verifier=None, max_verify=0, parallel_verify=2, verify_seconds=600, verify_low=0.35`.
  - With the defaults, behaviour is exactly #173's, and `tests/test_news_pipeline.py`'s `_deps` needs no edit.
  - `from_settings` builds the verifier only when `news_verify_max > 0`.
- **Config:** add these, all with a "why" one-liner, under the Media & Signals block in `config.py`:

  | setting | default |
  |---|---|
  | `news_verify_max` | 40 |
  | `news_verify_low` | 0.35 |
  | `news_parallel_verify` | 2 |
  | `news_verify_seconds` | 600 |
  | `news_verify_page_limit` | 3 |
  | `news_verify_call_limit` | 8 |
  | `news_verify_cost_usd` | 0.08 |

- **Plan line:**
  - `windows.NewsPlan` gains `checks` (`min(news_verify_max, est)`), and the cost includes it.
  - `NewsPlanOut` and `frontend/lib/api/types.ts` gain `checks`.
  - `_news_plan_line` and `ImportApproval.tsx`'s `NewsLine` append "· up to N checks".
- **Tracing:** wrap with `trace_config(settings, name="sangam_news_verify", tags=("news","verify"))` from
  `app/integrations/tracing.py`.

### B. Planner (`feeds`)

- **`pipeline.select(pool, names, feeds=None)`:**
  - With feeds and no names, it returns `Selection([], [], feeds, [], [])`.
  - Empty lists are not "everyone": `create_run` writes `feed:` subjects only, and `_parse` already accepts that.
  - An unknown feed key raises, listing `feeds.FEEDS`.
- **`run_import_now`** gains `feeds: str = ""` (docstring: `fcra`, `csr_trends`, `ngo_north_east`). It is passed
  through `_news_pull` and `_news_plan_line`.
- **`routes/news_runs.py` `plan`** gains `feeds: str = ""`, and `ImportApproval.tsx` passes `plan.feeds`.
- **`app/ingest/instructions.md`** adapter path gets one line: "A request about a topic only ('FCRA news') passes
  `feeds`, with no names."

### D. Analyst (Ask skill `backend/app/agent/skills/news-brief/SKILL.md`)

- **Steps:**
  1. Resolve the organisation or funder by name (`db_query` on `orgs`/`funders`).
  2. Get its stories: `news_story_entities` ⨝ `news_stories`, with `visibility <> 'hidden'` and `is_news`, over
     the last 30 days by default.
  3. Group them by `signal_type`/`topic` and stance.
  4. For a negative or regulatory story, `fetch_url` its main link once to name the primary source (an MHA order,
     a court, an MCA filing), cited in words.
  5. Write three to five lines, each with `[news:N]`.
- **Zero means unpulled:** report the latest `max(news_links.fetched_at)` and say "nothing in Sangam's pulls since
  X", never "no news".
- **`app/agent/instructions.md` rule 13** adds: "For what changed in an organisation's or funder's news, load
  news-brief." Skills are discovered from `SKILLS_DIR` (`build.py:45`), so no code change is needed.

## Security review

- **No new endpoint.** `GET /ingest/news-runs/plan` gains one query param and stays `require_staff`.
- **No new table and no catalog change,** so Ask can reach nothing new.
- **The verifier reads untrusted pages:**
  - It has no write tool. It returns a schema-validated `EntityVerdict` for one link and one subject only.
  - The bars are applied after it, in code, so injected text can at most move one score.
  - `read_page` goes through `check_url` (the SSRF guard from `core/egress.py`, plus robots and the source registry).
- **Side effect:** `check_url` may log unknown hosts to `ingest_source_proposals`. This already happens in Import.
- **No personally identifiable information (PII) beyond what pages already say.** Evidence is one own-words line,
  in line with design decision D11: no article text is stored.
- `TAVILY_API_KEY` is read from Settings only.

## Testing

Per the standing rule, no new tests in these PRs. Run the existing suites and fix only what a change breaks:
- `cd backend && pytest -m "not integration"`, then `pytest tests/test_news_pipeline.py tests/test_harness.py
  tests/test_ingest.py` against compose Postgres.
- Frontend: `npm run lint && npm run build`.
- **Manual trial:** `make news-pull ORG=<an ambiguous one-word org> CONFIRM=1`. Then read `ingest_run_items` for
  `news_verify` rows and check that the run finished in under 1800 s.
- **Ask:** "What's changed for <org> this month?" returns `[news:N]` lines, plus "since <date>" when the result
  is empty.

## Reuse map: what each new part builds on (nothing rebuilt)

| new part | reuses | from |
|---|---|---|
| verifier agent | `create_deep_agent`, `install()`, `filesystem(keep=REQUIRED_MINIMUM)` | `app/agent/harness.py` |
| verifier tools | `read_page`, `search_public_sources` (with `check_url`, the SSRF and robots guard) | `app/ingest/tools/research_tools.py` |
| verifier limits | `ReadingLimit`, `call_limit`, `fallback` | `app/ingest/middleware.py` |
| verifier input and output | `profile_for` (including the namesake notes), `EntityVerdict` | `news/feeds.py`, `news/classify.py` |
| verifier model and trace | `resolve_model`, `trace_config` | `app/agent/models.py`, `app/integrations/tracing.py` |
| who gets checked | the bars and `Bars.from_settings` | `news/bars.py` |
| run log | the run-item writer (made public in Milestone 1) | `app/ingest/runner.py` |
| topic-only pulls | `FEEDS`, `create_run`, `_parse` (already accepts feed-only subjects) | `news/feeds.py`, `news/pipeline.py` |
| plan line | the one `plan_for` from Milestone 1 | `news/pipeline.py` |
| analyst | `db_query`, `fetch_url`, the skills dir, the High/Medium/Low wording in the catalog notes | Ask Sangam as is |

## Precondition: PR #173 lands first, renumbered

- **Migration numbers collide.** Master took `0044` with `0044_one_read_policy_and_fk_indexes` (#181). The PR
  branch now carries `0044_news.sql` and `0045_drop_news_mentions.sql`.
- **Fix in #173 before merge:** rebase onto master and renumber to `0045_news` and `0046_drop_news_mentions`. Then
  update the migration list in CLAUDE.md, and every "0044" reference in the spec and code comments.
- This plan stacks on `origin/feat/media-signals` at `4506fbf` or later. The local branch `40d5d1f` is behind the
  remote.

## Milestones: one stacked PR, one commit per milestone

- **One branch, `feat/media-signals-agentic`,** cut from `origin/feat/media-signals` in its own worktree (sessions
  share the checkout).
- **One PR whose base is `feat/media-signals`.** The diff shows only this work, not #173.
- **Once #173 merges,** GitHub retargets the base to `master`. Rebase onto master then.
- **Each milestone is one commit** (or a short run of commits) that passes its own exit gate. A reviewer can read
  it commit by commit, and any one commit can be reverted alone.
- **The verifier ships switched off** (`news_verify_max=0`) inside the same PR. Switching it on is an env change
  after the merge, not another PR.

#### Milestone 0: plan committed
- **Deliverable:** this plan as `docs/features/2026-10-12-media-signals-agentic.md` on `feat/media-signals-agentic`.
- **Exit gate:** `git log -1 -- docs/features/2026-10-12-media-signals-agentic.md`

#### Milestone 1: cleanup, then one copy of each shared piece (no behaviour change)
What #173 left behind, removed, and what it wrote three times, written once. Every later milestone builds on this.
- **Dead code removed.** GDELT and India CSR are parked: `ADAPTERS` dispatches nothing, and `news_mentions` is
  dropped.
  - [ ] `app/ingest/adapters/gdelt.py`: it writes a dropped table, so it can't be revived as is.
  - [ ] `_ingest_india_csr` and `_query` in `runner.py`, and `app/ingest/adapters/india_csr.py`.
  - [ ] The `NewsMention` record in `app/ingest/records.py:258`, and `"news_mention"` in `YIELD_KINDS`
        (`sources.py`).
  - [ ] Keep `PARKED` and its reasons: a request for `gdelt` or `india_csr` still gets a refused row that says why
        (D16). Git history keeps the adapter code for anyone reviving it.
- **The source registry tells the truth.**
  - [ ] In `data/sources/media.json`, the 22 media entries say `yields: ["news_link"]`, not `news_mention`.
- **One plan, not three copies.** The same select → `plan_subjects` → `windows.plan` sequence lives in
  `routes/news_runs.py:22-26`, `pipeline_tools._news_plan_line` and `news/run.py:46`.
  - [ ] Add `pipeline.plan_for(pool, names, feeds=None) -> (Selection, NewsPlan)`. All three call it. B and C then
        each extend one place.
- **One public run-item writer.** `runner._item` is private, but it is called from `news/pipeline.py` (5 places)
  and `pipeline_tools._news_pull`.
  - [ ] Rename it `runner.record_item` and update the callers.
- **The adapter-only helpers collapse.** With `ADAPTERS` empty, the logic simplifies.
  - [ ] Fold `_adapter_keys()` and `_parked()` into direct imports of `runnable_for` and `PARKED`.
  - [ ] Keep `run_import`'s refusal and summary path. Non-news calls still report refused and held sources.
- **Docs.** CLAUDE.md still says "the two enumerated sources" in places. Make it say what runs: `tavily_news`, and
  parked adapters.
- **Touches:** backend, JSON registry, CLAUDE.md. No frontend, prompt or schema change.
- **Exit gate:**
  - `pytest -m "not integration"` and `pytest tests/test_news_* tests/test_ingest.py` pass. Only tests that pinned
    deleted code are edited.
  - `git grep -n "gdelt\.\|_ingest_india_csr\|news_mention\b" backend/app` is empty, except the `PARKED` reasons.

#### Milestone 2: D, the news-brief skill
- **Touches:** prompt only (`SKILL.md`, `instructions.md` rule 13).
- **Exit gate:** `pytest tests/test_prompt.py` passes, and an Ask question returns a cited brief.

#### Milestone 3: B, topic-only pulls
- **Touches:** backend (`pipeline.select` and `plan_for` gain `feeds`, `run_import_now`, the plan route), the Import prompt line,
  `ImportApproval.tsx`, and the Design System `Import.jsx` text.
- **Exit gate:**
  - `make news-pull` is unchanged.
  - Scout "FCRA news only" shows a card with 1 subject and runs feed-only.
  - `pytest -m "not integration"` and `npm run build` pass.

#### Milestone 4: C, the verifier
- **Touches:** backend (`verify.py`, `prompts/verify.md`, `bars.needs_check`, the pipeline hook, `Deps`,
  config, the plan line), plus the `ImportApproval` text.
- **Shipping:** ships with `news_verify_max=0` first (inert), then turned on by env.
- **Exit gate:** a trial pull on an ambiguous org shows `news_verify` items, finishes under 1800 s, and the full
  backend suite passes.

## Open questions and risks

- **The verifier is a third deep agent.** A deepagents upgrade that adds preset tools would reach it, as it would
  Ask and Import.
  - The no-new-tests rule means this PR adds no pin.
  - Open question: extend `test_harness.py`'s graph walk to the verifier (exactly `read_page`,
    `search_public_sources`, `read_file`) as a fix to an existing test, or leave it unpinned.
- **The harness profile is global per provider.** A future `install()` change made for Ask or Import also changes
  the verifier.
- **Time:** at 40 checks, 2 at a time, about 60 s each, verification adds about 20 min. That is too much for an
  everyone pull. The `news_verify_seconds=600` deadline caps it, and the rest keep Haiku's verdict. The default cap
  may need to be about 20.
- **Structured output on Sonnet 5.5:** `ProviderStrategy` support needs checking. If it is missing, run a final
  `with_structured_output(..., method="json_schema")` call over the agent's last message.
- **Old scores are never re-checked** until `PROMPT_VERSION` is bumped. This is accepted for Draft v1.
- **No "checked by Sangam" mark on the StoryCard.** It is deferred, because it would need a Design System change
  and a schema field.
