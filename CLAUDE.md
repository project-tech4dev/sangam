# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

First run, from a clean checkout (needs Docker and an `ANTHROPIC_API_KEY`):

```bash
cp .env.example .env     # set ANTHROPIC_API_KEY, or another provider's key + MODEL
make up                  # build and start everything
make seed                # load the cohort data — the app is empty without it
make smoke               # confirm the stack is wired end to end
```

Then http://localhost:3000 for the app and http://localhost:8010/docs for the API.
`OPENAI_API_KEY` and `make graph-seed` are optional — the graph disables itself cleanly.

Everyday targets:

```bash
make up                  # start the whole stack (Postgres, Neo4j, backend, frontend)
make down / make logs
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

`asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio`. **Unit tests never
touch a database**: `client_for(*routers)` builds a router-only FastAPI app with no lifespan
(no pool, no agent, no model) and overrides two dependencies — `get_current_user`, and
`get_pool` with a `_SentinelPool` that raises on any attribute access. Routers take the pool
as `PoolDep`, so that one override covers every router; monkeypatch the `repositories/`
function rather than the pool. Only `tests/test_migration_integrity.py` carries the
`integration` mark.

Running the migration runner outside Docker needs `MIGRATIONS_DIR` — it defaults to the
container path `/srv/db/migrations`.

Frontend: `npm run lint`, `npm run build`. Run `next build` before pushing — type errors
surface there and never in `next dev`.

## Environment selection

`ENV` picks the database for every DB-touching target: `ENV=local` (default) uses the
bundled Postgres container, `ENV=staging` uses the `STAGING_DB_*` block in `.env` via
`docker-compose.staging.yml`. Compose resolves the connection string so there is one
source of truth; `scripts/db-url.sh` surfaces its error when a staging variable is missing.

`ENV=staging` deploys nothing. It points local tooling at the managed database.

**`STAGING_DB_*` are local-tooling variables only.** The backend itself reads
`DATABASE_URL` (`backend/app/core/config.py`). Setting `STAGING_DB_*` on a deployed host does
nothing.

## Architecture

```
browser ── Next.js ── /api/copilotkit (CopilotKit v2 runtime)
              │             │ AG-UI (SSE)
              │ REST        ▼
              └────── FastAPI ── LangGraph deep agent
                          │          tools: search_orgs · get_funder · get_grants
                          │                 get_fit_scores · search_graph · fetch_url
                          ▼
              Postgres + pgvector        Neo4j (optional)
```

### Layout

```
backend/app/
  main.py          create_app() + `app = create_app()` — the ASGI entrypoint, wiring only
  core/            config.py (Settings) · security.py (auth stub) · lifespan.py · logging.py
  db/              pool.py (PoolDep) · checkpointer.py (LangGraph) · migrate.py (runner)
  api/             router.py (the one aggregate router) · deps.py · routes/<resource>.py
  repositories/    hand-written SQL, one module per resource
  schemas/         Pydantic, one module per resource
  agent/           graph.py (builds the deep agent) · models.py · prompt.py
  tools/           the agent's tools
  integrations/    graphiti.py (Neo4j client lifecycle)

frontend/
  app/             routes ONLY — pages, layouts, route handlers
  features/        one folder per screen: ask/, registry/
  components/      ui/ (display primitives) · layout/ (site chrome)
  lib/             api/ (client + types) · format.ts
