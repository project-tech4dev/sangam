# Contributing to Sangam

Thanks for helping. This guide covers setting up the stack, the checks a change has to pass, and the
conventions that keep the codebase honest. For what each subsystem does and why, read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); for what shipped, [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

- [Ways to contribute](#ways-to-contribute)
- [Set up the stack](#set-up-the-stack)
- [Configuration](#configuration)
- [Everyday commands](#everyday-commands)
- [Tests and lint](#tests-and-lint)
- [Repository layout](#repository-layout)
- [Conventions](#conventions)
- [Opening a pull request](#opening-a-pull-request)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## Ways to contribute

- **Report a bug** or **suggest a feature** with the [issue templates](https://github.com/project-tech4dev/sangam/issues/new/choose).
- **Report a security problem privately**, never in an issue: see [`SECURITY.md`](SECURITY.md).
- **Fix something**: comment on the issue first so two people don't build the same thing, then open a PR.

Everyone taking part agrees to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up the stack

You need **Docker Desktop**, an **Anthropic API key** and a **Supabase project**. Supabase is not
optional: the frontend runs `lib/supabase/middleware.ts` on every request, and without its two keys every
page returns 500. Create a free project and copy the URL and the publishable key from **Project Settings →
API**. To reach `/import` and the signed-in Ask workspace you also need a sign-in method: enable the
**Google** provider under **Authentication → Providers**, or add a user by hand.

Give Docker Desktop at least **12 GB** of memory (Settings → Resources) if you run long Imports: the
Next.js dev server relays the whole stream and grows with it.

```bash
cp .env.example .env     # ANTHROPIC_API_KEY and the two NEXT_PUBLIC_SUPABASE_* values
make up                  # start Postgres, migrate, then start everything else
make seed                # migrate, then load the cohort data; the app is empty without it
make smoke               # confirm the stack is wired end to end
```

**Migrations are not automatic, and two things depend on them.** `db/init/` is a baseline only: 13 of
the SQL catalog's 37 tables arrive in `db/migrations/`, and the backend refuses to boot when one is
missing. The seeder needs `0002_taxonomy.sql` too. So locally `make up` runs `migrate` before the
backend starts and `make seed` runs it as well (a no-op the second time). Against a managed database
neither does: run `make migrate ENV=staging` yourself, after a backup.

| URL | What |
|---|---|
| http://localhost:3000 | The app |
| http://localhost:8010/docs | FastAPI's OpenAPI page |
| http://localhost:7474 | Neo4j browser, `neo4j` / `sangamneo4j` |

`make graph-seed` builds the optional knowledge graph afterwards, if `OPENAI_API_KEY` is set.

### Verify the install

```bash
make smoke                      # backend, frontend and the chat wire
SMOKE_SKIP_LLM=1 make smoke     # the same, minus the one real agent call
```

One check is expected to fail on a fresh clone: `documents: 96+ on file`. `make seed` does not create
those documents. Every other check should pass.

Then check the loop the product is built on. In the chat at `/ask`:

1. Ask **"Which organisations in the database work in Assam?"** A labelled `db_query` step appears in
   the trace before the answer streams, and the answer carries inline `[org:N]` markers.
2. As staff (the dev user is staff), ask how well one of them fits **Axis Bank Foundation**. `compare_fit`
   judges the fit in code, and each criterion says what it found or that it is not recorded.
3. Ask something the data cannot answer, such as **"What is this funder's 2027 budget?"** It should
   say it has no data rather than guess.
4. Refresh mid-conversation and keep going. Threads checkpoint into Postgres.

### Tools on the host

Four `make` targets run on the host, not in Docker:

| Target | Needs |
|---|---|
| `make evals`, `make client-docs` | a backend virtualenv at `backend/.venv`; the image has no pytest |
| `make dev-backend` | `uvicorn` on the host |
| `make dev-frontend` | Node 22 and `npm` |

## Configuration

`.env.example` documents every variable. The tiers:

| | Variables | Without them |
|---|---|---|
| **Required** | `ANTHROPIC_API_KEY` | the agents cannot answer |
| **Required (frontend)** | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | every page returns 500 |
| **Optional** | `OPENAI_API_KEY` + `NEO4J_*` | the graph disables itself cleanly |
| **Optional** | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | no auth (every request is the dev user), no document archive or Doc Vault |
| **Optional** | `MODEL`, `RESEARCH_MODEL`, `UTILITY_MODEL`, `SQL_AUDIT_MODEL` | the defaults in `backend/app/core/config.py` |
| **Optional** | `RESEARCH_PAGE_LIMIT`, `RESEARCH_MODEL_CALL_LIMIT` | no cap on an Import researcher's pages or model calls |
| **Optional** | `TAVILY_API_KEY` | Import and the news pipeline have no web search |
| **Optional** | `LANGFUSE_*`, `LANGSMITH_*` | no tracing; both can run at once |
| **Deployed only** | `ALLOWED_ORIGINS`, `ALLOWED_ORIGIN_REGEX` | irrelevant locally |

**`ENV` selects the database** for every target that touches one. `ENV=local` (the default) uses the
bundled Postgres; `ENV=staging` uses the `STAGING_DB_*` block through `docker-compose.staging.yml`. It
deploys nothing. `make up ENV=staging` runs your containers against the shared database, so an Import run
from your machine writes into the data the deployed app serves.

**Ports are fixed in `docker-compose.yml`:** frontend 3000, backend 8010 (from the container's 8000),
Postgres 5433 (from 5432), Neo4j 7474/7687. Outside Docker, `make dev-backend` serves on 8000.

### Models

Each agent runs on a model matched to how hard its work is:

| Variable | Default | Runs |
|---|---|---|
| `MODEL` | `anthropic:claude-opus-5-5` | Ask Sangam; the Import supervisor |
| `RESEARCH_MODEL` | `anthropic:claude-sonnet-5-5` | Import's entity-researchers and vault-reader |
| `UTILITY_MODEL` | `anthropic:claude-haiku-4-5` | fixed-shape work: catalog-writer, workbook-reader, article extraction |
| `SQL_AUDIT_MODEL` | `anthropic:claude-haiku-4-5` | the audit of each Ask SQL answer; `off` disables it |

A blank variable means the default, and `config.py` is the only place defaults are written.

## Everyday commands

`make help` lists every target. The ones you need first:

```bash
make up / make down / make logs
make frontend-reinstall  # force npm ci; make up installs only when dependencies change
make seed                # load the cohort data
make graph-seed          # build the Neo4j graph from Postgres (needs OPENAI_API_KEY)
make match [ORG=slug]    # save a Funder Match run for every org, or one (no model calls)
make migrate             # apply db/migrations/*.sql; make migrate-status shows what would run
make psql                # a shell on whichever database ENV selects
make dev-backend         # uvicorn on the host against the compose Postgres
make dev-frontend        # next dev on the host against a host backend on 8000
```

`make db-reset` drops every volume, including the graph and imported documents, then rebuilds and
reseeds. Fresh installs only.

## Tests and lint

Backend tests come in three tiers:

```bash
cd backend
pytest                          # unit tests; these never touch a database
pytest -m integration           # needs the compose Postgres on :5433
ruff check .                    # line length 110, target py312
make evals                      # golden questions through the real agent; COSTS MONEY
make evals TAG=canary           # the cheap subset
```

Unit tests build a router-only FastAPI app with no lifespan and a pool that raises on any use, so a test
that reaches for a database fails loudly. Monkeypatch the `repositories/` function, not the pool. Async
tests need no decorator (`asyncio_mode = "auto"`). Evals sit behind a `--run-evals` conftest flag rather
than a marker filter, because a command-line `-m` replaces addopts' `-m` and would start billing.

Frontend:

```bash
cd frontend
npm run lint                    # eslint
npm test                        # vitest
npm run coverage                # vitest with v8 coverage, as CI runs it
npm run build                   # next build; type errors surface here, never in next dev
```

CI runs all of it on every PR, plus the integration tier against a fresh pgvector Postgres, and uploads
coverage to Codecov, where backend and frontend are gated separately: neither may drop by more than 1%,
neither may fall under 75%, and 75% of the lines a PR changes, backend or frontend, must be covered.

## Repository layout

```
backend/app/
  main.py          create_app() and the ASGI entrypoint; wiring only
  core/            config · security (Supabase JWT) · lifespan · logging · egress
  db/              pool · checkpointer (LangGraph) · migrate (the runner)
  api/             router.py (one aggregate router) · deps · routes/<resource>.py
  repositories/    hand-written SQL, one module per resource
  schemas/         Pydantic, one module per resource
  agent/           Ask Sangam: build.py · tools/ · skills/ · instructions.md · harness.py
  ingest/          Sangam Scout (Import): its agent, tools/, skills/, prompts/ and pipeline
  matching/        Funder Match: rubric · rules · match (pure) · service
  proposals/       Sangam Pitch
  integrations/    graphiti · tracing · storage

frontend/
  app/             routes only: pages, layouts, route handlers
  features/        one folder per screen: ask · auth · home · ingest · registry · resources · settings · taxonomy · terms
  components/      ui/ (display primitives) · layout/ (site chrome)
  lib/             api/ · supabase/ · format.ts

db/init/           the baseline schema, run once on a new database
db/migrations/     every change after it, applied by make migrate
seed/              vendored data and idempotent loaders (seed/data/README.md has the provenance)
scripts/           smoke.sh, the db-url resolver and helpers
```

## Conventions

The full list lives in [`CLAUDE.md`](CLAUDE.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The
ones a first PR most often trips on:

- **Postgres is the system of record.** The Neo4j graph is derived from it and rebuildable; nothing
  lives only in the graph.
- **Schema changes go in a new `db/migrations/*.sql`**, never in `db/init/`. See
  [`db/migrations/README.md`](db/migrations/README.md).
- **A REST resource is three files:** `api/routes/<r>.py`, `repositories/<r>.py`, `schemas/<r>.py`, plus
  one line in `api/router.py`. There is no ORM.
- **Agent tools never raise, and every row they return is cited** (`[org:N]`, `[funder:N]` and so on).
  A raised exception ends the whole run; an uncited row produces an uncitable answer.
- **Adding a table to the SQL catalog is a security decision.** `docs/SQL_AGENT.md` explains the four
  layers between the model's SQL and the database.
- **Every fetch of a model-supplied URL goes through `guarded_client`** (`app/core/egress.py`).
- **Nothing that is not a route goes under `frontend/app/`**, and no new module goes flat at the top of
  `backend/app/`.
- **Styles go in classes built from the design system's tokens**, icons come from `lucide-react`, and a
  change to a component updates the design system in the same PR (`docs/DESIGN_SYSTEM.md`).
- **Comments are short:** say why, in a line or two.

## Opening a pull request

1. Branch from `master` (or from the PR you are stacking on). A change with more than one milestone is a
   plan in `docs/features/YYYY-MM-DD-<name>.md` first, then one PR per milestone.
2. Add tests for the deterministic code you change.
3. If you changed a tool, table, route or flow, run `make wiki-update`. Never hand-edit `openwiki/`.
4. If you changed a rule, edit `docs/ARCHITECTURE.md`; if it ships, add a line to `docs/CHANGELOG.md`.
5. Run the checks above, then open the PR. The template's checklist repeats these steps.

Merging deploys nothing; a maintainer runs the Deploy workflow by hand.

## Deployment

Docker is for local development only. Deployed, the frontend and backend are two Vercel projects (root
directories `frontend` and `backend`), Postgres is Supabase, and Neo4j is Aura or omitted. Both functions
run in `bom1`, beside the database. Two traps:

- **Use Supabase's session pooler, not the direct host.** `db.<ref>.supabase.co` is IPv6-only and
  containers hang on it. The transaction pooler on 6543 breaks `pg_restore`; use session mode on 5432.
- **`NEXT_PUBLIC_*` is inlined at build time.** Changing one needs a fresh deploy.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `column "code" of relation "tags" does not exist` while seeding | migrations not applied | `make migrate`, then `make seed` |
| Every page returns 500 | `NEXT_PUBLIC_SUPABASE_*` empty | set both, then `make up`; `docker compose restart` keeps the old environment |
| `/import` sends you to sign in | working as designed | sign in, or enable a Supabase auth provider |
| Postgres never starts | `COMPOSE_PROFILES=localdb` missing from `.env` | add it back |
| `make smoke` fails only on `documents: 96+` | `make seed` does not create them | expected on a fresh clone |
| `Module not found` after a `package.json` change | the install stamp is stale | `make frontend-reinstall` |
| A staging connection hangs | the direct host is IPv6-only | use the session pooler on 5432 |
| Type errors only on deploy | `next dev` does not typecheck | `npm run build` before pushing |

## Terms you will meet in the code

| Term | Meaning |
|---|---|
| **Deep agent** | A `deepagents` preset over LangGraph: planning middleware and subagents around a tool-calling loop. Not an alternative to LangGraph |
| **Harness** | `app/agent/harness.py`, which strips the filesystem tools and general-purpose subagent `deepagents` adds, so each agent runs only its declared tools |
| **Skill** | A `SKILL.md` procedure an agent reads only when a request needs it; only its name and description sit in the prompt |
| **Model tier** | Which model a piece of work runs on: `MODEL`, `RESEARCH_MODEL` or `UTILITY_MODEL` |
| **AG-UI** | The protocol that streams agent events (tool calls, tokens) from the backend to the chat over SSE |
| **match-v2** | Funder Match's rubric (`app/matching/rubric.py`); an unknown criterion is left out of the score, not counted as zero |
