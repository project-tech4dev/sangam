---
type: quickstart
title: Quickstart
description: First run of the Sangam stack, the make targets that matter (including the Wiki group that regenerates openwiki/), a repo map, the ground rules, and a task-to-page routing table that covers all three agents (Ask, Import/Scout, Proposal Copilot) plus the architecture, workflow, operations and testing pages.
tags: [quickstart, onboarding, make, repo-map, routing, agents, proposals]
sources:
  - id: openwiki-source-5f5b95b3d6a215fa02ceb945
    resource: repo://.env.example
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-6766b7a0c14857435d2077c9
    resource: repo://.github/workflows/deploy.yml
  - id: openwiki-source-8037e2358a2c4f9b2c722a11
    resource: repo://AGENTS.md
  - id: openwiki-source-d1e8740dfb3dd3dd2e214ddc
    resource: repo://backend/app/agent/build.py
  - id: openwiki-source-7faba850789bc67a49b79a3f
    resource: repo://backend/app/agent/tools/sql/catalog.py
  - id: openwiki-source-e136029ec7d24feaceb8ce72
    resource: repo://backend/app/core/lifespan.py
  - id: openwiki-source-b52886aad1fc413e4e030f22
    resource: repo://backend/app/core/security.py
  - id: openwiki-source-0c2810df96342c5efec98a57
    resource: repo://backend/app/proposals/agent.py
  - id: openwiki-source-f3d6f52af409427e4d0e8a39
    resource: repo://backend/app/proposals/work.py
  - id: openwiki-source-1157f5d2ae5aa2bccc1057d0
    resource: repo://backend/app/repositories/proposals.py
  - id: openwiki-source-a2371d6362e5db4bc834ad03
    resource: repo://CLAUDE.md
  - id: openwiki-source-5f7022cb75865b779a5792a0
    resource: repo://codecov.yml
  - id: openwiki-source-3d121c1ca466c424ca2b4936
    resource: repo://db/migrations/0048_proposal_work.sql
  - id: openwiki-source-b79fbbd921df689b4bbdc82f
    resource: repo://docker-compose.yml
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-10-19T08:30:22.232Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-10-19T08:30:22.232Z
---

# Quickstart

Sangam is grant intelligence for Indian civil-society organisations and funders. Three LangGraph agents share one database, and the repo has no others:

| Agent | On screen | Backend chat route | What it does | Read |
|---|---|---|---|---|
| **Ask** | Ask Sangam | `/agent` | Answers questions about the registry with cited, read-only SQL | [Ask Sangam](architecture/ask-sangam.md), [One Ask turn](workflows/ask-turn.md) |
| **Import** | Scout (Sangam Import) | `/ingest` | Pulls new funder and NGO data in from public sources, with a human choosing the sources first | [Import / Scout](architecture/sangam-import-scout.md), [One Import turn](workflows/import-turn.md) |
| **Proposal Copilot** | Sangam Pitch | `/proposal` | Works with an NGO's team on one grant proposal, step by step, inside rules the code checks | [Proposal Copilot](architecture/proposal-copilot.md), [One proposal, end to end](workflows/proposal-lifecycle.md) |

Postgres is the system of record, and every fact an agent states carries a citation back to a row. The names differ on screen and in code: Scout keeps "ingest" and "Import" in routes and threads (the backend posts to `/ingest`, the screen is `/import`), and Sangam Pitch keeps "proposal".

This page covers the first run, the commands you will use, where things live, and which page to read next.

## Ground rules

These four hold across the repo. Break one and something fails in a non-obvious way.

