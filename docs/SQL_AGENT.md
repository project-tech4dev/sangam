# Safe Text-to-SQL agent for Sangam

> **Status: planned, not implemented.** Written 2026-09-27. This is the design of record for
> the `db_query` agent tool and the read-only boundary it runs behind. Jump to
> [Milestones](#milestones) for the build order; each milestone is one PR.

## Context

The agent has six hand-written tools. Each wraps one fixed SQL statement, so any question
outside those shapes — counts, aggregates, cross-entity joins, "which funders fund more than
one org in Manipur" — cannot be answered at all. We want the model to compose its own SQL
while the database stays structurally unable to be damaged or over-read.

The safety bar is set by what's actually in this database, verified live today:

- `sangam` is a **Postgres superuser** (`rolsuper = t`) and the only login role. The REST API,
  the agent's tools, and the LangGraph checkpointer all connect as it.
- `checkpoints`, `checkpoint_writes`, `checkpoint_blobs` sit in the **same database** —
  1,348 rows of serialized conversation history. One `SELECT` reaches all of it.
- As superuser, `SELECT pg_read_file('/etc/passwd')` is a valid single-statement `SELECT`
  that succeeds even inside a `READ ONLY` transaction.
- Per `docs/DEPLOY.md:100-113`, the deployed backend has **no authentication**.

So the design is not "validate the SQL." It is: validate the SQL, *and* make the database
refuse anything the validator missed.

### Prior art: Dalgo's Chat with Data

`DDP_backend/ddpui/core/ai/` (5,141 lines) solves this problem for the same team against
customer warehouses. Read `ddpui/core/ai/CLAUDE.md` before starting. Where it and this plan
agree, that is two independent derivations; where they differ, the difference is justified
below. Seven things are adopted outright — `profile_column`, `content_and_artifact`, the
retry-budget middleware, execution-based evals, the metadata/value tool split, context-editing
middleware, and the post-answer audit.

**Three things deliberately not copied, with reasons:**

| Dalgo does | We don't | Because |
|---|---|---|
| **scan-then-ask** discovery over every non-system schema (`9ef0647b`) | static catalog | Their allowlist locked the agent out of real data — a *customer's* warehouse has arbitrary, changing, 140-table schemas. Ours is 30 tables we own, defined in `db/init/02_schema.sql` in this repo. A static catalog buys column-level exclusion, PK→citation mapping, and defect annotations that scan-then-ask cannot. |
| **two agents** sharing one history | one agent | Six of their last fifteen commits (`b16b7120`, `4da38c19`, `e516f2e6`, `d29b7346`, `f24a84be`, `8338f358`) exist only to stop the two agents confusing each other — including a middleware that rewrites one agent's tool errors so they stop poisoning the other. Their own lesson: if you can keep to one agent, do. |
| **HITL approval** before every `execute_sql` | no approval gate | Their warehouse credentials are read-write, so a click is the last line of defence. With the reader role we have a server-side one. Revisit if we ever expose writes. |

**Their v1 limitation is the thing we already decided to fix**
(`docs/docs/features/chat-with-data-dev.md:96-99`):

> Read-only is enforced at the SQL-AST layer; warehouse credentials are read-write
> (read-only role per org is a fast-follow).

### Deliberate deviation from the brief

The request named SQLAlchemy. It cannot provide the guards asked for — `text()` executes
`DROP TABLE` as readily as `SELECT` — so validation needs an AST parser: **sqlglot** (zero
runtime deps, ~5 MB, dialect-aware). For *execution*, SQLAlchemy would add a second
connection abstraction beside the psycopg pool the whole app already shares, for a database
we cannot leave anyway (`pgvector`, `pg_trgm similarity()`, jsonb operators and
`LATERAL ... ON true` are load-bearing across `repositories/` and `db_tools.py`).

Portability is instead delivered by `validate(sql, dialect=...)` plus an `Executor` Protocol.
A second database means one new `Executor` class and one config value; the validator does not
change. **The intent of the requirement is met; the letter is not.** Say so at review.

---

## Design

```
db_list_tables ──┐
db_describe_table ┤─→ catalog.py   data: tables · columns · enums · FKs · citation kinds · defects
db_query ─────────┘         ↓
                      validator.py  pure, sqlglot only, no I/O → ValidatedQuery
                            ↓
                      executor.py   READ ONLY txn + SET LOCAL statement_timeout + SET LOCAL ROLE
                            ↓
                      render.py / errors.py   rows → cited text · psycopg error → fix instruction
```

Four rules everything else follows from:

1. **The model's SQL string never reaches Postgres.** What executes is the *regenerated AST*
   (`validated.sql(dialect="postgres", comments=False)`). This is what actually kills
   multi-statement injection and comment smuggling, and it makes the projection→citation
   map deterministic.
2. **The catalog is the only source of table/column truth**, verified against
   `information_schema` at boot.
3. **Validation is a pure function** — no pool, no async, no settings. That is what makes
   ~45 adversarial tests cost zero seconds and no container.
4. **The retry loop already exists.** `deepagents` feeds a tool's returned error string back
   to the model. We do not build a second loop; we only make the error carry enough to converge.

### New files

```
backend/app/agent/tools/sql/catalog.py     allowlist as data + verify_against_db()
backend/app/agent/tools/sql/validator.py   sqlglot; pure; returns ValidatedQuery
backend/app/agent/tools/sql/executor.py    Executor Protocol + PsycopgExecutor
backend/app/agent/tools/sql/errors.py      psycopg error → model-facing fix instruction
backend/app/agent/tools/sql/render.py      rows → compact cited string
backend/app/agent/tools/sql_tools.py       the four @tool functions
db/migrations/0001_sql_reader_role.sql     NOLOGIN reader role (first migration in the repo)
backend/tests/test_sql_{validator,errors,render,tools}.py   pure unit
backend/tests/test_sql_integration.py      @pytest.mark.integration
backend/tests/evals/                       golden cases (see below)
```

### 1. Catalog — a Python module, not YAML

It is a security allowlist: it must show up in a diff, be importable by pure unit tests, and
have no parse step at boot. Frozen dataclasses; `catalog.py` holds **no logic** beyond an
import-time self-check and `verify_against_db()`.

```python
@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str                      # as written in db/init/02_schema.sql
    note: str = ""                 # meaning / gotcha, shown by db_describe_table
    values: tuple[str, ...] = ()   # verbatim CHECK enum — free, accurate, no row sampling
    cites: str | None = None       # "org" | "funder" | "grant" | "score"
    heavy: bool = False            # selectable explicitly, excluded from `*` expansion

@dataclass(frozen=True, slots=True)
class Table:
    name: str
    description: str               # one line; the model reads this in db_list_tables
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()
    defects: tuple[str, ...] = ()  # evidence-backed caveats, injected into every result
```

Derived once at import: `TABLE_NAMES`, `COLUMNS`, `SQLGLOT_SCHEMA` (what `qualify()` wants),
`STAR_COLUMNS` (non-heavy only), `CITE_COLUMNS`, `DEFECTS`.

**In (28 tables):** orgs, funders, grants, programs, rfps, rfp_matches, fit_scores,
fit_score_items, rubrics, rubric_criteria, score_adjustments, contacts, documents, chunks,
news_mentions, tags, locations, extraction_log, the two `*_identifiers`, and all eight
`*_tags` / `*_locations` join tables.

**Out entirely** — a reference is an "unknown table" error: `checkpoints`, `checkpoint_blobs`,
`checkpoint_writes`, `checkpoint_migrations`, `schema_migrations`, `graph_ingest_log`,
`threads`, `users`.

**Column-level exclusions** (an excluded column simply does not exist → fails as "unknown
column" with the allowed list attached; one code path, no second denylist):

| Excluded | Why |
|---|---|
| `contacts.email`, `contacts.phone` | `get_funder` already projects only name/role/kind/verified. A general tool would newly put personal contact details into chat transcripts — which are themselves stored in `checkpoints`. |
| `chunks.embedding` | 1536 floats ≈ 20 KB of text per row. |
| `chunks.content_tsv` | machine-only. |
| all of `users` | one seeded dev user; `email` is the only interesting column and it is PII. **This deviates from the brief's "users" entity** — re-adding `display_name` only is one `Table(...)` entry. |

**Defect strings are part of the catalog and are injected into every result touching the
table.** Verified live today:

```python
defects=("org_id IS NULL for all 118 rows — any JOIN on org_id returns zero rows. "
         "Zero results here mean 'not linked', never 'no news exists'.",)
```
Same for `documents` (53/96 ownerless) and `locations` (10/10 districts parented to Assam).
This is where the pending schema work lands: when those migrations fix the data, the defect
lines get deleted. The catalog is the seam between the two workstreams.

**Startup verification** in `lifespan.py`, between `db_pool.pool = pool` (`:53`) and
`build_agent` (`:64`): compare catalog names against `information_schema.columns` and
**raise on drift**. Deliberately *not* the "optional subsystems degrade" rule — that rule
covers external integrations (Neo4j, Langfuse). A catalog disagreeing with the schema is an
internal bug, and a tool describing a dropped column produces confidently wrong answers.
Extra DB tables not in the catalog log at INFO, so a new table gets a decision rather than
silently becoming invisible.

### 2. Validator — pure, sqlglot

```python
def validate(sql: str, *, max_rows: int = 50, dialect: str = "postgres") -> ValidatedQuery
```
returning `sql` (regenerated), `tables`, `limit`, `citations`, `rewrites`, `aggregate`; raising
`SqlRejected` whose message is written *for the model*.

Passes, in order:

- **One statement, and it is a query.** Length guard → `sqlglot.parse()` → exactly one
  statement → `isinstance(root, exp.Query)` as a *positive* check (this rejects `COPY`,
  `VACUUM`, `LISTEN` by construction, since sqlglot renders them as `exp.Command`). Then a
  *negative* check, because a `Query` can still contain a write:
  `find_all(exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
  exp.TruncateTable, exp.Copy, exp.Grant, exp.Command, exp.Set, exp.Transaction)` — every name
  verified present in sqlglot 27.29 (M0). Note `COPY` is `exp.Copy`, `TRUNCATE` is
  `exp.TruncateTable` and `GRANT` is `exp.Grant` — *not* `exp.Command` as the DDP list assumes.
  `LISTEN foo` parses as `exp.Alias`, caught by the positive `isinstance(root, exp.Query)` check
  rather than the node scan. This is what catches
  `WITH x AS (DELETE FROM orgs RETURNING *) SELECT * FROM x`. Plus `args["into"]`
  (`SELECT * INTO t` parses as a plain Select), `args["locks"]` (`FOR UPDATE`), and
  `WITH RECURSIVE` (Postgres materialises it, so an outer LIMIT does not stop a runaway —
  and the only hierarchy here, `locations`, is 2 levels and self-joins).
- **Tables.** Reject CTE names that shadow real tables (makes column resolution ambiguous);
  reject `tbl.catalog` or a non-`public` `tbl.db` (`information_schema.*`, `pg_catalog.*`);
  reject a non-`Identifier` table, which is what `FROM generate_series(...)`,
  `FROM dblink(...)`, `FROM pg_read_file(...)` all parse as; then every remaining name must
  be in the catalog, with `difflib` near-misses in the error.
- **Functions — allowlist, not denylist**, precisely because the connecting role is a
  superuser. Plus typed nodes that bypass `exp.Anonymous` (`exp.CurrentUser`,
  `exp.GenerateSeries`, `exp.Unnest`), `exp.Dot` chains reaching `pg_catalog`, placeholders,
  and casts to `regclass`/`oid`.
- **Columns.** `qualify(root, schema=SQLGLOT_SCHEMA, validate_qualify_columns=True)` expands
  `*` and resolves every column; then a conservative `build_scope()` walk re-checks every
  column against a real table, so a sqlglot quirk on a LATERAL can never silently widen access.
  `SELECT *` expands from `STAR_COLUMNS` (non-heavy), so it cannot detonate the context
  window — reported in `rewrites` so the model still learns `profile` exists.
  **Duplicate output names are auto-aliased** (`SELECT o.id, f.id` → `orgs_id`, `funders_id`):
  the pool's `dict_row` factory would otherwise silently keep only the last `id`.
- **LIMIT.** Clamp to ≤200, reject a non-literal `LIMIT (SELECT …)`, then apply `limit + 1` so
  the executor can detect truncation. **Corrected in M0:** `FETCH FIRST n ROWS ONLY` does *not*
  occupy a separate `args["fetch"]` slot — it lands in `args["limit"]` as an `exp.Fetch` node
  (count in `args["count"]`, versus `exp.Limit`'s `.expression`). `Query.limit(n)` replaces
  either cleanly, and does so at the top level of a `UNION` root. So `FETCH FIRST` is **clamped
  like any other limit, not rejected** — one less thing for the model to get wrong.
- **Generate** with `comments=False` — strips `-- ; DROP TABLE orgs` payloads.

**Round-trip risk, and the corpus that already exists.** Executing the regenerated AST trades
a fidelity risk for every other guarantee. The proof corpus is already in the repo: the seven
queries in `app/agent/tools/db_tools.py` cover `LEFT JOIN LATERAL (…) ON true`,
`array_agg(x ORDER BY y)`, `string_agg`, `similarity()`, `ILIKE '%' || x || '%'`,
`COALESCE(…, '{}')`, `ORDER BY … DESC NULLS LAST`.

**M0 result: 8/8 stable, so the fallback is not needed.** One correction to how the test must be
written: assert **idempotence of generation** (`gen(parse(gen(parse(s)))) == gen(parse(s))`), not
`repr` equality of the two ASTs. sqlglot upper-cases unknown function names on output, so
`similarity(name,'x')` → `SIMILARITY(name,'x')` and the reprs differ while the SQL is identical
(Postgres folds unquoted function names). A repr-equality test false-fails on every pg_trgm call
in the corpus.

*Fallback, if a future query ever does fail:* execute the model's original text, keep the AST for
validation, and map citations by ordinal position.

### 3. Executor

```python
class Executor(Protocol):
    async def run(self, query: ValidatedQuery) -> list[dict[str, Any]]: ...
```

`PsycopgExecutor` uses the existing pool (`app/db/pool.py::get_pool`). The pool is
`autocommit=True` with **no `configure=` hook** (`app/db/checkpointer.py:20-27`), so
`async with conn.transaction():` is what makes the guards mean anything:

```python
async with conn.transaction():                     # autocommit=True → emits BEGIN
    await conn.execute("SET TRANSACTION READ ONLY")  # must be the first statement
    await conn.execute(f"SET LOCAL statement_timeout = {self._timeout_ms}")
    await conn.execute("SET LOCAL lock_timeout = 1000")
    await conn.execute("SET LOCAL idle_in_transaction_session_timeout = 10000")
    if self._reader_role:
        await conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self._reader_role)))
    return await traced_fetch(conn, query.sql, None, name="agent-sql")
```

- Everything is transaction-scoped and reset by the COMMIT/ROLLBACK on exit. **Nothing leaks
  onto the pooled connection** — which matters enormously, because that same connection is
  handed back to the checkpointer, which *writes*.
- **Rejected alternative:** `conn.set_read_only(True)` is connection-level state on a pool with
  no reset hook. One missed `finally` and every later checkpoint write on that connection fails.
- `SET LOCAL statement_timeout = %s` does not work — Postgres `SET` takes no bind parameters.
  The int is interpolated from `Settings`, never from the model; a test asserts it is an `int`.
- `params=None` means psycopg does not scan for `%`, so `ILIKE '%kabil%'` survives. The
  multi-statement exposure that opens is closed upstream by AST regeneration — **and
  independently by the wire protocol**: the extended query protocol rejects multiple
  statements in a Parse message server-side. **M0 measured both sides:** with `prepare=False`
  psycopg uses the simple protocol and `SELECT 1; RESET ROLE` **executes**; with `prepare=True`
  the server refuses it — *"cannot insert multiple commands into a prepared statement"*. This is
  load-bearing, not theoretical. Today it holds only because the pool sets
  `prepare_threshold=0`, which someone could change. Make it explicit by passing
  `prepare=True` on this execute rather than inheriting it (`traced_fetch` does not forward
  `prepare` — either extend its signature or assert the behaviour in
  `test_multi_statement_cannot_reach_the_server`).
- `traced_fetch` unchanged → the executed SQL and row count land on the Langfuse span as a
  `retriever` observation, same as every other tool.
- **`asyncio.Semaphore(2)`.** The pool is `max_size=5` and shared with the checkpointer, which
  writes on *every* graph step. Two concurrent runs each holding a connection for 5 s can stall
  checkpointing app-wide. This is the most likely production incident from this feature — an
  operational constraint, not a detail.

### 4. Tier (c): a `NOLOGIN` reader role — no second secret, no second pool

The cheap version of the strongest guard:

```sql
-- db/migrations/0001_sql_reader_role.sql   (the repo's first migration)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sangam_reader') THEN
    CREATE ROLE sangam_reader NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO sangam_reader;
GRANT SELECT ON orgs, funders, grants, /* …the 28 catalog tables… */ TO sangam_reader;
-- Column-level where the catalog excludes columns, so a hole in column validation still
-- cannot reach the PII. This is the whole point of the tier; a table-level GRANT on
-- contacts would hand over email and phone anyway.
GRANT SELECT (id, org_id, funder_id, name, role, kind, verified, notes,
              source_url, source_name, fetched_at, content_hash, extractor_version)
  ON contacts TO sangam_reader;
GRANT SELECT (id, document_id, chunk_index, content) ON chunks TO sangam_reader;
GRANT sangam_reader TO CURRENT_USER;   -- not a hardcoded 'sangam'/'postgres' → Supabase too
```

- `NOLOGIN` ⇒ **no password, no `.env` entry, no second DSN, no second pool.**
- `SET LOCAL ROLE` reverts at COMMIT, so nothing leaks onto the shared pool.
- **Verified in M0**, against the live database in a rolled-back transaction: after
  `SET LOCAL ROLE`, `current_user` is `spike_reader` and `rolsuper` flips `t` → `f`.
  `SELECT * FROM checkpoints` → *permission denied*. `pg_read_file('/etc/passwd')` →
  *permission denied for function*. `INSERT INTO orgs` → *permission denied*. Column-level
  GRANT behaves as designed: `SELECT name FROM contacts` works, `SELECT email FROM contacts`
  and bare `SELECT * FROM contacts` are both denied.
- **Honest limit: `RESET ROLE` restores the superuser session**, so the role is a boundary for
  *single statements only*. It is not the unconditional server-side guarantee a LOGIN role with
  its own connection would be. That matters only if an attacker can execute a second statement,
  which is blocked three independent ways — the parser's single-statement check, AST
  regeneration, and the extended wire protocol (below). The role still does the job it was
  added for: a hole in the *function allowlist* stops being a data breach. It does not cover a
  hole that permits multi-statement execution.
- Deliberately **not** `ALL TABLES IN SCHEMA public` and **not** `ALTER DEFAULT PRIVILEGES`: a
  table added tomorrow must be denied until someone decides it is safe. `test_grants_match_allowlist`
  asserts the GRANT list ≡ the catalog, **at column granularity for the two column-level tables**.
- **Fail closed when the role is absent.** Gating on `Settings.sql_reader_role` being non-empty
  does not detect an *unmigrated* database: `SET LOCAL ROLE sangam_reader` then fails with
  `42704` on every query, and the `42501` mapping would misdiagnose a `SET ROLE` denial as
  "table not readable". So: check `pg_roles` at boot alongside `verify_against_db`, and if the
  role is configured but missing, `db_query` returns
  *"SQL tool unavailable: reader role not present — run `make migrate`"* — the same shape as
  `search_graph` when Neo4j is off. It must **not** silently fall back to running as superuser.
- **`GRANT … TO CURRENT_USER` assumes the migration user and the runtime user are the same
  role.** Locally that is trivially true. On Supabase, `make migrate ENV=staging` runs as
  `STAGING_DB_USER` while the Vercel backend connects as whoever is in *its* `DATABASE_URL`.
  If they differ, `SET ROLE` is denied. M3 verifies they match, or GRANTs to both.
- **Why this is worth doing now, not later:** tiers (a) and (b) close `pg_read_file` and
  `SELECT * FROM checkpoints` only through a denylist that must stay complete forever. The
  GRANT closes them structurally — a hole in the function allowlist stops being a data breach.
  Verify `SET LOCAL ROLE` to a non-superuser genuinely drops superuser privilege before
  relying on it (M0).
- `make migrate` runs each file in one transaction; `CREATE ROLE` is transactional, so this
  is safe. Supabase's `postgres` role has `CREATEROLE`, and `GRANT … TO CURRENT_USER` avoids
  naming the role, so `make migrate ENV=staging` is the whole deployed story.

### 5. The four tools

`db_list_tables()` · `db_describe_table(tables: str)` · `db_profile_column(table, column)` ·
`db_query(sql: str, purpose: str)`. Registered in `app/agent/build.py` after the curated tools.
Conventions from `app/agent/tools/db_tools.py:1-7` apply unchanged — never raise, return error
strings.

**No `check_sql` tool.** Validation is folded into `db_query` so it cannot be skipped, and a
rejection already tells the model everything a dry run would.

**`db_profile_column` is adopted from Dalgo and is not optional.** Their prompt rule #2 is
*"ALWAYS use this before filtering on a text column — the stored values often differ from what
the user said (e.g. the user says 'Maharashtra' but the column stores 'MH')."* Sangam has the
identical hazard in at least four places: `orgs.legal_form` is free text (`Society | Trust |
Section 8 | …`), `grants.status` is a four-value CHECK enum, `tags.label` is a 40-row
vocabulary, and `locations.name` is upper-case (`DIMAPUR`, not `Dimapur`). A model filtering
`WHERE legal_form = 'Trust'` against stored `'Public Charitable Trust'` gets a confident zero.
Implementation is a server-constructed `SELECT col, count(*) … GROUP BY 1 ORDER BY 2 DESC
LIMIT 20` — the model supplies only a table and column name, both validated against the catalog.

**The metadata/value split is the PII boundary.** Dalgo's `schema_tools.py:3-5`: *"These tools
return METADATA only … Actual values reach the model solely through profile_column and
execute_sql, so PII controls only have those two surfaces to cover."* Adopt that framing:
`db_list_tables` and `db_describe_table` read the catalog and never touch the database;
`db_profile_column` and `db_query` are the only two tools that return cell values, and they
are the only two that need column-exclusion enforcement.

**Watch a gap they have:** Dalgo's `profile_column` and `catalog.list_table_names` call
`ctx.warehouse.execute(sql)` **directly**, bypassing both the AST guard and the statement
timeout. Safe there because the SQL is server-constructed — but `db_profile_column` must still
go through `PsycopgExecutor` here, so it inherits the read-only transaction, the timeout and
the reader role. Don't reproduce the shortcut.

`db_describe_table` is where the brief's "relationships" requirement lands: it renders foreign
keys **in both directions** from the catalog (`grants.funder_id → funders.id`; and on
`funders`, *referenced by* `grants.funder_id`, `rfps.funder_id`, `fit_scores.funder_id`, …),
the CHECK enums verbatim, and the defect lines — at zero database round-trips.

**No live sample rows** (unlike LangChain's `sample_rows_in_table_info=3`): they cost a query
per describe and would print `contacts` PII. The static CHECK enums give the model the same
information and are guaranteed accurate.

**Error strings are the feature** — stable prefixes, sorted content, one explicit next step:

```
db_query rejected: unknown column "sector" on table "orgs".
Columns of orgs: cohort, content_hash, extractor_version, fetched_at, id, legal_form,
  name, org_kind, registered_location_id, registration_date, slug, source_name, source_url.
Sectors are tags: join org_tags → tags and read tags.label.
Next: call db_describe_table("orgs,org_tags,tags"), then retry.
```
```
db_query failed: Postgres 42703 (undefined_column).
  column o.setor does not exist
  HINT: Perhaps you meant to reference the column "o.sector".
executed: SELECT "o"."id" AS "id", "o"."setor" AS "setor" FROM "orgs" AS "o" LIMIT 51
Next: fix the column name and call db_query again.
```

`errors.py` maps SQLSTATE → guidance (`42703`, `42P01`, `42883`, `42601` with a caret window,
`42803`, `57014` timeout, `25006` — unreachable; if seen, the validator has a hole, log ERROR —
`42501` = the reader role firing). Two non-negotiables: **echo the executed SQL in every
failure** (otherwise the model diffs against text that never ran), and **never surface
`psycopg.OperationalError` text**, which can contain the DSN host and user.

### 5b. Tool return shape: `content_and_artifact`

Adopt LangChain's two-channel tool return (`@tool(response_format="content_and_artifact")`):

- **content** — the compact cited text rendering the model reads.
- **artifact** — `{"sql", "status", "row_count", "columns", "rows"}` carried on the
  `ToolMessage`, which **never enters the model's context** and is what the UI renders.

This also closes a gap already present in this repo: `EvidenceRail.tsx:42,51-67` uses `step.result` only to extract citation markers and
**renders no tool output as text anywhere**. The artifact gives the frontend a real result
table without spending context on it.

Follow Dalgo's one-interpreter rule (`messages/artifacts.py`): a single module reads artifacts,
so the live stream, any audit, and history replay can never disagree about what a turn did.

### 5c. Retry budget and context, as middleware

`create_deep_agent` accepts `middleware=[…]` (it already carries `CopilotKitMiddleware`), so
this is additive.

- **`sql_retry_limiter`** — port of `middleware.py:19-74`. `MAX_SQL_ATTEMPTS = 5`, counting
  `ToolMessage`s whose content starts with the failure prefixes, **resetting at each
  `HumanMessage`** (budget is per question, not per session). On exhaustion it appends a plain
  apology and `jump_to="end"`. Three details that matter: rejections *and* execution errors
  both count; the same number is interpolated into the prompt so the model stops gracefully
  first and the middleware is only the deterministic backstop; and it must be **first** in the
  list because it can jump. Dalgo raised this 3→5 (`7f12e1c5`) because discovery legitimately
  burns 2–3 attempts.
- **`clear_old_tool_results()`** — `ContextEditingMiddleware(edits=[ClearToolUsesEdit(
  trigger=40_000, keep=5)])`. Once `db_query` starts returning result grids, old ones are dead
  weight. Cheap insurance.
- **`trim_history`** — trims via `llm_input_messages` so the **request** shrinks while the
  checkpoint keeps the full conversation for the UI. Only needed if context pressure appears;
  note it, don't build it yet.

Costing note from their code (`chat_data_agent.py:32-38`): every middleware hook is its own
graph node, so one model⇄tool cycle costs ~12 graph steps. Sangam's `recursion_limit` is 100 —
verify it still allows ~8 tool calls after the middleware lands, and raise it if not.

### 5d. Post-answer audit (recommended, non-blocking)

A cheap second-model pass after the answer (`llm_calls/turn_audit.py`), scoring four things:
**grain** (does the SQL count the entity the question asked about?), **filters** (is every
condition in the question present?), **false zero** (could a 0 result mean a wrong filter
*value* rather than absent data?), **numbers** (do the figures in the answer match the result
table?). It emits a caveat and a Langfuse score and **never blocks the answer**.

Worth it here specifically because of the known defects: the false-zero check is exactly what
turns *"0 news mentions for KABIL"* into *"0 rows — but `news_mentions.org_id` is unpopulated,
so this is 'not linked', not 'no news'."* Their design rule — **fail-open for helpers,
fail-loud for deliverables** — applies: if the audit call fails, the turn continues unaudited.

### 6. Citations

`Column.cites` is set on primary keys **and on every FK pointing at one** — so `programs`,
`contacts`, `rfp_matches`, `documents`, `fit_score_items` and all eight join tables get cited
through their `org_id` / `funder_id` **with no frontend change**. After `qualify`, every
projection is a resolved `exp.Column`, so the output-column → kind map is exact.

**We do not auto-inject the id column** — injecting `orgs.id` breaks any `GROUP BY`/`DISTINCT`
query with a `42803` the model never wrote, which is exactly the non-convergent loop this
design exists to avoid. Instead the result header says:
`no citable id column projected — add orgs.id to the SELECT list so these rows can be cited.`

Genuinely uncitable results (`count(*)`, grouping by `tags.label`, `locations`, `rubrics`) get
one header marker `[sql:<sha8-of-executed-sql>]`, mirroring `[graph:<uuid8>]`. **Safe to ship
server-side alone:** `citations.ts:10`'s regex is a closed union, so an unknown kind stays
literal text — no broken links, no crash. Extending the frontend is an optional 3-line
follow-up (union at `:1`, regex at `:10`, a `case "sql"` at `:61` parallel to `graph`).

### 7. Agent layout (`backend/app/agent/`)

Adopt only the template entries that have content here. **Do not create** `channels/`,
`schedules/`, `connectors/`, `skills/`, `sandbox/`, `middleware/`, `memory.py`,
`pyproject.toml` — six of thirteen entries have nothing to put in them, and an empty
`middleware/` is a lie about the architecture.

```
backend/app/agent/
  build.py          ← graph.py   (not agent.py: app.agent.agent.build_agent stutters)
  instructions.md   ← prompt.py  (prompt.py stays as a 3-line loader exposing SYSTEM_PROMPT)
  models.py
  tools/            ← app/tools/
    sql/
```

- `graph.py → build.py` retires the "Two files are called `graph`" gotcha table in
  CLAUDE.md:148-155. One import to fix (`lifespan.py:18`).
- `app/tools/ → app/agent/tools/`: **3 import lines** (`graph.py:13-15`) and nothing else —
  no test, seed, script or frontend reference. Docker `COPY app/ app/` and the compose mount
  ship the whole tree. CLAUDE.md:127 already says the tools are agent-only; the directory
  placement currently contradicts it. This deepens PR #52's thesis rather than undoing it.
- `instructions.md` **must live inside the package** (loaded via `importlib.resources`). At
  `backend/instructions.md` it ships on *none* of the three paths — the Dockerfile copies only
  `pyproject.toml` and `app/`. Watch the `\` line continuations in the current prompt: a naive
  paste into markdown introduces hard newlines, silently changing the system prompt.
- **`identity.py`: skip, and here is why that matters.** Re-exporting `get_current_user` would
  make `app.api.routes.*` import from `app.agent.*` — an inverted dependency. The thing
  genuinely missing is that **checkpointer threads are not bound to users**: `thread_id` comes
  straight off `RunAgentInput` with no ownership check, so any caller can resume any thread and
  read another user's conversation, on a publicly reachable unauthenticated backend. Create
  `identity.py` when Supabase Auth lands, carrying that check. Creating it now as a shim buries
  the gap.

### 8. Evals — `backend/tests/evals/`

Not `app/agent/evals/`: `COPY app/ app/` ships everything under `app/` to a 500 MB-capped
Vercel bundle already at ~256 MB, and `tests/` already has the pytest infrastructure.

**The eval unit is question → executed gold SQL, not question → expected SQL text.** The
obvious objection to golden SQL — that SQL is not unique, so a text comparison fails on every
correct rephrasing — is real, and Dalgo's answer to it is evidence-backed: `gold_sql` is **executed** and its
*result set* compared to the agent's — never the SQL text. Their `evals/README.md:116-121`
reports that on the first judged run their text-comparing SQL judge disagreed with execution
on **8 of 11 items, and all 8 were the judge false-failing queries that provably return
identical results**. Adopt the executed form.

One JSONL item per line, file in git as the source of truth:

```json
{"question": "How many organisations are registered in Assam?",
 "gold_sql": "SELECT count(*) FROM orgs o JOIN locations d ON d.id = o.registered_location_id
              JOIN locations s ON s.id = d.parent_id WHERE s.name ILIKE 'assam'",
 "forbidden_citations": ["org:better-life-foundation", "org:pesch", "org:prda"],
 "tags": ["canary", "geography"]}
```

| Field | Scores |
|---|---|
| `gold_sql` | **gate** — executed, result multiset compared (`eval_sql_correct`) |
| `expected_value` | lighter gate — the value must appear in the answer text |
| `answer_expectations` | judge — one sentence describing a correct answer |
| `required_citations` / `forbidden_citations` | **gate** — Sangam-specific, regex over markers |
| `tags` | `--tag canary` for the cheap ~5-item loop |

Three rules carried over:

- **Gates block, judges inform.** Never let an LLM judge veto a merge. Run judges on a
  different model family than the agent so they don't share its blind spots.
- **Gold SQL cannot score absence questions.** *"How much silt in Maharashtra?"* where there
  is no Maharashtra data: a correct agent says so, which a `0` gold can't score. Use
  `answer_expectations`. This is precisely the shape of `kabil-news-declines-when-unlinked`.
- **Verify every gold by executing it before committing it.** Their first run went 8/14 → 13/14
  purely from fixing ambiguous questions and wrong golds — *"expect your first run to fail on
  item wording, not agent bugs."*

`forbidden_citations` stays, because it is the one thing their scheme lacks and the Assam
failure needs: it catches **over**-retrieval. Resolve slugs → ids in a fixture; ids are
`GENERATED ALWAYS AS IDENTITY` and differ between a fresh seed and Supabase.

Their comparator (`evals/sql_compare.py:65-137`) is worth porting rather than reinventing —
it is deliberately tolerant of *presentation* (extra context columns, a full ranking answering
a `LIMIT 1` gold, invented labels when numbers carry row identity) and strict on *substance*
(wrong numbers, wrong rows, empty results), with a regression test and a real failure behind
each rule. Also port their **judge-vs-hard-metric agreement report** (`runner.py:98-112`),
which measures how far the judge can be trusted instead of assuming.

Gating: a `--run-evals` conftest flag, **not** `addopts`. A CLI `-m` *replaces* addopts' `-m`,
so the documented `pytest -m integration` workflow would silently start billing model calls.

Seed cases — the first two fail today, and both are **data bugs, not agent bugs** (say so in
the file docstring or someone will try to fix them with prompt engineering):

| id | asserts | why it fails today |
|---|---|---|
| `assam-orgs-excludes-neighbours` | forbids `better-life-foundation` (Nagaland), `pesch`, `prda` (Manipur) | `seed/seed.py:112` parents every district to Assam; 10/10 confirmed live |
| `kabil-news-declines-when-unlinked` | `must_decline: true`, forbids `news:*` | 118/118 `org_id IS NULL`. **"I don't have news linked to KABIL" is the correct answer** per prompt rule 1; fabricating a headline is the bug. Retire this case the day the linking migration lands. |
| `refuses-unknown-org` | "Tell me about Pratham" → decline, no `[org:*]` | guards answering from world knowledge |
| `sql-readonly-refusal` | "Delete all orgs in Manipur" → `db_query` returns an error string, never raises | |
| `sql-aggregate` | "How many organisations per district?" → matches a golden query | |

**Langfuse is the sink, not the runner.** pytest gates merges and the citation assertions are
regex over strings — an LLM judge would be slower, nondeterministic, billed and less accurate.
But Langfuse **Datasets** give the "promote this production trace into the eval set" loop,
which is exactly how both failures above were found, and dataset runs give history across
`MODEL` values. Set `LANGFUSE_TRACING_ENVIRONMENT=eval`. Verify the v3 dataset-run API names
against the installed `langfuse>=3,<4` — the shape changed from v2.

---

## Risks

- **Tool-selection regression.** Adding four tools to a six-tool agent will pull traffic from
  `get_grants` toward `db_query`, losing the tuned trigram search, provenance formatting, and
  the "absence here is not proof no grant exists" caveat (`db_tools.py:205-206`). Mitigate in
  `instructions.md` and the first line of the `db_query` docstring; watch it in Langfuse. If it
  regresses, describe `db_query` as an escalation path rather than a peer.
- **Unbounded retry.** Only `recursion_limit: 100` bounds it today, so a stuck model can burn
  ~40 turns on one malformed query. The `sql_retry_limiter` middleware (§5c) is what bounds it.
- **Pool contention.** See the `Semaphore(2)` note above.
- **The larger exposure is the unauthenticated backend, not a sqlglot bypass.** This feature
  should ship on the same milestone as auth, not ahead of it.
- **Result rows in traces.** Sangam's `traced_fetch` records only `{"row_count": n}` today, so
  nothing leaks. Keep it that way: if `db_query` ever attaches rows to its span, add Dalgo's
  `LANGFUSE_MASK_TOOL_RESULTS` switch (`tracing.py:112-116`) — SQL text always traced, rows
  replaced by a length stub. Their own doc is blunt that traces carrying query results are
  *"only acceptable against a self-hosted Langfuse inside the deployment."*
- **Session-scoped `SET` leaking onto a pooled connection.** Dalgo has a live instance of this
  (`sql_tools.py:84-89`): `SET statement_timeout` without `LOCAL`, outside a transaction, on a
  SQLAlchemy pool — it survives the rollback on return and applies to the next borrower. Our
  `SET LOCAL` inside an explicit transaction is what avoids it, and
  `test_nothing_leaks_onto_the_pooled_connection` is the test that keeps it avoided. Worth
  flagging to whoever owns that file.
- **Interrupts and cancellations must not read as errors in traces**
  (Dalgo `tracing.py:230-247`) — otherwise error-rate dashboards are fiction. Sangam has no
  HITL pause, but a client disconnect mid-stream is the same shape.

---

## Milestones

Branch off `origin/master` (`c62e8ce`). The Langfuse tracing work is already merged as PR #53 —
the local `feat/langfuse-detailed-tracing` branch is fully contained in `origin/master`.

**One milestone, one PR.** The ordering has a property worth protecting: the entire safety
layer is written, tested and merged **before the agent can reach the database at all**. The
tools are not registered until M4. Up to that point every merge is inert to the running product.

| | Milestone | Ships | Agent can query? |
|---|---|---|---|
| **M0** | Spike | nothing — findings only | no |
| **M1** | Agent layout | pure renames | no |
| **M2** | The guard | validator + catalog, unwired | no |
| **M3** | Execution safety | executor + reader role, unwired | no |
| **M4** | Tools, live | four tools + middleware + UI | **yes** |
| **M5** | Evals | measurement | yes |
| **M6** | Audit & polish | caveats + citation chips | yes |

---

### M0 — Spike ✅ done

Ran against sqlglot **27.29.0** (3.9 MB installed) and the live local Postgres. Four findings
changed the design; all are folded into the sections above.

| # | Checked | Outcome |
|---|---|---|
| 1 | Node classes, root typing, arg slots | 13/14 as designed |
| 2 | `FETCH FIRST` | **Correction** — occupies `args["limit"]` as `exp.Fetch`, not `args["fetch"]`. Clamp it, don't reject it (§2). |
| 3 | Forbidden-node names | **Correction** — `COPY`→`exp.Copy`, `TRUNCATE`→`exp.TruncateTable`, `GRANT`→`exp.Grant`, and `LISTEN`→`exp.Alias` (caught by the root-type check, not the node scan). |
| 4 | Round-trip of the 8 real `db_tools.py` queries | **8/8 stable — fallback not needed.** But the test must assert *idempotence of generated SQL*, not `repr` equality: sqlglot upper-cases function names, so a repr test false-fails on every `similarity()` call (§2). |
| 5 | `qualify()` kwargs, star expansion, `build_scope()` | as designed; unknown column raises `OptimizeError: Column '"sector"' could not be resolved` |
| 6 | `Query.limit()` on a `UNION` root | applies at top level ✓ |
| 7 | `SET LOCAL ROLE` drops superuser | ✓ `rolsuper` `t`→`f`; checkpoints, `pg_read_file`, INSERT and ungranted columns all denied (§4) |
| 8 | `RESET ROLE` | **escapes to superuser** — the role bounds single statements only (§4) |
| 9 | `prepare=True` vs multi-statement | **load-bearing**: simple protocol runs `SELECT 1; RESET ROLE`; extended protocol blocks it server-side (§3) |

Also confirmed `count(*)` is aliased `_col_0` by `qualify` — the renderer should use the model's
own alias where one is given, since `_col_0` is meaningless in an answer.

---

### M1 — Agent layout

Pure moves. No behaviour change, so it reviews as renames — the same reason PR #52 was split
this way.

- `git mv app/agent/graph.py app/agent/build.py`; fix the one importer (`lifespan.py:18`).
- `git mv app/tools app/agent/tools`; fix three imports in `build.py`. Nothing else in the
  repo imports `app.tools` — no test, seed, script or frontend reference.
- `prompt.py` → `agent/instructions.md` + a 3-line loader that keeps `SYSTEM_PROMPT`
  importable. Decide the `\`-continuation whitespace question explicitly; it changes the
  system prompt.
- **CLAUDE.md edits in the same commit** — layout tree, the "Two files are called `graph`"
  table (now obsolete), the `app/tools/` paths, the "Adding a tool" recipe. Plus the stale
  `db/migrations/README.md:3` path.

**Why first:** `git mv app/tools app/agent/tools` into a directory that already exists would
nest as `app/agent/tools/tools/`. Do the move before any new file lands there.

**Exit:** `pytest -m "not integration" && ruff check . && make up && make smoke` — all green,
and `git show --stat` shows renames, not rewrites.

---

### M2 — The guard

The whole safety argument, as pure functions. No pool, no async, no agent. ~45 adversarial
tests cost zero seconds and no container.

- `catalog.py` — the 28-table allowlist as frozen dataclasses, the import-time self-check,
  and `verify_against_db()`.
- `validator.py` — every pass in §2, returning `ValidatedQuery`.
- `errors.py`, `render.py` — the model-facing error strings and the row rendering.
- `test_sql_validator.py` written **alongside**, not after: the ~45 rejections, the acceptance
  table, and the `db_tools.py` round-trip corpus. Each rejection asserts on the *message*,
  because the message is the feature.

**Exit:** `pytest tests/test_sql_{validator,errors,render}.py -q && ruff check .`, and
`python -c "from app.agent.tools.sql.catalog import CATALOG; print(len(CATALOG))"` → 28.

---

### M3 — Execution safety

The server-side boundary, complete and proven, still unreachable by the agent.

- `executor.py` — the `Executor` Protocol and `PsycopgExecutor`: read-only transaction,
  `SET LOCAL statement_timeout`, `SET LOCAL ROLE`, the `Semaphore(2)`, routed through
  `traced_fetch`.
- `db/migrations/0001_sql_reader_role.sql` — the repo's first migration. Column-level GRANT on
  `contacts` and `chunks`. **Verify the migration user and the runtime user are the same role**
  before merging; on Supabase they may not be.
- `Settings.sql_timeout_ms / sql_max_rows / sql_reader_role / sql_max_attempts`.
- `test_sql_integration.py` — the tests that prove the tiers are independent, especially
  `test_nothing_leaks_onto_the_pooled_connection` (this pool also serves the checkpointer) and
  `test_reader_role_cannot_read_checkpoints`.

**Exit:** `make migrate && make migrate-status`, then `make up && pytest -m integration -q`.
`test_read_only_transaction_blocks_write` and `test_reader_role_cannot_read_checkpoints` must
both pass — those two are the milestone.

---

### M4 — Tools, live

The first milestone that changes what a user sees.

- The four tools in `sql_tools.py` with `content_and_artifact`: `db_list_tables`,
  `db_describe_table`, `db_profile_column`, `db_query`.
- `sql_retry_limiter` (**first** in the middleware list — it can jump) and
  `clear_old_tool_results()`.
- Registration in `build.py`; catalog + `pg_roles` verification in `lifespan.py`.
- `instructions.md`: when to prefer SQL over the curated tools, the profile-before-filter rule,
  the `MAX_SQL_ATTEMPTS` number, and what `[sql:…]` means.
- Frontend: `toolLabels.ts` entries, and artifact rendering in `EvidenceRail` — which is new
  capability, since `step.result` is currently rendered nowhere.

**Exit:** `make up && make smoke`, then ask the chat *"how many grants does each funder have?"*
and confirm a result table plus `[funder:N]` chips in the Evidence Rail. Then ask
*"which organisations work in Assam?"* — it should surface the `locations` defect caveat rather
than confidently listing Manipur orgs.

---

### M5 — Evals

Before tuning anything. Dalgo's harness landed *first* (`7439b82b`) and every later change was
measured against it; they also had to loosen the comparator twice (`f9316b0b`, `145f9340`)
before it was right, which is an argument for building it while the agent is still simple.

- `tests/evals/` — harness, the `sql_compare.py` port, the `--run-evals` conftest flag
  (**not** `addopts`), the `eval` marker, `make evals`.
- ~12 golden items as JSONL in git. Execute and verify every `gold_sql` before committing it.
- Langfuse dataset seeding, keyed by question hash so re-seeding upserts.

**Exit:** `pytest tests/evals --run-evals --tag canary`. The two known-failing cases
(`assam-orgs-excludes-neighbours`, `kabil-news-declines-when-unlinked`) must fail *for the
documented reason* — they are data bugs, and this is the harness that will prove when the
schema migrations fix them.

---

### M6 — Audit & polish

- Post-answer audit (§5d) and its Langfuse score. Fail-open.
- Frontend `[sql:]` citation kind — 3 lines in `citations.ts`.
- `trim_history` if context pressure has actually appeared by now; skip it if not.

**Exit:** the final gate below.

---

**Final gate (every milestone M1+):**
`cd backend && pytest -m "not integration" && ruff check . && cd ../frontend && npm run build && cd .. && make smoke`

---

## Verification

Adversarial cases the validator must reject (each asserts on the *message*, not just that it
raised — the message is the feature). Abbreviated; ~45 in full:

| SQL | Rejected because |
|---|---|
| `SELECT 1; DROP TABLE orgs` | 2 statements — psycopg3 with `params=None` uses the simple protocol, which **permits** multi-statement |
| `SELECT 1 -- ; DROP TABLE orgs` | comment stripped on regeneration |
| `WITH x AS (DELETE FROM orgs RETURNING *) SELECT * FROM x` | root *is* a Query; caught by the write-node scan |
| `SELECT * INTO copy_of_orgs FROM orgs` | CTAS disguised as a Select |
| `COPY orgs TO '/tmp/x'` / `VACUUM` / `EXPLAIN ANALYZE DELETE …` | `exp.Command`, not a parse error |
| `SELECT id FROM orgs FOR UPDATE` | locking clause |
| `SELECT pg_read_file('/etc/passwd')` | **succeeds today as superuser** — function allowlist |
| `SELECT * FROM dblink(…)` / `generate_series(1,1e9)` | non-Identifier table |
| `SELECT * FROM checkpoints` / `checkpoint_writes` | not in catalog |
| `SELECT * FROM information_schema.tables` | cross-schema |
| `WITH orgs AS (SELECT 1 AS id) SELECT id FROM orgs` | CTE shadows a real table |
| `SELECT * FROM orgs UNION ALL SELECT * FROM checkpoints` | recursive table scan, root is `exp.Union` |
| `SELECT email FROM contacts` | column not in catalog |
| `WITH RECURSIVE t AS (…) SELECT * FROM t` | outer LIMIT cannot stop a materialised recursive CTE |
| `"(" * 5000 + "SELECT 1" + ")" * 5000` | length guard; no `RecursionError` escape |

Integration tests that prove the tiers are independent (`@pytest.mark.integration`, reusing the
skip-if-no-DB fixture at `tests/test_migration_integrity.py:17-23`):

- `test_catalog_matches_information_schema` — the gate that fails loudly when a migration drops a table
- `test_read_only_transaction_blocks_write` — bypass the validator, run a raw `INSERT` inside the executor's transaction → `ReadOnlySqlTransaction`
- `test_statement_timeout_fires` — slow cartesian join → `QueryCanceled` (57014)
- `test_nothing_leaks_onto_the_pooled_connection` — query, then write on a connection from the same pool → must succeed (**this pool also serves the checkpointer**)
- `test_reader_role_cannot_read_checkpoints` — under `SET LOCAL ROLE`, `SELECT * FROM checkpoints` → `InsufficientPrivilege`
- `test_percent_literal_survives_params_none` — `ILIKE '%kabil%'` returns rows
- `test_grants_match_allowlist` — the migration's GRANT list ≡ the catalog

End-to-end: `make up && make seed && make smoke`, then ask the chat *"how many grants does each
funder have?"* and *"which organisations work in Assam?"* — the second should surface the
`locations` defect caveat rather than confidently listing Manipur orgs.

---

## Out of scope

- The schema migrations from the earlier review (`0001_location_provenance` … `0004_drop_dead_joins`)
  — this plan *records* those defects in the catalog rather than fixing them. Renumber
  `0001_sql_reader_role.sql` if that work lands first; `migrate.py` orders by filename and
  freezes each file's checksum once applied.
- Supabase Auth / thread-ownership checks — named above as the reason `identity.py` is deferred.
- `db/migrations/README.md:3` still points at `backend/app/migrate.py` (moved to
  `app/db/migrate.py` in PR #52). One-line fix; fold into M1's CLAUDE.md commit.
