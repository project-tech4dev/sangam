# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

First run, from a clean checkout (needs Docker, an `ANTHROPIC_API_KEY`, and a Supabase
project — see README.md, "Prerequisites"):

```bash
cp .env.example .env     # ANTHROPIC_API_KEY, and the two NEXT_PUBLIC_SUPABASE_* values
make up                  # build and start everything
make seed                # migrate, then load the cohort data — the app is empty without it
make smoke               # confirm the stack is wired end to end
```

**Migrations are not automatic, and two things depend on them.** `db/init/` is a baseline only:
7 of the SQL catalog's 32 tables arrive in `db/migrations/`, and `_verify_sql_catalog` raises
at boot when one is missing, so the backend will not start against an unmigrated database.
`seed.taxonomy_seed` needs `0002_taxonomy.sql` as well.

Locally, `make up` therefore starts Postgres, runs `migrate`, and only then starts the backend,
and `make seed` runs `migrate` too. Both are pinned to `ENV=local`: against a managed database
you run `make migrate ENV=staging` yourself, deliberately and after a backup.

Then http://localhost:3000 for the app and http://localhost:8010/docs for the API. The Ask
workspace and Import (`/import`, with its own list of past imports; `/ask?view=import`
redirects there) are behind Supabase sign-in; signed out, `/ask` is a public preview. `OPENAI_API_KEY` and `make graph-seed` are optional —
the graph disables itself cleanly. One smoke check, `documents: 96+`, is expected to fail on a
fresh clone: `make seed` does not create those documents.

Everyday targets (`make help` lists all of them):

```bash
make up                  # start the whole stack (Postgres, Neo4j, backend, frontend)
make down / make logs
make frontend-reinstall  # force a frontend npm ci; `make up` installs only on a dep change
make seed                # load cohort data into Postgres
make graph-seed          # build the Neo4j graph from Postgres (needs OPENAI_API_KEY)
make smoke               # end-to-end check of backend + frontend + chat wire
                         # SMOKE_SKIP_LLM=1 make smoke  → skips the one real agent call
make migrate             # apply db/migrations/*.sql   (make migrate-status to inspect)
make psql                # interactive shell against whichever DB ENV selects
```

Running a piece outside Docker:

```bash
make dev-backend         # uvicorn --reload against localhost:5433
make dev-frontend        # next dev with AGENT_URL pointed at localhost:8000
```