1. **Migrations are not automatic.** `db/init/` is only the baseline for a new database. Every later change is a plain SQL file in `db/migrations/`, applied by `make migrate`. Locally, `make up` and `make seed` run it for you. Against a managed database you run `make migrate ENV=staging` yourself, after a backup. The backend refuses to boot against an unmigrated database (see ground rule 4).
2. **Nothing deploys automatically.** Deploying is a manual run of the Deploy workflow (Actions, Deploy, Run workflow, `workflow_dispatch` only). A merge or push builds nothing, and Vercel's Git integration is disabled. The separate CI workflow runs on every PR and push to `master`, but it only checks (lint, tests, frontend build) and deploys nothing. `ENV=staging` does not deploy anything either. It points your local tooling, and with `make up ENV=staging` your local containers, at the shared managed database. See [Deploying by Hand](workflows/deploying-by-hand.md).
3. **Postgres is the system of record.** The Neo4j graph is derived from Postgres (`make graph-seed`) and can be wiped and rebuilt. Nothing should live only in the graph. If the two disagree, Postgres wins.
4. **`catalog.py` is a security allowlist.** `backend/app/agent/tools/sql/catalog.py` lists the tables and columns Ask's model-written SQL may read. It allowlists 37 tables, and `KNOWN_EXCLUDED` names 22 more that are deliberately kept out (for example `proposals`, `users` and the checkpoint tables). A table missing from the catalog is invisible to Ask. At boot, `_verify_sql_catalog` in `core/lifespan.py` raises if the catalog and the database disagree, for example when a catalogued table is missing because migrations were not applied. A table that is merely undeclared is only logged, so it stays invisible until someone catalogues it or marks it excluded.

## First run