```

Two rules keep this from eroding: **nothing that is not a route goes under
`frontend/app/`** (a `_private` folder is the smell that something belongs in
`features/`), and **no new module goes flat at the top of `backend/app/`** — it belongs in
one of the groups above. Cross-folder frontend imports use the `@/` alias, not `../../..`.

Things worth knowing before changing anything:

**Postgres is the system of record.** The Neo4j graph stores relationship facts *extracted*
from source text and is rebuildable from Postgres (`seed/graph_seed.py`). Keep that
property — nothing should live only in the graph.

**The agent reaches the database through tools, not the API.** `backend/app/tools/db_tools.py`
queries repositories directly. `backend/app/api/routes/` serves the frontend's REST calls. They
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

**Only one file is called `graph`**: `app/tools/graph_tools.py`, the `search_graph` agent
tool. The deep agent is built in `app/agent/build.py`, and the Graphiti/Neo4j client lifecycle
(`open_graph`, `graph_status`, `client`) lives in `app/integrations/graphiti.py`. Both used to
be called `graph.py` too, which made tracebacks ambiguous.

**`deepagents` is LangGraph, not an alternative to it.** `create_deep_agent()` is a preset
middleware stack over `langchain.agents.create_agent` and returns a compiled LangGraph
graph — which is exactly what `AsyncPostgresSaver` checkpointing and
`add_langgraph_fastapi_endpoint` require. Dropping `deepagents` would not drop LangGraph.

**The agent has exactly six tools, and some config implies more than is wired.**
`app/agent/build.py` registers `search_orgs`, `get_funder`, `get_grants`, `get_fit_scores`,
`search_graph`, `fetch_url` — nothing else. `app/tools/mcp.py` (GitHub and Playwright MCP
servers), `app/tools/files.py` (`download_file`, `read_pdf`) and `web.make_web_search`
(Tavily) are complete but imported nowhere, and the `Settings` fields that feed them —
`tavily_api_key`, `github_pat`, `github_mcp_url`, `playwright_mcp_url`, `mcp_servers` —
therefore do nothing until those tools are registered. Setting them changes no behaviour.

## Conventions

**Schema changes go in `db/migrations/*.sql`, never in `db/init/02_schema.sql`.** The
baseline is what a brand-new database gets; migrations carry everything after it. See
`db/migrations/README.md`. `db/migrations/` currently holds only that README — the baseline
is still the entire schema, and `make migrate` creates `schema_migrations` but applies
nothing until the first `0001_*.sql` lands. (`README.md` says migrations live in `db/init/`;
it is stale, this rule wins.)

**Agent tools never raise, and every row they return is cited.** Two conventions that the
product depends on and that a new tool silently breaks:

- *Errors are return values.* A raised exception aborts the entire agent run; a returned
  error string lets the model see the failure and adapt. Every tool body in `app/tools/` is
  wrapped in `try/except` returning `f"<tool> failed: {exc}"`.
- *Every database and graph row carries a citation marker* — `[org:N]`, `[funder:N]`,
  `[grant:N]`, `[score:N]`, `[graph:<uuid8>]` — because `app/agent/prompt.py` requires the
  model to repeat it inline next to each fact. A tool that returns uncited rows produces
  uncitable answers. (`fetch_url` is the exception: live web text carries no marker.)

Adding a tool: write the async function in `app/tools/` with both conventions, register it
in `app/agent/build.py`, describe its marker in `app/agent/prompt.py`, and add a label to
`frontend/features/ask/lib/toolLabels.ts` (unlabelled tools fall back to a humanised name;
`HIDDEN_TOOLS` there suppresses the `deepagents` filesystem built-ins from the trace).

**Provenance columns on every scraped or extracted table**: `source_url`, `source_name`,
`fetched_at`, `content_hash`, `extractor_version`. Populate them — the product promise is
that every field traces to a source.

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

**Auth is a deliberate stub.** `backend/app/core/security.py::get_current_user` resolves every
request to one seeded user. Every route already does `Depends(get_current_user)`, so
swapping in Supabase JWT verification changes only that function. The frontend sends a
hardcoded `Authorization: Bearer dev` from five call sites.

## Deployment

> **Two other files describe a hosting setup that is not the live one — ignore them.**
> `docs/DEPLOY.md` argues the backend cannot run on Vercel and belongs on a container host,
> and the tracked `vercel.json` describes a single project with the backend as a
> `runtime: "container"` build of `backend/Dockerfile`. Neither is what is deployed. **This
> table is authoritative.**

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
- The backend runs as a Vercel Function, so the filesystem is ephemeral — anything written
  to `downloads_dir` disappears between invocations.

## Working state

`.memory/STATE.md` is a gitignored scratch notebook: what is deployed right now, what is
half-finished, and gotchas already paid for. Read it at the start of a session and update
it as things change. It is not authoritative — anything that should outlive the current
work belongs in this file, `docs/`, or a commit message.

## Reading `.env`

`.claude/settings.json` denies reading `.env` through both the Read tool and common shell
commands. This is intentional. Read `.env.example` to learn which variables exist, and ask
the user for values rather than trying to work around the rule.
