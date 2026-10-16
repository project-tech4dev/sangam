# Ask efficiency: one compare_fit, a cache that holds, fewer wasted queries

Status: **Draft v1**, 2026-10-16. Branch `feat/ask-efficiency`. No earlier document covers this; it
builds on `2026-10-10-funder-matching-match-v1.md` and `2026-10-11-funder-match-v2-themes.md`
(what `compare_fit` returns) and does not change either rubric.

## 1. Goal

**Ask answers "what does X do, where does it work, and which funders fit it?" in about four tool
calls, for about a quarter of today's cost, with every fact still cited.**

Success is measured on the same question, in production, with `trace_cost.sh` on the Langfuse trace:

| measure | before (trace `5bfdbc85`, 16 Oct) | target |
|---|---|---|
| cost | $0.87 | under $0.25 |
| latency | 141 s | under 60 s |
| model calls / tool calls | 21 / 26 | under 8 / under 8 |
| `compare_fit` calls | 4 | 1 |
| `read_file` on `/large_tool_results` | 2 (one an error) | 0 |
| cache read per model call | climbs to 50k, then stuck at 7,338 | only climbs |

### What went wrong, in that trace

```
17:13:51  9 SQL calls      5 wasted: guessed columns (mission, t.name), guessed tables
                           (org_themes, themes), a locations query without org_id
17:14:08  compare_fit(8)   reply > 80,000 chars -> evicted to /large_tool_results/…  (one line)
17:14:11  read_file        "lines 1-1 of 1", cut short; offset 400 -> ERROR
17:14:56  context > 40k    ClearToolUsesEdit fires, and fires again on every later call
          … 3 more compare_fit, 6 re-queries of rows it had already read
                           cache read stuck at 7,338 tokens; ~$0.66 of $0.87 spent here
```

Four separate causes, each with its own fix:

> **The rule:** `compare_fit(org_id)` must fit in the conversation.
> **Example:** for Better Life Foundation [org:8] it scored 26 of 37 funders and wrote every one at full
> detail — seven criteria each — as one JSON line. The 20k-token eviction moved it to a file the model
> could not page.
> **Why it matters:** the skill says "call it once"; the model cannot, if it cannot read the reply.

> **The rule:** clearing old tool results must not change the prompt prefix on every call.
> **Example:** with `trigger=40_000, keep=5`, every call past 40k clears a different oldest result, so
> the cached prefix breaks each time and Sonnet re-writes 20–53k tokens of cache per call.
> **Why it matters:** this one setting was three-quarters of the cost, and it erased the org's
> description, places and themes, which the model then fetched again.

> **The rule:** a row the model asked for comes back cited, without a second query.
> **Example:** `SELECT l.name, l.kind, ol.role FROM org_locations ol JOIN locations l …` came back with
> no `[org:8]`; the model re-ran it with `ol.org_id`.
> **Why it matters:** instructions rule 8 forces the re-run; code can add the id the way it already adds
> `source_url`.

> **The rule:** the model never has to guess a table name.
> **Example:** it asked `db_describe_table("orgs,org_themes,org_locations,locations,themes")`, then
> `db_list_tables` to recover. Themes live in `org_tags` + `tags`.
> **Why it matters:** two calls per question, every question that starts cold.

### Why no new tools

`compare_fit` already has the two shapes needed: `compare_fit(org_id)` is the shortlist,
`compare_fit(org_id, funder_ids)` is the detail. The four hand-written lookups (`search_orgs`,
`get_funder`, …) were removed as cached query plans that were worse than the model's own SQL
(`CLAUDE.md`, "There used to be four hand-written tools"). Every fix below is to an existing tool's
output, one middleware setting, or the prompt.

## 2. Blast radius

