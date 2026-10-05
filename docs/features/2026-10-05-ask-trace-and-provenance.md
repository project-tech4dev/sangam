# Ask Sangam: one trace, one task, and a source for every row

## Context

When the agent runs, the Ask workspace shows the same thing twice. `TraceCard.tsx:61-66` (in the
chat) and `EvidenceRail.tsx:64-65` (in the 340px right rail) both render
`humanizeTool(step.tool).label` plus `.detail(step.args)`, one line per step — identical text, two
columns. The rail's only addition is a row of `CitationChip`s extracted from the raw tool result,
and those duplicate the chips already inline in the answer prose.

The split that was *designed* was never wired: `EvidenceRail.tsx:35` defines `executedSql()` and
never calls it, `citationTarget` is imported and unused, and the comment at `toolLabels.ts:17-18`
says "the query itself is shown in full by the evidence rail, which is what makes the answer
auditable" — it is shown in **zero** places. So the fix is partly finishing the original intent
rather than inventing a new one.

Second, nothing in the product says where a fact came from. 25 of the 41 catalogued tables carry
`source_url`; `orgs`, `funders`, `grants`, `programs`, `contacts`, `documents` and `rfps` carry all
five provenance columns. `instructions.md` never mentions `source_url`, no agent tool projects it,
and the frontend types it in four places and renders it in none. The product promise is that every
field traces to a source; today a user cannot see one.

**Outcome.** The chat says *what Sangam is doing right now*, one line per step. The rail says *what
the task is* — a high-level phase roll-up — plus the executed SQL and a **Sources** list of real,
clickable URLs with fetch dates. Nothing appears in both columns.

**Decisions taken** (asked and answered before planning):

- The high-level task is **derived client-side** from the tool sequence. No planning tool, no
  seventh tool, no backend change for this half. (langchain's `TodoListMiddleware` is in the
  installed stack if a real agent-authored plan is wanted later — filed as a follow-up, not built.)
