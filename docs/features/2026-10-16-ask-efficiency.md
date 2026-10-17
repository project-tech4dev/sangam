# Ask efficiency: one compare_fit, a cache that holds, fewer wasted queries

Status: **Draft v2**, 2026-10-16 (v1 the same day; v2 adds the tool-design gaps in §1.1 and
milestones M1 and M4). Branch `feat/ask-efficiency`. No earlier document covers this; it
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

### 1.1 Tool-design gaps (Draft v2)

Draft v2 checks Ask's seven tools, prompt, skills, middleware and evals against published
tool-design guidance and adds the gaps chosen for fixing. Milestone numbers are §7's.

Sources: Anthropic, "Writing effective tools for agents" [W], "Effective context engineering" [C],
"Building effective agents" [B]; Claude docs on defining tools [D], context editing [CE] and prompt
caching [PC]; LangChain deepagents context management [LC] and SQL agent [SQL]; Google Cloud
text-to-SQL [G].

**The gap table (guidance → Ask today → fix)**

| # | Guidance | Ask today | Fix | In |
|---|---|---|---|---|
| 1 | Cap every response, page it, steer on truncation [W]; return only what the next step needs [D] | `compare_fit(org_id)` has no cap. It returns every scored funder at full detail as **one JSON line**, which got evicted and was unreadable | A compact shortlist, rendered as text with a line per fact, under a 15k-token budget. `funder_ids` keeps full detail, so it acts as `response_format` without adding a parameter | M2 |
| 2 | Clearing breaks the cache, so use `clear_at_least` and `exclude_tools` [CE] | `ClearToolUsesEdit(trigger=40k, keep=5)` with no batching. It cleared on every call, the cache read stayed stuck at 7,338 tokens, and ~$0.66 of $0.87 went there | Raise the trigger, set `clear_at_least`, and `exclude_tools=("compare_fit",)`. Sangam Pitch shares the function | M2 |
| 3 | Preload a little, retrieve the rest on demand [C]; list the tables first [SQL] | No table list in the prompt, so the model guessed `org_themes`/`themes` and then called `db_list_tables` | Put a `{{TABLE_MAP}}` in `instructions.md`, built from `CATALOG` in `prompt.py` | M3 |
| 4 | Poka-yoke: make mistakes hard to make [B] | A row is cited only if its id is in the SELECT. A locations query came back uncited and was re-run | The validator adds a `__cite__<alias>` id column, the same way `_plan_provenance` adds `__prov__` | M3 |
| 5 | Return meaningful context [W] | `MAX_CELL_CHARS=200` cut `orgs.description`, which led to two `substring()` queries | For a one-row result, text cells go up to 2,000 characters | M3 |
| 6 | Token-efficient responses [W] | Every `db_query` repeats each table's full caveats (orgs ≈ 840 chars, funder_activity ≈ 2,465) and the full rewritten SQL | **Caveats once per turn** (user's choice). **Remove the SQL echo** from the text and move it to the tool artifact | M3 |
| 7 | One clear place for each instruction [D]; avoid ambiguity [C] | The prompt duplicates tool docstrings (rule 7 ≈ profile_column's, rules 6, 8, 9, 10, 12, 14, 15). `fetch_url` points to a web-search tool that doesn't exist. `db_profile_column` errors use the `db_query rejected:` prefix, so the retry limiter doesn't count them. Rule 4 cites "rule 16" for compare_fit, which is rule 12. `build.py` says the audit is "off unless configured", but it is on by default | Cleanup PR (detail below) | M4 |
| 8 | Evaluate with realistic tasks; track tool calls, tokens, cost [W] | Evals score rows, citations and text only. Nothing counts tool calls or cost | The eval harness records tool calls, tokens and cost per case. Cases get optional budgets. Add a Better Life Foundation canary | M1 |

**Considered and not done.** A workflow tool like `get_org_profile` ([W] principle 1). The repo removed
four such lookups because they were worse than the model's own SQL (CLAUDE.md, "There used to be four
hand-written tools"). Gaps 3–5 bring the org lookup down to about 2 SQL calls without one. `strict`
tools and `input_examples` [D/S]: no failures in the trace call for them.

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
| Sangam Pitch (`proposals/agent.py`) | 1 | also uses `clear_old_tool_results()` | in scope | gets the cache fix for free; prefill guard in M5 |
| `agent/tools/sql/validator.py`, `render.py` | 0 | auto citation id, single-row cells | in scope | |
| `agent/tools/sql/catalog.py` | 1 | source of the table list and `CITE_COLUMNS` | read only | no table added; not a security change |
| `agent/instructions.md`, `agent/prompt.py` | 0 | table map, rule 8 wording | in scope | |
| Sangam Import (`ingest/`) | 1 | shares `harness.filesystem`, not `clear_old_tool_results` | unaffected | Import's own eviction stays as is |
| Funder Match page and saved runs (`matching/service.py`) | 2 | store `match()`, never `compare()` | unaffected | |
| `tests/evals/` | 1 | golden questions run through the real agent | in scope | one new canary for this question |
| `agent/tools/web.py::fetch_url`, `build.py` | 0 | `fetch_url` removed from Ask (M4) | in scope | `make_web_search` stays: Import uses it (`ingest/tools/research_tools.py:21`) |
| `agent/skills/news-brief/SKILL.md` | 1 | its "fetch_url its main link" step | in scope | cites `[news:N]` and gives the link as is |
| `agent/middleware.py::sql_retry_limiter` | 0 | counts `db_profile_column` errors too (M4) | in scope | |
| frontend `features/ask/lib/sources.ts` | 1 | `executedSql` reads the SQL echo that moves to the artifact (M3) | in scope | fall back to the call's `sql` argument; `fetch_url` labels stay for old chats |
| `tests/evals/harness.py`, `test_golden.py` | 1 | record tool calls, tokens, cost; per-case budgets (M1) | in scope | `EXECUTED` regex reads the artifact after M3 |
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
 browser ─▶ Next.js /api/copilotkit ─AG-UI─▶ FastAPI /agent ─▶ Ask deep agent (MODEL)
 ┌─ system prompt ───────────────────────────────────────────────────────────────────────────┐
 │ instructions.md: rules only; each tool's how-to lives once, in its docstring        (M4)   │
 │ + {{TABLE_MAP}}: 37 tables, one line each, from catalog.py, cached                  (M3)   │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
 ┌─ middleware ───────────────────────────────────────────────────────────────────────────────┐
 │ Filesystem   unchanged ─ a safety net, no longer the normal path                           │
 │ sql_retry    also counts db_profile_column errors                                   (M4)   │
 │ ClearToolUses higher trigger · clear_at_least (one batch) · never compare_fit       (M2)   │
 │               ─▶ fires rarely, prefix stable, cache keeps climbing                         │
 │ answer_audit unchanged                                                                     │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
 ┌─ tools ────────────────────────────────────────────────────────────────────────────────────┐
 │ db_list_tables · db_describe_table · db_profile_column (own error prefix)           (M4)   │
 │ db_query ─▶ validator (+__prov__, +__cite__ id when none projected)                 (M3)   │
 │          ─▶ executor (unchanged)                                                           │
 │          ─▶ render: caveats once per turn, then one line · SQL in artifact, not text (M3)  │
 │                     one-row text up to 2,000 chars · every row cited first time            │
 │ compare_fit(org_id)        ─▶ shortlist text: strong/medium full, weak 1 line, <15k  (M2)  │
 │ compare_fit(org_id, ids)   ─▶ full detail, text                                            │
 │ search_graph            fetch_url REMOVED: Ask has six tools                       (M4)   │
 │ skills: unchanged names; funder-matching's reply table updated                      (M2)   │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
 evals: + tool calls, tokens, cost per case; budgets like compare_fit ≤ 1           (M1)

 BLF question: db_query org ─▶ db_query places+themes ─▶ compare_fit once ─▶ write-up
               ≈ 4 tool calls · ≈ 5 model calls · target < 60 s, < $0.25
```

### How the agent picks tables, per question (after M3)

```
question ─▶ table map in the prompt (37 lines: name — catalog description)
         ─▶ model matches the question's nouns to descriptions ─▶ 2-4 candidate tables
         ─▶ db_describe_table(candidates): columns, allowed values, FKs BOTH directions, caveats
         ─▶ db_profile_column, only before filtering on free text (legal_form, locations.name)
         ─▶ ONE joined db_query ─▶ rows cited automatically
```

| question part | words | map line that matches | tables |
|---|---|---|---|
| "what does BLF do" | org, does | `orgs — CSOs/NGOs in the FFRH cohort` | orgs (description, website) |
| "where does it work" | where, works | `org_locations — Where an org is registered or operates` | org_locations ⨝ locations |
| "its themes" | theme, sector | `org_tags — Which sector/population/theme tags an org carries` | org_tags ⨝ tags |
| "which funders fit" | funders, fit | rule 12 + `funder-matching` skill, not a table | compare_fit |
| "who funded X in 2023" | funded, grant | `funder_activity — … A grant to an organisation is a 'partner' line … there is no grants table` | funder_activity ⨝ funders |

The catalog descriptions are the routing layer. Where a question still picks the wrong table, the fix
goes in that table's `description` in `catalog.py`, not in the prompt, so the map and
`db_list_tables` stay one text.

**Touched:** the model (fewer, cheaper calls). **Not touched:** Postgres schema, Neo4j, Supabase
Storage, REST routes. The frontend only for the evidence rail's SQL source (M3).

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

### 4.7 Evals measure cost — `backend/tests/evals/`

- `harness.py::run_agent` also returns a `RunStats`: tool calls by name, model calls, and
  input / output / cache-read / cache-write tokens from `AIMessage.usage_metadata`, with a cost.
- `cases/golden.jsonl` gains optional `max_tool_calls` and `max_calls` (e.g. `{"compare_fit": 1}`),
  checked in `test_golden.py`; `make evals` prints each case's stats.

### 4.8 Caveats once per turn — `backend/app/agent/tools/sql/render.py`

- A `ContextVar[set[str]]` of tables already caveated, set fresh per `/agent` request beside
  `agent_caller` (`db/pool.py:40`).
- `_caveats_for` gives a table's full caveats the first time it appears in a turn, then one line:
  "orgs: caveats as above. Rows here are only what this user can see; 0 rows is not 'none exist'",
  so the result still stands alone if the earlier one was cleared.
- Example: `funder_activity`'s caveats are ≈2,465 chars; three queries on it in one turn pay that once.

### 4.9 The SQL echo moves to the artifact — `db_query`

- `db_query` returns `(content, artifact)` with `response_format="content_and_artifact"`. The executed
  SQL goes in the artifact; the `adjusted:` line in the text still says what the validator changed.
- Consumers: the evals' `EXECUTED` regex reads `ToolMessage.artifact`; the evidence rail
  (`frontend/features/ask/lib/sources.ts:40`, `executedSql`) uses the artifact if AG-UI delivers it,
  else the tool call's `sql` argument.

### 4.10 Tool text cleanup, and `fetch_url` removed (M4)

- Prompt rules that restate a docstring (rule 7 ≈ `db_profile_column`'s; rules 6, 8, 9, 10, 12, 14, 15)
  shrink to one line pointing at the tool. The docstring is the single source; the test that every
  registered tool is named in the prompt still passes.
- `db_profile_column` errors get their own prefix (`db_profile_column rejected:`) and
  `sql_retry_limiter` counts them.
- Rule 4's "rule 16" becomes rule 12; `build.py:73`'s "off unless configured" comment is corrected
  (the audit is on by default).
- `fetch_url` is removed (decided 16 Oct). It pointed at a web-search tool Ask does not have. Ask then has
  six tools: drop it from `TOOLS` and the import in `build.py`, delete it from `tools/web.py`, drop its
  paragraph from `instructions.md:9` and the step in `news-brief`, update `tests/test_harness.py:113`,
  CLAUDE.md ("seven tools", the diagram, the citation-exception line) and the comments in
  `tools/files.py:63` and `core/egress.py:2`. Frontend labels stay, for old chats.

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
- **Removing `fetch_url` shrinks Ask's egress surface**: Ask no longer fetches any model-supplied URL.
  `guarded_client` stays for Import and the news pipeline.
- **The SQL in the artifact is the SQL the text echoed before**, to the same caller.
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
- `test_sql_render.py`: a second result on the same table in one turn prints the one-line caveat;
  a new request starts the set empty.
- `test_harness.py`: Ask's tool list is the six, without `fetch_url`; `db_profile_column` errors count
  toward the retry limit.
- `tests/evals`: `RunStats` sums `usage_metadata` correctly on a recorded message list (no model call).
- `test_proposal_agent.py`: a state ending in an `AIMessage` makes no model call.

Integration: none new; no SQL changes against the compose Postgres beyond what the validator tests
cover.

Evals (cost money): one `canary` case, "What does Better Life Foundation do, where does it work, and
which funders fit it?", asserting one `compare_fit` call and no `read_file` on `/large_tool_results`.

Zero means unrecorded: the shortlist's `not_scored.funder_has_nothing_recorded` stays "unknown",
never folded into "weak". A test pins it.

## 7. Milestones

One PR per milestone, each stacked on the last, stopping for review between them. Every PR runs
`make wiki-update` and adds a CHANGELOG line.

#### Milestone 0: This plan

- **Deliverable**: Draft v2 of this document, committed before any code.

#### Milestone 1: Measure, and teach evals to measure

- **Deliverable**: §4.7; the numbers in §4.1–4.2 (shortlist size by field, worst case, the chosen trigger
  and batch values); a Better Life Foundation canary with `max_calls.compare_fit = 1` and no `read_file`
  on `/large_tool_results`.
- **Touches**: `tests/evals/` only.
- **Acceptance criteria**: `make evals TAG=canary` prints each case's tool calls, tokens and cost; the
  plan's numbers are measured, not estimated.

#### Milestone 2: One compare_fit, and a cache that holds (gaps 1–2)

- **Deliverable**: §4.1, §4.2; the reply table in `funder-matching` and wording in `funder-shortlist-brief`.
- **Touches**: backend (`matching_tools.py`, `middleware.py`), two skills.
- **Acceptance criteria**: `cd backend && pytest tests/test_compare_fit.py tests/test_agent_middleware.py`;
  the BLF canary passes; after Deploy, the production re-run calls `compare_fit` once, reads no
  `/large_tool_results`, and its cache read only climbs.

#### Milestone 3: Fewer and leaner SQL calls (gaps 3–6)

- **Deliverable**: §4.3, §4.4, §4.5, §4.8, §4.9; rule 8 reworded; `docs/SQL_AGENT.md` and CLAUDE.md's
  "only substitution" sentence updated.
- **Touches**: backend (`validator.py`, `render.py`, `prompt.py`, `db_query`), `instructions.md`,
  frontend (`sources.ts`).
- **Acceptance criteria**: `cd backend && pytest tests/test_sql_validator.py tests/test_sql_render.py tests/test_prompt.py`;
  `cd frontend && npm run lint && npm run build`; the production re-run meets §1's targets.

#### Milestone 4: Tool text cleanup (gap 7)

- **Deliverable**: §4.10.
- **Touches**: `instructions.md`, `build.py`, `tools/web.py`, `middleware.py`, `news-brief`, CLAUDE.md.
- **Acceptance criteria**: `cd backend && pytest && ruff check .`; Ask registers six tools.

#### Milestone 5: Pitch prefill guard

- **Deliverable**: §4.6: a Pitch run with nothing new to answer ends quietly, never with a 400.
- **Touches**: backend (`proposals/`), maybe frontend (`useAgentChat.ts`).
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
- **AG-UI may not deliver a tool's artifact to the browser.** Then the evidence rail reads the SQL
  from the tool call's `sql` argument, which is the model's SQL, not the rewritten one. Checked in M3.
- **One-line caveats rely on the first result still being in context.** The one-line form repeats the
  RLS and false-zero warning, which is the part that changes an answer.