Built by hand from `CLAUDE.md`'s Architecture section, `backend/app/agent/build.py`,
`backend/app/proposals/agent.py` and a grep for each symbol changed. No table or migration changes.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `agent/tools/matching_tools.py` (`compare`, `_entry`, `compare_fit`) | 0 | the shortlist reply's shape and format | in scope | `compare` has no other importer (grep, 16 Oct) |
| `agent/skills/funder-matching/SKILL.md` | 1 | its reply table names the fields | in scope | |
| `agent/skills/funder-shortlist-brief/SKILL.md` | 1 | reads weak fits, `summary`, `improve` | in scope | only wording; it already uses one line per weak fit |
| `agent/skills/funder-comparison/SKILL.md` | 1 | uses `compare_fit(org_id, funder_ids)` | unaffected | that path keeps every field |
| `agent/middleware.py::clear_old_tool_results` | 0 | the cache fix | in scope | |
| Sangam Pitch (`proposals/agent.py`) | 1 | also uses `clear_old_tool_results()` | in scope | gets the cache fix for free; prefill guard in M4 |
| `agent/tools/sql/validator.py`, `render.py` | 0 | auto citation id, single-row cells | in scope | |
| `agent/tools/sql/catalog.py` | 1 | source of the table list and `CITE_COLUMNS` | read only | no table added; not a security change |
| `agent/instructions.md`, `agent/prompt.py` | 0 | table map, rule 8 wording | in scope | |
| Sangam Import (`ingest/`) | 1 | shares `harness.filesystem`, not `clear_old_tool_results` | unaffected | Import's own eviction stays as is |
| Funder Match page and saved runs (`matching/service.py`) | 2 | store `match()`, never `compare()` | unaffected | |
| `tests/evals/` | 1 | golden questions run through the real agent | in scope | one new canary for this question |
| frontend | 2 | renders tool calls by name only | unaffected | no tool added or renamed |
| `openwiki/`, `docs/CHANGELOG.md`, `docs/SQL_AGENT.md` | 1 | describe the changed tools | in scope | `make wiki-update`; never hand-edit openwiki |

## 3. High-level design (HLD)

### Before: master today

```
 user ─▶ Next.js /api/copilotkit ─AG-UI─▶ FastAPI /agent ─▶ Ask deep agent (MODEL)
                                                               │
   middleware, in order ───────────────────────────────────────┤
   1 FilesystemMiddleware   read_file, ls; evicts any result > 20k tokens to /large_tool_results/
   2 sql_retry_limiter      5 failed db_query -> stop
   3 ClearToolUsesEdit      > 40k tokens: keep last 5 results, clear the rest ── EVERY call
   4 answer_audit           Haiku checks the answer afterwards
                                                               │
   tools ──────────────────────────────────────────────────────┤
   db_list_tables · db_describe_table · db_profile_column      │
   db_query ─▶ validator (qualify, LIMIT, +source cols) ─▶ executor (RLS, read-only) ─▶ render
                                     cells cut at 200 chars; no id projected -> no marker
   compare_fit(org_id) ─▶ repositories/matching (fixed SQL) ─▶ matching/rules ─▶ match()
                         ─▶ json.dumps(every scored funder, full detail)   ONE LINE, ~25-30k tokens
   search_graph · fetch_url                                    │
   skills (read_file /skills/…): funder-matching ─▶ funder-shortlist-brief

 the loop that hurt:
   compare_fit ─▶ >20k ─▶ evicted file (1 line) ─▶ read_file cut short ─▶ model re-calls compare_fit
               ─▶ context >40k ─▶ clearing every call ─▶ prefix changes ─▶ no cache, rows forgotten
               ─▶ model re-queries orgs / locations / tags
```

### After