- Source URLs at **both grains**: entity-level (an org's / funder's / grant's own source) and
  fact-level (the source of the rows a specific query read).
- **One PR**, landing as the four milestones below.

## Non-goals

- **No restyle.** Roadmap A10 (`features-plans/roadmap/2026-10-04-ui-roadmap.md`) moves
  `ChatPane`/`AnswerCard`/`TraceCard`/`EvidenceRail` onto the design system. This PR is behaviour
  only: reuse `.card`, `.card-kicker`, `.muted`, `CitationChip`. Per CLAUDE.md, a new look starts in
  the design system, not here.
- **No new agent tool** and no change to the six-tool invariant.
- `search_graph` and `fetch_url` provenance beyond what already exists: graph edges carry no URL at
  all, and the graph is dormant (`.memory/STATE.md`). `fetch_url`'s URL comes from `step.args`.
- Registry profile provenance lines (roadmap A6/A7). This PR only makes the Ask workspace show it.

## Known data gaps to state in the UI, not paper over

- `fit_scores`, `fit_score_items`, `score_adjustments`, `rubrics` have **no provenance columns**. A
  fit score has no source URL and never will have one — it is Sangam's own judgement. The rail must
  say "scored by Sangam against rubric vN", not show a blank.
- `news_mentions` names its link `url`, not `source_url` — handled by an explicit alias, not left to
  silently miss.
- Aggregate queries (`GROUP BY`, `count(*)`) cannot carry row-level provenance. The plan degrades to
  naming the tables read, and says so.

---

## Milestone 1 — `db_query` returns the sources of the rows it read

The one honest insertion point. `ValidatedQuery` already carries `tables`, `citations` and an unused
`aggregate` flag, and `_plan_citations` (`validator.py:467-487`) is the exact pattern to copy.

**`backend/app/agent/tools/sql/catalog.py`**
- Derive `PROVENANCE_COLUMNS: dict[str, dict[str, str]]` at import time next to `CITE_COLUMNS`
  (`catalog.py:994-998`) — per table, which of `url` / `name` / `fetched` roles exist and the real
  column name for each. Derived from `Table.columns`, never hand-listed, so it stays true as tables
  are added.
- One explicit alias map for the odd one out: `{"news_mentions": {"url": "url"}}`.

**`backend/app/agent/tools/sql/validator.py`**
- `ProvenancePlan(output_column, table, role)` mirroring `CitationPlan`.
- `_plan_provenance(qualified)` **maps first, then appends** — this is the part to get right:
  1. Walk the existing projections exactly as `_plan_citations` does (`validator.py:479-486`) and
     absorb any that already resolve to a provenance column into the plan. `SELECT *` matters here:
     `source_url`/`source_name`/`fetched_at` are in `STAR_COLUMNS`, so `_trim_expanded_star` leaves
     them in the projection. Appending on top would put the URL in every row *and* in the block, and
     the row budget would pay for it twice. **Side-effect to accept and document:** a model-selected
     `source_url` moves out of the row body into the `sources:` block.
  2. Append aliased projections only for what is missing, named `__prov__<alias>__<role>` — keyed on
     the **table alias**, not the table name. A self-join gives two aliases on one table, and
     `__prov__<table>__url` twice would collapse under psycopg's `dict_row`, which is the precise bug
     `_dedupe_output_names` exists for. Dedupe the *tuples* in `render.py`, not the projections.
  - Runs after `_dedupe_output_names` (the reserved prefix cannot collide) and before `_apply_limit`
    / `_plan_citations` — `source_url` has no `cites`, so it can never become a citation marker.
- Skip, with a reason string, when: `_is_aggregate()` is true, `DISTINCT` is set, the root is a set
  operation rather than `exp.Select`, or an outer scope source is not a plain `exp.Table` (a CTE or
  derived table). Adding a projection to any of those changes the result.
- **Be honest about CTE coverage.** `instructions.md:25` tells the model to write ONE joined query,
  so `WITH x AS (…) SELECT … FROM x` is a common shape and the skip rule fires on it — those queries
  get the `tables:` fallback, not row-level sources. Descending into a single non-aggregate CTE is a
  follow-up, not this PR.
- Add `provenance: tuple[ProvenancePlan, ...]` and `provenance_skipped: str | None` to
  `ValidatedQuery`.

**`backend/app/agent/tools/sql/render.py`**
- Exclude every planned provenance `output_column` from `body_columns`, exactly as `cited_columns` is
  excluded (`render.py:51-53`) — which covers both the appended `__prov__*` aliases and a column the
  model selected itself.
- Collect **distinct** `(table, source_name, source_url, fetched_at)` tuples and emit one
  `sources:` block, capped at `MAX_SOURCES = 8`. Budget it **outside** `MAX_OUTPUT_CHARS` so
  provenance never costs the model a row — the cost is O(distinct sources), not O(rows).
- **URLs bypass `render_cell`.** `MAX_CELL_CHARS = 200` truncates to `…(N chars total)`, and a
  truncated URL is a dead link in the rail. Render `source_url` raw; truncate only `source_name`.

**`backend/app/agent/tools/sql_tools.py`**
- Pass `provenance=query.provenance` into `render_rows` at the single call site (`sql_tools.py:175`).
- Add `tables: orgs, org_locations` to the success header (`sql_tools.py:182`). Cheap, and it is the
  one thing that still works on an aggregate, so the rail is never blank.
- **Order matters for tracing.** The block goes in the header region — after `executed:`, *before*
  `columns:`. `_redact_rows` (`app/integrations/tracing.py:39-56`) cuts everything after the
  `columns:` line, so a `sources:` block placed with the rows would disappear from every Langfuse
  trace whenever `LANGFUSE_MASK_TOOL_RESULTS` is on. Put it above the cut and no change to
  `tracing.py` is needed — provenance survives a masked trace for the same reason the SQL does.
- `backend/tests/test_tracing.py:268-277` pins the whole result string exactly (`"3 row(s).\n"` …),
  and `test_audit.py:19` pins a shorter one. Both move with the header change — expected, not a
  regression.

**`backend/app/agent/instructions.md`**
- A new rule: results may carry a `sources:` block; use its dates for the existing freshness rule
  (`instructions.md:15`), name the source in words for a scraped figure, and **do not paste URLs
  into the answer** — the workspace renders them. Say "scored by Sangam against rubric vN" for
  anything from `fit_scores`.

**Exit gate:** `cd backend && pytest -m "not integration"` green, with new cases in
`tests/test_sql_validator.py` (provenance planned for a plain join; absorbed rather than duplicated
for `SELECT *` and for a model-written `SELECT source_url`; distinct aliases on a self-join; skipped
for `GROUP BY`, `DISTINCT`, a UNION and a CTE-rooted query) and `tests/test_sql_render.py` (block
deduped, capped at 8, URL never truncated, row budget unchanged by its presence). The `sources:`
line grammar is a producer/consumer contract with **no consumer test** — there is no frontend test
runner — so pin it in `test_sql_render.py` with an exact-string assertion and name that test in a
comment in `sources.ts`. `tests/test_prompt.py` and `tests/test_tracing.py` green after the header
move. Then `pytest -m integration` against the compose Postgres on :5433 to prove a real query
returns real URLs.

## Milestone 2 — entity-level provenance reaches the Ask payload

**Start by counting, not coding.** Existing seeded data is unproven, so before building the rail's
source list, `make psql` and run
`SELECT count(*) FILTER (WHERE source_url IS NOT NULL), count(*) FROM orgs;` and the same for
`funders` and `grants`. If most rows are NULL, the entity grain has little to show and M3's
missing-source state is the main thing a user will see — worth knowing before M4 "fails" with no bug
in it.

`GrantRow` already has all three fields (`backend/app/schemas/grants.py:22-24`) and `/api/grants`
returns them. The other two are one column short each.

- `backend/app/schemas/orgs.py:17-18` — `OrgListItem` has `source_name` and `fetched_at`; add
  `source_url`. Add `o.source_url` to `LIST_SQL` (`backend/app/repositories/orgs.py:9`).
- `backend/app/schemas/funders.py` — `FunderListItem` has none of the three (they sit on
  `FunderDetail`). Add all three, and `f.source_url, f.source_name, f.fetched_at` to `LIST_SQL`
  (`backend/app/repositories/funders.py:23`).
- `frontend/lib/api/types.ts` — mirror the fields on `OrgListItem` / `FunderListItem`.
- `frontend/app/(agent)/ask/page.tsx:49-60` — carry them into `IndexPayload`; `RegistryIndex`
  (`features/ask/lib/citations.ts:3-8`) gains them per entity, and `citationTarget` returns them so
  the rail can list a source for anything the answer cited.
- Also carry `rubricVersion` onto `IndexPayload.scores` from `ScoreRow.rubric_version`
  (`frontend/lib/api/types.ts:54`, `backend/app/schemas/scores.py:15` — it already exists at both
  ends). Without it the rail cannot name the rubric, and "Sangam's own rubric judgement" with no
  version is the weaker line.
- **Every new `RegistryIndex` field must be optional.** `preview/sample.ts:16-19` builds a fixture
  index by hand; a required field there fails `npm run build`.

**Exit gate:** `pytest tests/test_orgs.py tests/test_funders.py` green; `/api/orgs` and
`/api/funders` each return `source_url` on the list shape, with the counts from the step above
recorded in the PR description so a sparse result is read as data coverage, not a bug.

## Milestone 3 — the rail becomes the task, the sources and the SQL

This is where the duplication dies. The rule: **label + detail live only in the chat; the phase
roll-up, sources and SQL live only in the rail.**

**New `frontend/features/ask/lib/phases.ts`** — the derived high-level task.
- Map each of the six tools to a phase: `db_list_tables` → "Finding the data", `db_describe_table` →
  "Reading the table structure", `db_profile_column` → "Checking how values are stored", `db_query`
  → "Querying", `search_graph` → "Reading the knowledge graph", `fetch_url` → "Reading a web page".
- `phasesFor(turn)` collapses consecutive steps into one phase each, with a count and a note (table
  names from `args`, or the latest `db_query.purpose`).
- **Render only phases that actually happened.** A pending phase the agent may never reach would be
  a guess, and the rail's job here is to be honest. The phase holding a `running` step is active;
  earlier ones are done.

**New `frontend/features/ask/lib/sources.ts`** — one source list per turn, from three inputs.
- Parse the `sources:` block out of each `db_query` step's `result` (fact-level).
- `args.url` from each `fetch_url` step.
- Entity-level: every citation in the answer, looked up in `RegistryIndex`.
- Dedupe by URL, cap at 10, keep `{ url, label, fetchedAt, grain }`.
- Move `executedSql()` here from `EvidenceRail.tsx:35`, finally calling it — and guard it, because
  `result` is typed `string` while the AG-UI protocol permits `ContentPart[]`, so
  `step.result.match()` can throw today.

**`frontend/features/ask/components/EvidenceRail.tsx`** — three sections replacing the step list:
1. **What Sangam is doing** — the phase list from `phases.ts`, live.
2. **Sources** — the list from `sources.ts`, each an `<a target="_blank" rel="noreferrer">` showing
   host + source name + "fetched <date>". Three states, all of which must render something:
   - a URL, when there is one;
   - "no source recorded" for a cited entity whose `source_url` is NULL — **never drop it
     silently**, or a data gap reads as a broken feature;
   - "scored by Sangam against rubric v2" for a `[score:N]`, using `rubricVersion` from M2; and the
     `tables: …` list from the header, with the skip reason, when a query was an aggregate or
     CTE-rooted.
3. **How it was queried** — one `<details>` per `db_query` step with the executed SQL, which is the
   claim `toolLabels.ts:17-18` has been making all along.

Drop from the rail: the per-step `label`/`detail` pair, and the `CitationChip` row (the answer prose
already carries those chips). Keep `IndexCard` as the pre-question state.

**`frontend/features/ask/components/TraceCard.tsx`** — stays the per-step activity log in the chat,
unchanged in shape. Delete the vestigial `const visible = steps;` (`TraceCard.tsx:8`) and the
orphaned hidden-tools doc comment at `toolLabels.ts:22`.

**`frontend/features/ask/lib/toolLabels.ts`** — delete the dead `write_todos` and `task` entries
(no such tools exist; `build.py:27-34` is the whole list) and correct the stale SQL comment.

**Constraints to honour:**
- `TraceCard`'s props must stay `{ steps, streaming }` — `preview/AskPreview.tsx:111` renders it
  against `SAMPLE_TRACE`, and the design doc says the sample "can't drift from the workspace".
- `.evidence-rail-slot` is `display: none` below 900px (`app/globals.css:382`). The rail's content is
  therefore not the only home for anything load-bearing; the phases are a summary of what the chat
  already shows step by step.
- `args` can be a partial JSON string mid-stream (`useAgentChat.ts:30-36` returns the input
  unchanged on parse failure), so every `detail(a)` and parser must tolerate a string.

**Exit gate:** `cd frontend && npm run lint && npm run build` both clean — type errors surface in
the build and never in `next dev`.

## Milestone 4 — prove it end to end

- `make up && make seed`, then ask "Which organisations in the base work in Assam?" signed in at
  `/ask`. Confirm: the chat shows one line per step and no SQL; the rail shows the phase roll-up,
  real `ngodarpan.gov.in` / organisation-site URLs with fetch dates, and the executed SQL under a
  `<details>`; and **no label or detail string appears in both columns**.
- Ask an aggregate ("How many organisations are in the base?") and confirm the rail names the tables
  read and says why there is no row-level source, rather than showing nothing.
- Ask something the model is likely to answer with a CTE ("Which funders gave the most across the
  cohort, by year?") and confirm the same fallback fires cleanly — this is the common shape
  `instructions.md:25` pushes the model toward, so it must not look broken.
- Confirm a cited org whose `source_url` is NULL renders "no source recorded".
- Ask a fit-score question ("How well does KABIL fit Axis Bank Foundation?") and confirm the rail
  says the score is Sangam's own rubric judgement rather than rendering an empty source.
- `make smoke` — 1 expected failure on a fresh clone (`documents: 96+`; `make seed` does not create
  those).
- `make evals TAG=canary` **only if the user asks** — it bills real model calls.

## Follow-ups to file, not build

- An agent-authored plan via langchain's `TodoListMiddleware`, replacing the derived phases. It is a
  seventh tool, so it moves `build.py`, `instructions.md`, the tool-count tests and
  `toolLabels.ts` together.
- Provenance columns for the score tables, or an explicit "Sangam judgement" provenance kind.
- `fetch_url` echoing its final URL (after redirects, which `web.py:32` currently discards) in the
  success path.
- Roadmap A10: move these four components onto the design system.
- Registry profile provenance lines (A6/A7) reusing `sources.ts`'s formatting.