You need Docker Desktop and an `ANTHROPIC_API_KEY`. To sign in you also need a Supabase project. Without `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, the frontend does not fail: `lib/supabase/middleware.ts` passes every request through and gates nothing, so the public pages and the `/ask` preview still render. But nobody can sign in (the sign-in dialog says the Supabase keys are not set), so the full Ask workspace (which also holds Funder Match and Proposals) and Import are out of reach. Reaching them needs a sign-in method too, such as the Google provider enabled in Supabase.

```bash
cp .env.example .env     # set ANTHROPIC_API_KEY and the two NEXT_PUBLIC_SUPABASE_* values
make up                  # bring up Postgres, migrate, then build and start the whole stack
make seed                # load the cohort data: the app is empty without it
make smoke               # confirm backend, frontend and the chat wire
```

- **`make seed` is required.** Without it the registry, the Ask workspace and Funder Match have nothing to show, and there is nothing to start a proposal from. Locally it runs `migrate` first, because the taxonomy seeder needs migration `0002`. It loads the cohort, the LGD geography, and the taxonomy.
- **One smoke check is expected to fail on a fresh clone.** `documents: 96+ on file` fails because `make seed` does not create those documents. `SMOKE_SKIP_LLM=1 make smoke` skips the one real agent call.
- `COMPOSE_PROFILES=localdb` in `.env` starts the bundled Postgres. Dropping it means you are pointing `DATABASE_URL` at a managed database, and `make up` then deliberately does not migrate.
- `OPENAI_API_KEY` and `make graph-seed` are optional. Without a key the graph disables itself and the agent is told to use the database tools.

Once the stack is up:

| URL | What |
|---|---|
| http://localhost:3000 | Home; `/registry` is the public registry |
| http://localhost:3000/ask | Ask Sangam (sign-in for the full workspace, where Funder Match and Proposals live as views) |
| http://localhost:3000/import | Sangam Import (sign-in required) |
| http://localhost:8010/docs | FastAPI OpenAPI |
| http://localhost:7474 | Neo4j browser |

Ports are fixed in `docker-compose.yml`: frontend 3000, backend 8010 (published from container port 8000), Postgres 5433 (from 5432), and Neo4j 7474/7687. Outside Docker, `make dev-backend` serves uvicorn on 8000 directly, which is why `dev-frontend` points at 8000.

## Make targets that matter

`make help` lists everything, grouped. Bare `make` runs `help` and starts nothing.

| Target | What it does | Notes |
|---|---|---|
| `make up` | Starts Postgres, runs `migrate`, then builds and starts Postgres, Neo4j, backend and frontend with `--wait` | The migrate step is local-only, and skipped when the bundled Postgres is off |
| `make seed` | Loads cohort data, then the taxonomy | Depends on `migrate` when `ENV=local` |
| `make migrate` / `migrate-status` | Applies, or lists, `db/migrations/*.sql` | Works on any `ENV` |
| `make smoke` | End-to-end check of backend, frontend and chat wire | Runs `scripts/smoke.sh` |
| `make match [ORG=slug]` | Saves a Funder Match run for every org, or one | In code, no model, no cost. A proposal can only start from a saved run |
| `make evals [TAG=… K=…]` | Golden questions through the real agent | **Costs money**: about 10 cents a case, except the `cost` cases (about $0.90 a run), which a run with no `TAG` includes. `TAG=canary` is the cheap subset, `TAG=import` the Import canaries (needs `TAVILY_API_KEY`), `K=<name>` one case. Runs on the host venv `backend/.venv`, so create it first |
| `make news-pull ORG=… / FUNDER=…` | Pulls news through Tavily | Prints the plan first; `CONFIRM=1` runs for everyone |
| `make graph-seed` | Builds the Neo4j graph from Postgres | Needs `OPENAI_API_KEY` |
| `make psql` | Interactive shell against the database `ENV` selects | |
| `make dev-backend` | uvicorn `--reload` on the host against Postgres on 5433 | Needs host `uvicorn` |
| `make dev-frontend` | `next dev` on the host with `AGENT_URL` at `localhost:8000` | Needs Node 22 and npm |
| `make wiki` | Generates `openwiki/` from scratch | **Costs money.** Real model calls |
| `make wiki-update` | Refreshes only the `openwiki/` pages whose source changed | No model call when nothing changed |
| `make wiki-fix MSG="…"` | Asks OpenWiki to correct pages, given what is wrong and where | **Costs money.** Real model calls; fails with a usage message if `MSG` is empty |
| `make wiki-deploy` | Publishes `openwiki/` as a static site to the Vercel project `sangam-wiki` | By hand, needs a one-time `npx vercel login` |

Related targets: `down`, `logs`, `frontend-reinstall` (forces an `npm ci`), `locations-seed`, `taxonomy-seed`, `news-seed`, `news-visibility` (rewrites who sees each story after a bar or rule changes), `db-url`, `client-docs`, and `staff-source` (staging only). `db-clean`, `db-reset`, `db-backup` and `db-upgrade` are local-only. `db-reset` drops every volume, including Neo4j and any imported documents.

### The `Wiki` group

The `##@ Wiki` group in the Makefile drives the generated `openwiki/` code wiki, including this page. `wiki`, `wiki-update` and `wiki-fix` run the pinned `openwiki@0.7.2` through `npx`, source `.env` quietly, use Anthropic explicitly (otherwise OpenWiki would pick `OPENAI_API_KEY`, the graph's key, first), and delete `openwiki/.run.json` afterwards.

- `make wiki` regenerates the whole wiki from scratch. It calls a model and costs money.
- `make wiki-update` rewrites only pages whose cited source changed. When nothing changed it makes no model call.
- `make wiki-fix MSG="what is wrong, and where"` asks OpenWiki's agent to correct pages. It calls a model and costs money.
- `make wiki-deploy` only publishes what is already there. It is separate from the app's Deploy workflow, which never touches it.

The page text is generated, so do not hand-edit it. Steer generation through `openwiki/INSTRUCTIONS.md`, and correct a wrong page with `make wiki-fix`, so the page and its evidence claims are changed by the same tool. `wiki-update` reacts to code changes only: editing `INSTRUCTIONS.md` alone rewrites nothing.

### Agent instructions

`CLAUDE.md` remains the source of the repo's invariants and commands. Its "Read first" section names three layers: `openwiki/` (the generated facts, starting at this page), `docs/ARCHITECTURE.md` (rules and decisions) and `docs/CHANGELOG.md` (what shipped, plus "Not finished"). `AGENTS.md` is a thin pointer that sends agents to `CLAUDE.md` first and names the same three.

The wiki is optional, just-in-time context rather than startup reading. Agents should not preload or search it at task start. They use `openwiki_search` and `openwiki_read` only when an unfamiliar area materially affects the task, and fall back to this page and its links only when those retrieval tools are unavailable. Source code and tests stay authoritative over the wiki, and over `docs/`.

By `CLAUDE.md` convention, a PR that changes a tool, table, route or flow runs `make wiki-update`, one that changes a rule edits `docs/ARCHITECTURE.md`, and one that ships adds a `docs/CHANGELOG.md` line. Nested `CLAUDE.md` files in `backend/app/agent/`, `backend/app/ingest/`, `backend/app/matching/`, `backend/app/core/`, `db/` and `frontend/` load on their own and point at the matching wiki pages. `docs/README.md` indexes the deeper design docs (`SQL_AGENT.md`, `INGEST.md`, `SKILLS.md`, `DATA_PLATFORM.md`, `DESIGN_SYSTEM.md`).

### Choosing a database with `ENV`

`ENV=local` (the default) uses the bundled Postgres. `ENV=staging` uses the `STAGING_DB_*` block through `docker-compose.staging.yml`. `ENV` is honoured by `up`, `down`, `logs`, `seed`, `migrate`, `psql`, `client-docs` and the remote targets. It is not honoured by the local-only maintenance group. `STAGING_DB_*` exist only for local tooling. A deployed backend reads `DATABASE_URL`. Details are in [Environments and Env Vars](operations/environments.md).

## Repo map

```
backend/app/
  main.py         create_app() and the ASGI entrypoint (wiring only)
  core/           Settings, Supabase JWT security (incl. per-agent chat access), lifespan, logging
  db/             pool, LangGraph checkpointer, migrate runner
  api/            one aggregate router plus routes/<resource>.py
  repositories/   hand-written SQL, one module per resource (no ORM)
  schemas/        Pydantic, one module per resource
  agent/          Ask Sangam: build.py, tools/ (incl. tools/sql/catalog.py), instructions.md
  ingest/         Sangam Import: agent, tools, skills/, pipeline, news/
  proposals/      Sangam Pitch: agent, steps, gates, work, facts, trace, readers, tools/
  matching/       Funder Match: rubric, rules, match, service, run
  integrations/   Graphiti/Neo4j lifecycle, tracing, Supabase Storage
backend/tests/    unit, integration and evals tiers
frontend/
  app/            routes only
  features/       one folder per screen (the Ask workspace holds the Funder Match and Proposals views)
  components/ lib/  UI primitives, API client, auth headers, chat wiring
db/init/          baseline schema (runs once on a new database)
db/migrations/    every change after the baseline (0048 added proposals.work)
seed/             idempotent loaders and their vendored data
scripts/          smoke.sh and the db-url resolver
docs/             longer human-written design docs
```

Two structural rules: nothing that is not a route goes under `frontend/app/`, and no new module goes flat at the top of `backend/app/`. A REST resource is always a route, a repository and a schema file, plus one line in `api/router.py`.

Agents are built lazily. `lifespan.py` opens the pool, checks the catalog and opens the checkpointer at boot, and registers `/agent`, `/ingest` and `/proposal` as routes of our own. All three agents are built together by `load_agents`, once and under a lock, on the first post to any of those routes, or on the first REST route that calls `get_graph`. Each route declares who may post to it in `AGENT_ACCESS`, and a path with no entry fails at boot. Ask has exactly seven tools, and `compare_fit` is the only one whose SQL is fixed rather than model-written. Proposal Copilot has its own tool list and never writes SQL of its own: code in `backend/app/proposals/` owns the steps and checks, and `proposals.work` is only changed through one write path. See [Proposal Copilot](architecture/proposal-copilot.md).

## Task routing

| I want to… | Read |
|---|---|
| Understand the backend app factory, settings, model tiers, lazy agent loading, tracing, deploy topology | [Platform](architecture/platform.md) |
| Change Ask's tools, prompt, SQL validation, citations or answer audit | [Ask Sangam](architecture/ask-sangam.md) |
| Change Import (Scout): subagents, research, brief, promote, undo | [Sangam Import / Scout](architecture/sangam-import-scout.md) |
| Change the proposal agent, its steps and gates, the fact list, the trace check, polish or the Word file | [Proposal Copilot (Sangam Pitch)](architecture/proposal-copilot.md) |
| Follow one proposal from a Funder Match card to a Word download | [One proposal, end to end](workflows/proposal-lifecycle.md) |
| Add a table to the SQL catalog, or understand the schema | [Data and Migrations](architecture/data-and-migrations.md) |
| Understand roles, RLS, or which database pool code uses | [Auth, Roles and RLS](architecture/auth-roles-rls.md) |
| Change the fit rubric or saved match runs | [Funder Match](architecture/funder-match.md) |
| Work on the news pipeline or story visibility | [Media & Signals](architecture/media-and-signals.md) |
| Change a screen, the chat proxy or the API client | [Frontend](architecture/frontend.md) |
| Trace a question through the whole system | [One Ask Turn, End to End](workflows/ask-turn.md) |
| Trace an import from source choice to undo | [One Import Turn](workflows/import-turn.md) |
| Add a schema change | [Writing and Applying a Migration](workflows/writing-a-migration.md) |
| Ship to Vercel | [Deploying by Hand](workflows/deploying-by-hand.md) |
| Find an env var, or understand `ENV=local\|staging` | [Environments and Env Vars](operations/environments.md) |
| Work on Vercel, Supabase pooler, Tavily, Langfuse or Aura specifics | [Vercel and Supabase Specifics](operations/deploy-and-vendors.md) |
| Run or write tests, read the CI workflow or coverage rules, or learn what costs money | [Testing](testing/overview.md) |

The folders are `architecture/` (how each subsystem is built), `workflows/` (end-to-end traces and step-by-step procedures), `operations/` (configuration and vendors) and `testing/`. Each folder also has an `index.md` that lists its pages: [Architecture index](architecture/index.md), [Workflows index](workflows/index.md), [Operations index](operations/index.md) and [Testing index](testing/index.md). The wiki-wide [index](index.md) sits above them.

## Testing at a glance

Backend tests have three tiers. Unit tests never touch a database: they build a router-only app with a sentinel pool that raises on any use, so monkeypatch the `repositories/` function instead. Integration tests carry the `integration` mark and need the compose Postgres on 5433. Evals carry the `eval` mark, run only with `--run-evals` (a conftest flag, so `pytest -m integration` can never start billing model calls), and make real model calls (about 10 cents a case; the `cost` cases about $0.90). Locally, `cd backend && pytest -m "not integration"` is the quick loop and `ruff check .` the lint (line length 110).

CI (`.github/workflows/ci.yml`) runs on every PR and push to `master` with four jobs: `ruff check`, the unit tier with coverage, the integration tier against a fresh pgvector Postgres (baseline, `migrate`, then the seeders, with two preserved-dump tests deselected), and the frontend (`npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm run build`). The two coverage reports go to Codecov, and `codecov.yml` fails a PR that lowers total coverage by more than 1% or covers under 70% of the lines it changes. Evals are not in CI. The proposal rules are pure functions over a `work` dict, so their tests (`test_proposals_work.py`, `test_proposal_agent.py` and the `test_proposal_*` companions) need no database either. Before pushing frontend changes, run `npm run build`, because type errors surface there and never in `next dev`. See [Testing](testing/overview.md).