```
 user ─▶ Next.js /api/copilotkit ─AG-UI─▶ FastAPI /agent ─▶ Ask deep agent (MODEL)
                                                               │
   system prompt  + table map: 37 names, one line each, from catalog.py   (cached, ~1k tokens)
                                                               │
   middleware ─────────────────────────────────────────────────┤
   1 FilesystemMiddleware   unchanged (now a safety net, not the normal path)
   2 sql_retry_limiter      unchanged
   3 ClearToolUsesEdit      trigger raised, clears in one large batch (clear_at_least),
                            never clears compare_fit                ── fires rarely, prefix stable
   4 answer_audit           unchanged
                                                               │
   db_query ─▶ validator (+source cols, +__cite__ id when none projected) ─▶ executor ─▶ render
                                     one-row results show long text in full
   compare_fit(org_id)          ─▶ shortlist: strong/medium in full, weak as one line,
                                   no summary, text with a line per fact      (< 15k tokens)
   compare_fit(org_id, ids)     ─▶ unchanged: every field, for funder-comparison

 the same question:
   db_query orgs (cited) ─▶ db_query places + themes (cited) ─▶ compare_fit(8) once ─▶ write-up
```

**Touched:** the model (fewer, cheaper calls). **Not touched:** Postgres schema, Neo4j, Supabase
Storage, REST routes, the frontend.

### The key trade-off

| option | what it does | why not / why |
|---|---|---|
| line breaks only | the evicted file pages | still 25–30k tokens, read in 5–10 slices, and the 40k clearing still fires |
| exempt `compare_fit` from eviction | always in context | 25–30k tokens on every later call of the turn |
| **shrink the shortlist, keep the detail call** | fits, one call | **chosen**: the write-up already uses one line per weak fit, so the shortlist carries what is read |

The second trade-off is clearing. Turning clearing off would let a long chat grow without bound.
Raising the trigger and clearing in batches keeps the bound and keeps the prefix stable between batches.

## 4. Low-level design (LLD)

### 4.1 The shortlist reply — `backend/app/agent/tools/matching_tools.py`

- Measure first (M1): `len(reply)` for `compare_fit(8)` against the local DB, by field, and a
  synthetic worst case where all 37 funders are strong or medium. Count tokens as
  `deepagents.middleware.filesystem` does: 4 characters per token (`NUM_CHARS_PER_TOKEN`, line 1018),
  eviction at 20,000 tokens = 80,000 chars.
- The budget is **15k tokens (60,000 chars)**, not 20k: the context was already ~19k when
  `compare_fit` ran, and 19k + 21k crosses the 40k clear trigger in one step.
- `compare(..., shortlist=True)`:
  - `tier in ("strong", "medium")`: card, criteria (points, status, note, cites), `not_judged`,
    first `improve` action. No `summary`: it restates the card.
  - `tier == "weak"`: `funder [funder:N] · type · 36/100 weak · ! <first gap line>`.
  - `not_scored`: as today, names only.
- Rendered as text, not one JSON line: a header, one block per funder, one fact per line, in the
  style of `db_query`'s output. An oversized reply then pages cleanly with `read_file` offsets.
- `compare(..., shortlist=False)` (named funders): every field as today. Rendered with the same text
  layout, so both modes read alike.
- The `@tool` docstring's "Returns JSON" paragraph is rewritten to match.

### 4.2 Context clearing — `backend/app/agent/middleware.py`

```python
TOOL_RESULT_CLEAR_TRIGGER_TOKENS = 80_000   # was 40_000
TOOL_RESULTS_CLEAR_AT_LEAST = 30_000        # clear in one batch, then not again for a while
ClearToolUsesEdit(trigger=..., keep=TOOL_RESULTS_KEPT, clear_at_least=...,
                  exclude_tools=("compare_fit",))
```

Values are set in M1 from the measured sizes, not guessed. `exclude_tools` is safe because a
compact shortlist is bounded. Sangam Pitch shares the function and gets the same behaviour.

### 4.3 Automatic citation id — `backend/app/agent/tools/sql/validator.py`, `render.py`

- New `_plan_cite_ids(qualified, existing_plans)`, beside `_plan_provenance`, with the same guards:
  plain `SELECT` only, not aggregate, not `DISTINCT`, no CTE or subquery source.