Ports: frontend `3000`, backend `8010` (published from the container's `8000`), Postgres
`5433` (from `5432`), Neo4j `7474`/`7687`. Outside Docker, `make dev-backend` serves uvicorn
on `8000` directly — which is why `dev-frontend` points there while `make smoke` defaults to
`8010`.

Tests and lint (backend):

```bash
cd backend
pytest                              # all tests
pytest tests/test_orgs.py           # one file
pytest -k "score"                   # one pattern
pytest -m "not integration"         # skip tests needing the compose Postgres on :5433
ruff check .                        # line-length 110, target py312
```

```bash
make evals                          # golden questions through the real agent (COSTS MONEY)
make evals TAG=canary               # the cheap subset
```

`asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio`. **Unit tests never
touch a database**: `client_for(*routers)` builds a router-only FastAPI app with no lifespan
(no pool, no agent, no model) and overrides two dependencies — `get_current_user`, and
`get_pool` with a `_SentinelPool` that raises on any attribute access. Routers take the pool
as `PoolDep`, so that one override covers every router; monkeypatch the `repositories/`
function rather than the pool. `tests/test_migration_integrity.py` and
`tests/test_sql_integration.py` carry the `integration` mark.

`tests/evals/` is a third tier: golden questions run through the **real agent**, so they cost
money. They carry the `eval` mark and are skipped unless `--run-evals` is passed. That is a
conftest flag rather than an `addopts` filter on purpose — a command-line `-m` *replaces*
addopts' `-m`, so `pytest -m integration` would otherwise start billing model calls. `make
evals` runs them on the host venv, because the image installs runtime dependencies only and
has no pytest. A case with `expected_failure` is `xfail(strict=True)`: when the underlying
data bug is fixed the case passes, pytest reports XPASS as a failure, and the marker gets
deleted.

Running the migration runner outside Docker needs `MIGRATIONS_DIR` — it defaults to the
container path `/srv/db/migrations`.

Frontend: `npm run lint` (ESLint, flat config in `frontend/eslint.config.mjs`) and
`npm run build`. Run the build before pushing — type errors surface there and never in
`next dev`.

## Environment selection

`ENV` picks the database for every DB-touching target: `ENV=local` (default) uses the
bundled Postgres container, `ENV=staging` uses the `STAGING_DB_*` block in `.env` via
`docker-compose.staging.yml`. Compose resolves the connection string so there is one
source of truth; `scripts/db-url.sh` surfaces its error when a staging variable is missing.

`ENV=staging` deploys nothing. It points local tooling at the managed database —
and, with `make up ENV=staging`, the local stack itself. The containers stay yours;
only the data is shared. Think before using that one: a research run from your
machine then writes straight into the database the deployed app serves.

**Supabase Storage is global, so the two halves of a document can disagree.**
`SUPABASE_URL`/`SUPABASE_SERVICE_KEY` are not environment-scoped: with the backend
on the local Postgres, `fetch_document` still archives the file to the cloud bucket,
so the `documents` row is local and the object it names is not. Running
`ENV=staging` puts both in the same place.

**`STAGING_DB_*` are local-tooling variables only.** The backend itself reads
`DATABASE_URL` (`backend/app/core/config.py`). Setting `STAGING_DB_*` on a deployed host does
nothing.

## Architecture

```
browser ── Next.js ── /api/copilotkit (CopilotKit v2 runtime)
              │             │ AG-UI (SSE)
              │ REST        ▼
              └────── FastAPI ── LangGraph deep agent
                          │          tools: db_list_tables · db_describe_table
                          │                 db_profile_column · db_query
                          │                 search_graph · fetch_url
                          ▼
              Postgres + pgvector        Neo4j (optional)
```

### Layout

```
backend/app/
  main.py          create_app() + `app = create_app()` — the ASGI entrypoint, wiring only
  core/            config.py (Settings) · security.py (auth stub) · lifespan.py · logging.py · egress.py
  db/              pool.py (PoolDep) · checkpointer.py (LangGraph) · migrate.py (runner)
  api/             router.py (the one aggregate router) · deps.py · routes/<resource>.py
  repositories/    hand-written SQL, one module per resource
  schemas/         Pydantic, one module per resource
  agent/           build.py (builds the deep agent) · models.py · tools/
                   instructions.md (the system prompt) · prompt.py (loads it)
  ingest/          agent.py (builds Sangam Import) · instructions.md · skills/
                   tools/ every tool it has, and nothing else in ingest/ is one
                   the rest is the pipeline: runner · writer · promote · matcher
  integrations/    graphiti.py (Neo4j client lifecycle)

frontend/
  app/             routes ONLY — pages, layouts, route handlers
  features/        one folder per screen: ask/ auth/ home/ ingest/ registry/ terms/
  components/      ui/ (display primitives) · layout/ (site chrome)
  lib/             api/ (client + types) · supabase/ · format.ts
```

Two rules keep this from eroding: **nothing that is not a route goes under
`frontend/app/`** (a `_private` folder is the smell that something belongs in
`features/`), and **no new module goes flat at the top of `backend/app/`** — it belongs in
one of the groups above. Cross-folder frontend imports use the `@/` alias, not `../../..`.

Things worth knowing before changing anything:

**Postgres is the system of record.** The Neo4j graph stores relationship facts *extracted*
from source text and is rebuildable from Postgres (`seed/graph_seed.py`). Keep that
property — nothing should live only in the graph.

**The agent reaches the database through tools, not the API.** `backend/app/agent/tools/sql_tools.py`
runs model-written SELECTs against it directly. `backend/app/api/routes/` serves the frontend's REST calls. They
share `repositories/` but are separate paths; changing one does not change the other.

**The frontend talks to the backend two ways.** Server components use
`frontend/lib/api/client.ts` (reads `AGENT_URL`, strips the `/agent` suffix to derive the REST
base). The chat UI posts to `/api/copilotkit/[[...slug]]/route.ts`, which proxies to the
backend's `/agent` over AG-UI. `AGENT_URL` therefore ends in `/agent` while
`NEXT_PUBLIC_API_URL` does not — the asymmetry is deliberate.

**REST resources come in a three-file set**: `app/api/routes/<r>.py` (router) →
`app/repositories/<r>.py` (hand-written SQL over raw psycopg) → `app/schemas/<r>.py`
(Pydantic). There is no ORM, which is also why there is no Alembic — `app/db/migrate.py`
explains the reasoning. Adding a resource means all three, plus one line in
`app/api/router.py`. Nothing else: `main.py` includes that one aggregate router, and the
tests' pool override is dependency-based, so neither needs editing.

Routers take the pool as `pool: PoolDep` (from `app/db/pool.py`) rather than calling
`get_pool()` in the body — that is what makes it overridable per-app. Agent tools, which run
outside any request, still call `get_pool()` directly.

**Only one file is called `graph`**: `app/agent/tools/graph_tools.py`, the `search_graph` agent
tool. The deep agent is built in `app/agent/build.py`, and the Graphiti/Neo4j client lifecycle
(`open_graph`, `graph_status`, `client`) lives in `app/integrations/graphiti.py`. Both used to
be called `graph.py` too, which made tracebacks ambiguous.

**`deepagents` is LangGraph, not an alternative to it.** `create_deep_agent()` is a preset
middleware stack over `langchain.agents.create_agent` and returns a compiled LangGraph
graph — which is exactly what `AsyncPostgresSaver` checkpointing and
`add_langgraph_fastapi_endpoint` require. Dropping `deepagents` would not drop LangGraph.

**The agent has exactly six tools, and there is ONE path to the database.**
`app/agent/build.py` registers `db_list_tables`, `db_describe_table`, `db_profile_column`,
`db_query`, `search_graph`, `fetch_url`. Nothing else.

That sentence was false for a while and `app/agent/harness.py` is what makes it true again.
`create_deep_agent` adds eight filesystem tools of its own — including `write_file`, `delete`
and `execute` — and, whenever any subagent is declared, a `general-purpose` subagent carrying
**the main agent's entire tool list** under deepagents' generic prompt. Ask Sangam was running
fifteen tools; Sangam Import twenty-one, with a subagent that could call `run_import_now` and
`promote_research` under none of its instructions. `app/agent/harness.py` removes both, by
two different mechanisms, and the difference matters: a `HarnessProfile` is registered per
**provider**, so it is global to every agent sharing a model — right for the subagent, wrong for
tools, since Sangam Import needs `read_file` to load a skill and Ask Sangam must not. So
`install()` disables the subagent globally, and `filesystem(backend, keep=...)` replaces the
preset's `FilesystemMiddleware` **per agent**. Ask Sangam ends at its six plus `read_file`,
which `FilesystemMiddleware` refuses to be built without; Sangam Import adds `ls`. Nothing that
writes survives on either.

**A subagent inherits none of that and must say so itself.** `create_deep_agent` builds an
isolated subagent's middleware from scratch with an *unrestricted* `FilesystemMiddleware`, and
folds the parent's in only for `mode="fork"`. So `entity-researcher` and `catalog-writer` each
carry their own `middleware=[filesystem(backend, keep=...)]` in `app/ingest/agent.py` — without
it they run all eight tools, and `write_file`/`edit_file`/`delete` reach real disk through the
`/skills/` route. A test that reads only `build(...).nodes["tools"]` cannot see this: it is the
parent's tool node. `TestASubagentRunsOnlyTheToolsItsSpecDeclares` walks the compiled subagent
graphs instead.

Tests pin all of it, because the next library upgrade is free to add more.

There used to be four hand-written tools wrapping fixed queries (`search_orgs`, `get_funder`,
`get_grants`, `get_fit_scores`). They were removed, and it is worth knowing why before
proposing another: they were a cached query plan rather than a capability, and a worse one.
Asked which organisations work in Assam, `search_orgs` read only `orgs.registered_location_id`
and returned all ten; the model writing its own SQL found `org_locations`, cross-checked both
relationships and answered seven. Two paths to the same rows also meant two places to keep
correct — a data caveat added to the catalog reached `db_query` and not `search_orgs`. The cost
is latency: a curated lookup was one tool call, the same question in SQL is three to five.

`app/agent/tools/mcp.py` (GitHub and Playwright MCP servers) and `web.make_web_search` (Tavily)
are complete but imported nowhere, and the `Settings` fields that feed them — `tavily_api_key`,
`github_pat`, `github_mcp_url`, `playwright_mcp_url`, `mcp_servers` — therefore do nothing until
those tools are registered. Setting them changes no behaviour.

**The SQL tools let the model write its own SELECT, behind four layers.** Full design in
`docs/SQL_AGENT.md`; the parts you need before touching them:

- `app/agent/tools/sql/catalog.py` is the **allowlist, as data** — 32 tables, and a column not
  listed there does not exist as far as the tool is concerned. It also carries `defects`:
  evidence-backed caveats about the *data* that get injected into every result touching the
  table, so the model cannot report "0 rows" as "none exist". Delete a defect line when a
  migration fixes the underlying data. `verify_against_db()` runs at boot and **raises** on
  drift — deliberately not the degrade-quietly rule, because a catalog that disagrees with the
  schema produces confidently wrong answers.
- `validator.py` is pure: no pool, no async, no settings. **The model's SQL string never
  executes** — what runs is the regenerated sqlglot AST, which is what actually kills
  multi-statement injection and comment smuggling.
- `executor.py` wraps every query in a read-only transaction with `SET LOCAL statement_timeout`,
  and passes `prepare=True` so the *server* refuses multi-command statements. All
  transaction-scoped, because this pool is shared with the LangGraph checkpointer, which writes.
  **The app connects as the database owner, which is a superuser**, so the catalog is what keeps
  the checkpoint tables and `pg_read_file` out of reach — there is no second line of defence. A
  SELECT-only role was built and dropped as too much deploy surface for a first cut; see
  `docs/SQL_AGENT.md`.

`SQL_AUDIT_MODEL` turns on a post-answer audit (`app/agent/audit.py`): a cheap second model
checks grain, missing filters, false zeros and whether the figures in the prose match the rows,
then appends a caveat. It never blocks and never edits — by the time it runs the answer has
already streamed. Off by default because it is a real extra model call per SQL turn.

Adding a table to the catalog is a **security decision**, not bookkeeping: a new table is
invisible to the agent until someone puts it there, and boot logs any live table that is
neither catalogued nor in `KNOWN_EXCLUDED`.

## Conventions

**Schema changes go in `db/migrations/*.sql`, never in `db/init/02_schema.sql`.** The
baseline is what a brand-new database gets; migrations carry everything after it. See
`db/migrations/README.md`. `0001_`–`0010_` carry the v3 data model on top of the v2 baseline:
provenance columns, the taxonomy, geography, identity, credentials, funder activity, org facts,
proposals and signals. They are purely additive — 23 tables gain columns, 14 are new, nothing is
dropped — so a fresh database is `db/init/02_schema.sql` plus `make migrate`. `0011_`–`0029_`
continue on top, and `0030_tag_links` adds the theme taxonomy's join table, and `0031_funder_consolidation` is the first
that drops tables: nine funder tables became five, and `0032_staff_sources_bucket` adds the private bucket. `0033_cso_consolidation` puts an evidence tier (`source_type`, `evidence`) on the seven CSO tables, gives `org_identifiers` a status so an application needs no number, and drops `credential_events` and `program_locations`. `0034_grants_into_funder_activity` retires `grants` and `grant_locations`: a grant is a `funder_activity` partner line, cited `[activity:N]` and served at `/api/partner-lines`. `0035_research_coverage` adds `gaps` and `years` to `entity_research` for the coverage report. `0038_research_saved` adds `saved` and `saved_at`, what each Import save wrote, for the Done step's before and after. There are 36 in total. The design and the
before/after are in `docs/DATA_PLATFORM.md`.

**Every fetch of a model-supplied URL goes through `guarded_client` (`app/core/egress.py`)**, which refuses
private, loopback and metadata addresses on every redirect hop.

**Agent tools never raise, and every row they return is cited.** Two conventions that the
product depends on and that a new tool silently breaks:

- *Errors are return values.* A raised exception aborts the entire agent run; a returned
  error string lets the model see the failure and adapt. Every tool body in `app/agent/tools/` is
  wrapped in `try/except` returning `f"<tool> failed: {exc}"`.
- *Every database and graph row carries a citation marker* — `[org:N]`, `[funder:N]`,
  `[activity:N]`, `[score:N]`, `[graph:<uuid8>]` — because `app/agent/instructions.md` requires the
  model to repeat it inline next to each fact. A tool that returns uncited rows produces
  uncitable answers. (`fetch_url` is the exception: live web text carries no marker.)

Adding a tool: write the async function in `app/agent/tools/` with both conventions, register it
in `app/agent/build.py`, describe it in `app/agent/instructions.md` (a test asserts every
registered tool is named there), and add a label to
`frontend/features/ask/lib/toolLabels.ts` (unlabelled tools fall back to a humanised name).
For Sangam Import the four places are the same shape but different files:
`app/ingest/tools/<module>.py`, a tool list in `app/ingest/agent.py`,
the prompt that owns that list, and `frontend/features/ingest/lib/toolLabels.ts`.
**Which list, and therefore which prompt, is the decision.** The supervisor's `TOOLS` is
named in `instructions.md`; a subagent's `tools` is named in its `prompts/<name>.md`, and
instructions.md naming it does nothing — an isolated subagent never sees that file. A
parametrised test holds each spec against its own prompt.
There used to be a `HIDDEN_TOOLS` set there suppressing the `deepagents` filesystem built-ins
from the trace; the tools themselves are gone now, so hiding them is not needed.

**Design changes start in the design system, and the design system never drifts from the
repo.** The Claude Design project "Sangam Design System v2" is the system of record for colours,
type, corners, spacing and component looks. Do not add a token, size or colour to `globals.css`
that the design system lacks — reuse one, or change the design system first. And **any PR that
changes a component in `frontend/components/`, the classes or tokens in `globals.css`, or a
screen the UI kit recreates (Home, Registry, profiles, Ask, Import) updates the design system in
the same PR** — its components, their `.d.ts`/`.prompt.md`, and the matching
`ui_kits/sangam-web/` page. `docs/DESIGN_SYSTEM.md` has the link, the file-by-file mapping and
the step-by-step sync; `.design-sync/NOTES.md` has what a sync agent needs to know (the
`/design-sync` converter does not fit this repo — sync by hand).

**Styles go in classes, not `style={{…}}`.** A look belongs in a named class in `globals.css`
(or a Tailwind utility), built from the design system's tokens, and mirrored in its
`tokens/base.css`. Inline styles can't carry hover, focus or media queries, can't be reused,
and can't be kept in step with the design system. An inline style needs a real reason: a value
computed at runtime (a progress width, a measured height, a per-row colour from data). Some
300 older ones remain; a PR that touches a component moves that component's styles to classes,
as `features/ask/components/Sidebar.tsx` and the `.rail-*` classes did.

**Icons come from Lucide (`lucide-react`); never draw an SVG by hand.** Size, stroke and colour
are set by the `.icon` classes in `globals.css`, never as props: one stroke weight everywhere,
and the colour follows the surrounding text. Text-like marks stay as glyphs (⟨ ⟩ ✓ → ⌘↵), as
the design system's iconography page says.

**Provenance columns on every scraped or extracted table**: `source_url`, `source_name`,
`fetched_at`, `content_hash`, `extractor_version`. Populate them — the product promise is
that every field traces to a source.

**A tool of either agent lives under a `tools/` package, and nothing else does.**
`app/agent/tools/` for Ask Sangam, `app/ingest/tools/` for Sangam Import — three modules
there, split by what the tool touches: `pipeline_tools.py` (the adapter path),
`catalog_tools.py` (what Sangam already holds), `research_tools.py` (the open web).
Both agents register their list in one place — `build.py` and `agent.py` respectively — and
a test walks the package to prove every tool defined is also registered.

**Sangam Import has two human-in-the-loop steps: `list_bucket_files` (staff choose the bucket)
and `select_source_files` (staff choose the files).** Both are in `INTERRUPT_ON` in
`app/ingest/agent.py`, which `create_deep_agent(interrupt_on=…)` turns into LangChain's
`HumanInTheLoopMiddleware`; the Import screen answers with CopilotKit's `useInterrupt`
(`SpreadsheetsCard`, one card for both pauses) and resumes with `{decisions: [...]}`. Any bucket's `.xlsx` can be
picked, in any folder or none. A picked file becomes a
`documents` row, so no script is needed; `make staff-source` still writes the same row. The
supervisor never reads rows: when a request is about everyone in a file, the `workbook-reader`
subagent (one tool, `read_workbook`) returns the names, and a researcher per name follows.

**How many organisations Import researches at once is a setting, not a number in the
prompt.** `MAX_PARALLEL_RESEARCH` (default 8) bounds one *wave*, never the size of the list:
above it the agent researches in waves until every organisation asked for is done.
`app/ingest/instructions.md` carries a `{{MAX_PARALLEL_RESEARCH}}` placeholder — **the only
substitution any prompt in this repo gets** — because a number frozen in prose made the
setting decorative. It is a plain `.replace()`, not `.format()`: the file is full of literal
braces. The fan-out is bounded by connections, so `DB_POOL_MAX_SIZE` (default 10) moves with
it; the pool is shared with the checkpointer, which writes on every graph step, so the
concurrency gates in `sql/executor.py` and `ingest/runner.py` derive from it and sit under
it. The ceiling is the database's: Supabase allows 60 connections, 3 reserved, across every
deployed instance.

**Sangam Import loads its procedures from skills.** `app/ingest/skills/<name>/SKILL.md` holds a
reusable procedure, advertised by its frontmatter and read only when the model judges it
relevant. There are seven, in three groups: **what to pull** (`funder-intake-research`,
`ngo-credential-research` — cited fields in a set source order; `funder-intake-research` also
pulls the open call itself, and `ngo-credential-research` lists the documents to request from a
CSO), **what to produce** (`entity-record` for one organisation, `funder-scan-for-fundraisers`
and `ngo-brief-for-funders` for a comparison across several), and **what the catalog did
with it** (`catalog-mapping` before a write, `catalog-write-report` after). The two outer
groups split by entity kind because the kinds genuinely differ; the record, the mapping and the report do not. **They are the supervisor's, and no subagent declares one**: a
researcher's targets come from `research_goals` and the schema, and it returns a
`ResearchSummary` with no prose to shape. Constraints never live there: progressive disclosure
means the model chooses whether to load, and the money-unit rule, the entity-confirmation step and
the access rules cannot be optional. `docs/SKILLS.md` has the mechanism, the discovery rules and
the honest cost.

**Optional subsystems degrade, they do not crash.** The graph activates only when
`NEO4J_URI` and an OpenAI key are both set (`Settings.graph_enabled`); `graphiti_core` is
imported lazily inside `open_graph()` so the app boots without it, and `search_graph`
returns a message telling the agent to use the database tools instead. Langfuse follows
the same pattern. Preserve this when adding integrations.

**Tracing config lives in `app/integrations/tracing.py`**, and two of its settings are
load-bearing in ways the Langfuse docs do not advertise:

- `CallbackHandler(update_trace=True)` is what puts a name, the question, and the answer
  on the *trace*. Built bare, every trace is called `LangGraph` with empty input/output and
  you have to open a nested span to see anything.
- The handler groups turns by `metadata.langfuse_session_id` and **ignores LangGraph's
  `thread_id` entirely**. `SessionScopedAGUIAgent` overrides `prepare_stream` — the one hook
  that sees both the per-request `RunAgentInput` and the graph's config — to map one onto
  the other. Without it a six-turn conversation is six unrelated traces.

`LANGFUSE_TRACING_ENVIRONMENT` separates local traces from deployed ones; unset, they share
a bucket.

**Auth verifies Supabase tokens, and `SUPABASE_URL` turns it on.** `backend/app/core/security.py::get_principal`
checks the access token against the project's JWKS and finds or creates the `users` row for it;
no header is anonymous. With `SUPABASE_URL` empty every request is the seeded dev user, and
`DEV_AUTH=1` accepts `Bearer dev` locally — which `make smoke` sends, so it needs that set.
`require_user` (401) gates saving and editing, `require_staff` (403) gates Import, and a chat
someone else owns is 404. The frontend sends the token from `lib/api/auth-headers.ts` (browser)
and `auth-headers.server.ts` (server components). The plan, and what comes next (requests running
as the caller, then RLS), is `features-plans/access/auth-plan.md`.

## Deployment

> **`docs/DEPLOY.md` describes a hosting setup that is not the live one — ignore it.** It
> argues the backend cannot run on Vercel and belongs on a container host. **This table is
> authoritative.** (The root `vercel.json`, which described the same non-deployed shape, is
> gone; the two that remain are real config — see below.)

Docker is local development only. Deployed, the stack splits across three hosts — see
`docs/DEPLOY.md`:

| Piece | Runs on |
|---|---|
| Next.js frontend | Vercel project `sangam` (root directory `frontend`) |
| FastAPI backend | Vercel project `sangam-backend` (root `backend`, framework preset `fastapi`) |
| Postgres | Supabase |
| Neo4j | Neo4j Aura, or omitted |

Non-obvious constraints:

- **Use Supabase's session pooler, not the direct host.** `db.<ref>.supabase.co` resolves
  to IPv6 only, which Docker containers cannot reach — connections hang rather than fail.
  The pooler has IPv4. The transaction pooler (port 6543) breaks `pg_restore`; use session
  mode on 5432.
- **`NEXT_PUBLIC_*` is inlined at build time.** Changing it requires a fresh deploy, not
  just an env edit.
- **Vercel's Python bundle limit is 500 MB.** The backend's dependency tree is ~256 MB and
  fits with no trimming.

**Nothing deploys automatically; `.github/workflows/deploy.yml` is run by hand.** A merge to
`master` deploys nothing — run Actions → Deploy → Run workflow on `master` when it should go
out, and it deploys both projects. `frontend/vercel.json` and `backend/vercel.json` each set
`git.deploymentEnabled: false`, so no push builds anything either — before that, every push to
any of twenty branches built *both* projects, 40 deployments in one day. There are no preview
deployments by design.

Each `vercel.json` must stay in its project's **Root Directory** (`frontend` / `backend`) —
that is where Vercel reads it from, which is why a repo-root one did nothing. The workflow
needs one secret, `VERCEL_TOKEN`; the org and project IDs in it are identifiers, not
credentials.

## Working state

`.memory/STATE.md` is a gitignored scratch notebook: what is deployed right now, what is
half-finished, and gotchas already paid for. Read it at the start of a session and update
it as things change. It is not authoritative — anything that should outlive the current
work belongs in this file, `docs/`, or a commit message.

## Reading `.env`

`.claude/settings.json` denies reading `.env` through both the Read tool and common shell
commands. This is intentional. Read `.env.example` to learn which variables exist, and ask
the user for values rather than trying to work around the rule.
