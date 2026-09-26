# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

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

Tests and lint (backend):

```bash
cd backend
pytest                              # all tests
pytest tests/test_orgs.py           # one file
pytest -k "score"                   # one pattern
pytest -m "not integration"         # skip tests needing the compose Postgres on :5433
ruff check .                        # line-length 110, target py312
```

Frontend: `npm run lint`, `npm run build`. Run `next build` before pushing — type errors
surface there and never in `next dev`.

## Environment selection

`ENV` picks the database for every DB-touching target: `ENV=local` (default) uses the
bundled Postgres container, `ENV=staging` uses the `STAGING_DB_*` block in `.env` via
`docker-compose.staging.yml`. Compose resolves the connection string so there is one
source of truth; `scripts/db-url.sh` surfaces its error when a staging variable is missing.

`ENV=staging` deploys nothing. It points local tooling at the managed database.

**`STAGING_DB_*` are local-tooling variables only.** The backend itself reads
`DATABASE_URL` (`backend/app/config.py`). Setting `STAGING_DB_*` on a deployed host does
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

Three things worth knowing before changing anything:

**Postgres is the system of record.** The Neo4j graph stores relationship facts *extracted*
from source text and is rebuildable from Postgres (`seed/graph_seed.py`). Keep that
property — nothing should live only in the graph.

**The agent reaches the database through tools, not the API.** `backend/app/tools/db_tools.py`
queries repositories directly. `backend/app/api/` serves the frontend's REST calls. They
share `repositories/` but are separate paths; changing one does not change the other.

**The frontend talks to the backend two ways.** Server components use
`frontend/app/lib/api.ts` (reads `AGENT_URL`, strips the `/agent` suffix to derive the REST
base). The chat UI posts to `/api/copilotkit/[[...slug]]/route.ts`, which proxies to the
backend's `/agent` over AG-UI. `AGENT_URL` therefore ends in `/agent` while
`NEXT_PUBLIC_API_URL` does not — the asymmetry is deliberate.

## Conventions

**Schema changes go in `db/migrations/*.sql`, never in `db/init/02_schema.sql`.** The
baseline is what a brand-new database gets; migrations carry everything after it. See
`db/migrations/README.md`.

**Provenance columns on every scraped or extracted table**: `source_url`, `source_name`,
`fetched_at`, `content_hash`, `extractor_version`. Populate them — the product promise is
that every field traces to a source.

**Optional subsystems degrade, they do not crash.** The graph activates only when
`NEO4J_URI` and an OpenAI key are both set (`Settings.graph_enabled`); `graphiti_core` is
imported lazily inside `open_graph()` so the app boots without it, and `search_graph`
returns a message telling the agent to use the database tools instead. Langfuse follows
the same pattern. Preserve this when adding integrations.

**Auth is a deliberate stub.** `backend/app/auth.py::get_current_user` resolves every
request to one seeded user. Every route already does `Depends(get_current_user)`, so
swapping in Supabase JWT verification changes only that function. The frontend sends a
hardcoded `Authorization: Bearer dev` from five call sites.

## Deployment

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