- For each table alias that has a column in `CITE_COLUMNS` but none projected, append
  `"<alias>"."<col>" AS "__cite__<alias>"`. Prefer the table's own primary key; else the first foreign
  key that cites (so `org_locations` gets `org_id` -> `[org:N]`).
- `__cite__` joins `__prov__` as a reserved prefix in `_reject_reserved_aliases`.
- `render_rows` uses `__cite__` columns for markers and never prints them as data, as it already does
  for `__prov__`. The "No citable id column was projected" hint stays for the cases the guards skip.
- `instructions.md` rule 8 becomes: "db_query adds the id for you when it can; aggregates and DISTINCT
  cannot be cited."

### 4.4 Table map in the prompt — `backend/app/agent/prompt.py`, `instructions.md`

- A `{{TABLE_MAP}}` placeholder in `instructions.md`, replaced in `render_prompt` with the same lines
  `db_list_tables` prints (one per table, from `CATALOG`, sorted). Plain `.replace()`, as Import does.
- Built from code at import time, so it cannot drift from the catalog and costs no DB call.
- Rule 6 becomes: "The tables are listed below. Call db_describe_table for the ones you need before
  writing SQL; db_list_tables repeats this list."
- `CLAUDE.md`'s "the only substitution any agent prompt in this repo gets" sentence is updated.

### 4.5 One-row cells — `backend/app/agent/tools/sql/render.py`

- When the result has exactly one row, `MAX_CELL_CHARS` rises to 2,000 for text cells. Many rows
  keep 200, where the cap protects the 6,000-char output budget.

### 4.6 Pitch prefill guard — `backend/app/proposals/`

- A `before_model` hook: if the last message is an `AIMessage` with no tool calls, end the run with no
  model call (`jump_to: "end"`). A run with nothing new to answer then does nothing, instead of a 400.
- Find what posted `messages: []` (trace `e3c0493d`, 14 Oct, `proposal-887`): `send` in
  `frontend/lib/useAgentChat.ts:133` always adds a user message, so look at the `load` path and any
  `runAgent` after `advance`. Fix that too, if found.

## 5. Security review

- **No new endpoint, table or catalog entry.** The SQL catalog's 37 tables are unchanged, so nothing
  new is reachable by model-written SQL.
- **The auto citation column is a column the model could already select.** It reads the same row,
  under the same RLS, in the same read-only transaction; `CITE_COLUMNS` only names id and foreign-key
  columns. Example: a member asking about `contacts` gets `[org:N]` on rows RLS already let them see.
- **The table map is the same text `db_list_tables` already returns** to every caller, signed in or not.
  It names tables, not rows.
- **`compare_fit` permissions are unchanged:** `matching.may_run` still refuses anyone who is not staff,
  a steward or an admin, before any output is built.
- No PII, credentials or tokens are touched. Langfuse keys stay in the environment.

## 6. Testing

Unit tests, no database:

- `test_compare_fit.py` (new): a shortlist built from fixture profiles where all 37 funders are strong or
  medium stays under 60,000 chars; a weak fit renders as one line with its first `!`; the
  `funder_ids` path still carries every criterion; the reply spans more than 50 lines.
- `test_agent_middleware.py` (new): the edit excludes `compare_fit`; below the trigger nothing is cleared;
  across three calls past the trigger the cleared set changes at most once.
- `test_sql_validator.py`: `org_locations ⨝ locations` without `org_id` gains `__cite__ol`; with
  `org_id` projected, nothing is added; aggregate, `DISTINCT`, `UNION` and CTE queries gain nothing;
  a model alias starting `__cite__` is rejected.
- `test_sql_render.py`: `__cite__` columns make markers and never print; one row keeps a 1,500-char
  description; ten rows still cut at 200.
- `test_prompt.py`: every `CATALOG` table name appears in the rendered prompt; no `{{` is left.
- `test_proposal_agent.py`: a state ending in an `AIMessage` makes no model call.

Integration: none new; no SQL changes against the compose Postgres beyond what the validator tests
cover.

Evals (cost money): one `canary` case, "What does Better Life Foundation do, where does it work, and
which funders fit it?", asserting one `compare_fit` call and no `read_file` on `/large_tool_results`.

Zero means unrecorded: the shortlist's `not_scored.funder_has_nothing_recorded` stays "unknown",
never folded into "weak". A test pins it.

## 7. Milestones

One PR per milestone, each stacked on the last, stopping for review between them.

#### Milestone 1: Measure

- **Deliverable**: numbers in this document's §4.1 and §4.2: shortlist size today by field, worst
  case, and the chosen trigger and batch values.
- **Touches**: none shipped (a script under `backend/scripts/` or a test that prints).
- **Key tasks**: [ ] render `compare_fit(8)` locally [ ] worst case from fixtures [ ] update §4.1–4.2
- **Acceptance criteria**: the plan's numbers are measured, not estimated.

#### Milestone 2: One compare_fit, and a cache that holds

- **Deliverable**: the shortlist fits; clearing is batched and spares `compare_fit`.
- **Touches**: backend (`matching_tools.py`, `middleware.py`), prompt (two skills).
- **Key tasks**: [ ] §4.1 [ ] §4.2 [ ] skills' reply table [ ] tests [ ] `make wiki-update`
  [ ] CHANGELOG
- **Acceptance criteria**: `cd backend && pytest tests/test_compare_fit.py tests/test_agent_middleware.py`;
  then, after Deploy, the same question in production: one `compare_fit`, no `/large_tool_results`
  read, cache read only climbing (`trace_cost.sh <trace>`).

#### Milestone 3: Fewer wasted SQL calls

- **Deliverable**: rows come back cited without a re-run; no guessed table names; one-row text in full.
- **Touches**: backend (`validator.py`, `render.py`, `prompt.py`), prompt (`instructions.md`),
  `docs/SQL_AGENT.md`.
- **Key tasks**: [ ] §4.3 [ ] §4.4 [ ] §4.5 [ ] tests [ ] `make wiki-update` [ ] CHANGELOG
- **Acceptance criteria**: `cd backend && pytest tests/test_sql_validator.py tests/test_sql_render.py tests/test_prompt.py`;
  `make evals TAG=canary` passes; the production re-run meets §1's targets.

#### Milestone 4: Pitch prefill guard

- **Deliverable**: a Pitch run with nothing new to answer ends quietly, never with a 400.
- **Touches**: backend (`proposals/`), maybe frontend (`useAgentChat.ts`).
- **Key tasks**: [ ] §4.6 hook [ ] find the empty-run trigger [ ] test [ ] CHANGELOG
- **Acceptance criteria**: `cd backend && pytest tests/test_proposal_agent.py`; no prefill 400 in
  Langfuse for a week of local use.

## 8. Open questions and risks

- **Does a compact shortlist lose anything the write-up needs?** `funder-shortlist-brief` writes weak
  fits as "the score and its first `!` card line", which is exactly what is kept. If a user asks about
  one weak funder, the model calls `compare_fit(org_id, [that funder])` for the detail. Risk: low.
- **Batch clearing can still bust the cache once per batch.** That is one cache rewrite per ~30k tokens
  cleared, not one per call. Acceptable.
- **The table map adds ~1k tokens to every Ask prompt.** It is cached after the first call; it removes
  one or two calls per cold question. Net saving.
- **The empty Pitch run's trigger may not be found** from one trace on 14 Oct. The guard fixes the
  symptom either way.
- **The re-run is in production, so nothing shows until Deploy runs** (Actions → Deploy, by hand).
  Production runs `claude-sonnet-5` as `MODEL` (from its Vercel env), so compare like with like.
- **Other questions may still hit the 40k path** before M2 ships. No mitigation beyond shipping M2 first.
