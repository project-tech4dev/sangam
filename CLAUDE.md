# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read first

You do not need to read the code to learn how a subsystem works. Three layers, each with one job:

- **`openwiki/`** (start at `openwiki/quickstart.md`): the generated *what*: tools, routes, tables, settings and
  walkthroughs, each claim pinned to source lines. Open the page for an unfamiliar area; don't preload it.
  In Claude Code, `openwiki_search` / `openwiki_read` (`.mcp.json`, skill `.claude/skills/openwiki/`) return just the section.
- **`docs/ARCHITECTURE.md`**: the hand-written *why*: invariants, decisions and known regressions, one section per area.
- **`docs/CHANGELOG.md`**: everything that shipped, by subsystem and PR, plus **"Not finished"**.

Source code and tests win over all three. Nested `CLAUDE.md` files in `backend/app/agent/`, `backend/app/ingest/`,
`backend/app/matching/`, `backend/app/core/`, `db/` and `frontend/` load on their own and point at their pages.
A PR that changes a tool, table, route or flow runs `make wiki-update`; one that changes a rule edits ARCHITECTURE.md;
one that ships adds a CHANGELOG line. **Never hand-edit `openwiki/`**: correct it with `make wiki-fix MSG="..."`.

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
13 of the SQL catalog's 37 tables arrive in `db/migrations/`, and `_verify_sql_catalog` raises
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
make match [ORG=slug]    # save a Funder Match run for every org, or one (no model, no cost)
make smoke               # end-to-end check of backend + frontend + chat wire
                         # SMOKE_SKIP_LLM=1 make smoke  → skips the one real agent call
make migrate             # apply db/migrations/*.sql   (make migrate-status to inspect)
make psql                # interactive shell against whichever DB ENV selects
make wiki-update         # refresh openwiki/ pages whose source changed (no model call when none did)
make wiki-fix MSG="..."  # have OpenWiki correct a wrong page; never hand-edit openwiki/
make wiki                # regenerate openwiki/ from scratch (~20 min, COSTS MONEY)
make wiki-deploy         # publish openwiki/ to https://sangam-wiki.vercel.app (by hand, like the app)
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
make evals TAG=import               # Import canaries, only by tag: one funder, one NGO, ~15 min (needs TAVILY_API_KEY)
make evals TAG=cost                 # cases with call budgets (Better Life Foundation, ~$0.90 a run)
make evals K=org-count              # one case, by pytest -k
```

`asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio`. **Unit tests never
touch a database**: `client_for(*routers)` builds a router-only FastAPI app with no lifespan
(no pool, no agent, no model) and overrides three dependencies — `get_current_user`, `get_principal`
(the dev user), and `get_pool` with a `_SentinelPool` that raises on any attribute access. Routers take the pool
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

With Langfuse keys set, the selected cases run **once**, as a dataset experiment on `ask-golden`
(`tests/evals/experiment.py`), under environment `eval` and named `branch-sha`, so two runs compare
side by side in Langfuse with their cost. `golden.jsonl` stays the source of truth; the dataset is a copy.
A case's `max_calls` / `max_large_result_reads` fail it; its token counts are only reported.

Running the migration runner outside Docker needs `MIGRATIONS_DIR` — it defaults to the
container path `/srv/db/migrations`.

**CI** (`.github/workflows/ci.yml`) runs all of the above on every PR, plus the integration tier against a
fresh pgvector Postgres, and uploads both coverage reports to Codecov. `codecov.yml` fails a PR that lowers total
coverage by more than 1% or covers under 70% of the lines it changes.

Frontend: `npm run lint` (ESLint, flat config in `frontend/eslint.config.mjs`), `npm test`
(`node --test` over `frontend/tests/*.test.ts`, pure modules only, no runner dependency) and
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
                          │                 search_graph · compare_fit
                          ▼
              Postgres + pgvector        Neo4j (optional)
```

### Layout

```
backend/app/
  main.py          create_app() + `app = create_app()` — the ASGI entrypoint, wiring only
  core/            config.py (Settings) · security.py (Supabase JWT) · lifespan.py · logging.py · egress.py
  db/              pool.py (PoolDep) · checkpointer.py (LangGraph) · migrate.py (runner)
  api/             router.py (the one aggregate router) · deps.py · routes/<resource>.py
  repositories/    hand-written SQL, one module per resource
  schemas/         Pydantic, one module per resource
  agent/           build.py (builds the deep agent) · models.py · tools/
                   instructions.md (the system prompt) · prompt.py (loads it)
  ingest/          agent.py (builds Sangam Import) · instructions.md · skills/
                   tools/ every tool it has, and nothing else in ingest/ is one
                   the rest is the pipeline: runner · writer · promote · matcher
  matching/        Funder Match: rubric · rules · match (pure) · service (a saved run) · run (make match)
  integrations/    graphiti.py (Neo4j client lifecycle) · tracing.py (Langfuse) · storage.py (Supabase Storage)

frontend/
  app/             routes ONLY — pages, layouts, route handlers
  features/        one folder per screen: ask/ auth/ home/ ingest/ registry/ resources/ settings/ taxonomy/ terms/
  components/      ui/ (display primitives) · layout/ (site chrome)
  lib/             api/ (client, types, auth headers) · supabase/ · AgentProviders · useAgentChat · format.ts
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
`app/api/router.py`. (Registry profiles read one typed result per page from
`repositories/profile_facts.py`, which shares its public-read SQL pieces with the Registry list in
`repositories/public_sql.py`: private links are dropped there, in SQL.) Nothing else: `main.py` includes that one aggregate router, and the
tests' pool override is dependency-based, so neither needs editing.

Routers take the pool as `pool: PoolDep` (from `app/db/pool.py`) rather than calling
`get_pool()` in the body — that is what makes it overridable per-app. Agent tools, which run
outside any request, still call `get_pool()` directly; Ask Sangam's SQL executor then sets the
caller itself (below).

**Only one file is called `graph`**: `app/agent/tools/graph_tools.py`, the `search_graph` agent
tool. The deep agent is built in `app/agent/build.py`, and the Graphiti/Neo4j client lifecycle
(`open_graph`, `graph_status`, `client`) lives in `app/integrations/graphiti.py`. Both used to
be called `graph.py` too, which made tracebacks ambiguous.

**`deepagents` is LangGraph, not an alternative to it.** `create_deep_agent()` is a preset
middleware stack over `langchain.agents.create_agent` and returns a compiled LangGraph
graph — which is exactly what `AsyncPostgresSaver` checkpointing and the AG-UI agent
require. Dropping `deepagents` would not drop LangGraph.

**The agents are built on the first chat turn, not at boot.** Most cold starts on Vercel serve a
REST call, and two-thirds of the import time was the agent stack. So `lifespan.py` opens the pool,
checks the catalog and opens the checkpointer, and `load_agents()` imports and builds both agents,
once, under a lock, when `/agent` or `/ingest` is first posted to. Those two routes are our own
(`_add_agent_route`) because `add_langgraph_fastapi_endpoint` needs a built agent to register. A
route that needs a graph calls `get_graph(app, "ask_graph" | "ingest_graph")`; a REST module that
imports agent code at the top undoes this, so `routes/` imports it inside the function that uses it.

**The agent has exactly six tools, and there is ONE open path to the database.**
`app/agent/build.py` registers `db_list_tables`, `db_describe_table`, `db_profile_column`,
`db_query`, `search_graph` and `compare_fit`. Nothing else, and no subagent, so there
is no `task` tool. `compare_fit` is the one exception to "the model writes its own SELECT": funder
matching is a fixed checklist, so its queries are fixed too (`app/repositories/matching.py`, in a
read-only transaction with the same `statement_timeout`).

**Funder matching is judged in code, not by a model.** `compare_fit(org_id, funder_ids=None)` loads
an `OrgProfile` and `FunderProfile`s with fixed SQL (`repositories/matching.py`), and
`app/matching/rules.py` — pure, no I/O — judges the seven criteria of the **match-v2** rubric
(`app/matching/rubric.py`): theme 25, geography 15, population 15, eligibility 20, relationship 10,
funding size 10, capacity 5. Theme compares the `/resources/taxonomy` tree, not Darpan's `sector`
tags: a tag brings its ancestors and a sub-theme its Schedule VII clauses, and the finest grain both
sides share scores (theme 25, clause 15, domain 10). A criterion's status (met / partial / fail / unknown) is computed from
its points, an unknown one is left out of the score rather than counted as zero, and a funder
sharing no place or theme gets a NULL score. `app/matching/match.py` builds the card lines, summary and
"what would raise the score" from templates. Changing a rule is `rules.py`; changing a point value
or a tier is `rubric.py`. The shape follows the Funder Match spec (`features-plans/funder-match/` on `docs/funder-match-spec`),
and a saved run stores `match()` as it is. Design:
`docs/features/2026-10-10-funder-matching-match-v1.md`, and the theme change in
`docs/features/2026-10-11-funder-match-v2-themes.md`. Two model-judged versions came before it —
a `funder-assessor` subagent per pair, then `org-readiness` once plus assessors — and were removed
for running ~35 open-ended queries per subagent.

**A saved run is written by the people responsible for the org.** `POST /api/funder-matches/runs?org=`
and `make match` both call `app/matching/service.py::run_and_save`: it reads as the owner, so every
runner judges the same inputs, and writes every funder's row in one transaction as the writer. The route
writes as the caller, and `0042_funder_matches`' RLS lets only staff and the org's stewards and admins
insert (`app.my_match_org_ids()`), with `run_by` their own id; members read. No role may update or delete
a run. `compare_fit` refuses in chat for anyone else, by the same rule. Design:
`docs/features/2026-10-10-funder-match-saved-runs.md`.

That sentence was false for a while and `app/agent/harness.py` is what makes it true again.
`create_deep_agent` adds eight filesystem tools of its own — including `write_file`, `delete`
and `execute` — and, whenever any subagent is declared, a `general-purpose` subagent carrying
**the main agent's entire tool list** under deepagents' generic prompt. Ask Sangam was running
fifteen tools; Sangam Import twenty-one, with a subagent that could call `run_import_now` and
`promote_research` under none of its instructions. `app/agent/harness.py` removes both, by
two different mechanisms, and the difference matters: a `HarnessProfile` is registered per
**provider**, so it is global to every agent sharing a model — right for the subagent, wrong for
tools, since both supervisors need `ls` to find a skill and no subagent may hold it. So
`install()` disables the subagent globally, and `filesystem(backend, keep=...)` replaces the
preset's `FilesystemMiddleware` **per agent**. Ask Sangam ends at its six plus
`read_file` and `ls`; a subagent keeps only `read_file`, which `FilesystemMiddleware` refuses to
be built without. Nothing that writes survives on any of them. A third deep agent, the news verifier
(`app/ingest/news/verify.py`, `RESEARCH_MODEL`), runs inside a news pull with `read_page`,
`search_public_sources` and that `read_file` floor; it is off until `NEWS_VERIFY_MAX` is above 0.

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

`app/agent/tools/mcp.py` (GitHub and Playwright MCP servers) is complete but imported nowhere, and
the `Settings` fields that feed it — `github_pat`, `github_mcp_url`, `playwright_mcp_url`,
`mcp_servers` — therefore do nothing. `web.make_web_search` (Tavily) is not an Ask tool, but Sangam
Import's `search_public_sources` and the news pipeline use it, so `tavily_api_key` matters.

**The SQL tools let the model write its own SELECT, behind four layers.** Full design in
`docs/SQL_AGENT.md`; the parts you need before touching them:

- `app/agent/tools/sql/catalog.py` is the **allowlist, as data** — 37 tables, and a column not
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
  **The app connects as the database owner, a superuser, but the chat's queries run as the
  caller.** `ask_access` (`core/security.py`) puts the caller's role and JWT claims in
  `agent_caller` (`db/pool.py`) on every `/agent` request — declared per route in
  `AGENT_ACCESS` (`core/lifespan.py`), so a new agent route with none fails at boot — and the executor `set_config`s them
  after `SET TRANSACTION READ ONLY`, as `CallerPool` does for REST — so RLS applies, and the server
  itself refuses the checkpoint tables and `pg_read_file`. With no caller it runs as `anon`, never
  the owner. Every catalog column must be SELECT-able by `authenticated` (`test_agent_rls.py`), or
  `SELECT *` breaks. `compare_fit` and Sangam Import still read as the owner, by design.

`SQL_AUDIT_MODEL` turns on a post-answer audit (`app/agent/audit.py`): a cheap second model
checks grain, missing filters, false zeros and whether the figures in the prose match the rows,
then appends a caveat. It never blocks and never edits — by the time it runs the answer has
already streamed. On by default, on the cheap tier; `SQL_AUDIT_MODEL=off` turns it off.

Adding a table to the catalog is a **security decision**, not bookkeeping: a new table is
invisible to the agent until someone puts it there, and boot logs any live table that is
neither catalogued nor in `KNOWN_EXCLUDED`.

**Sangam Pitch is the proposal agent's name on screen.** The route stays `/proposal`, threads stay
`proposal-<id>-<user>`, and the backend and code keep "proposal". Each editor has their own private chat with it.

**Sangam Scout is Sangam Import's name on screen.** The route stays `/import`, threads stay
`import-<uuid>`, and the backend, endpoint and prompts keep "ingest"/"Import". Scout is one chat
thread like Ask: task cards over the composer, sources ticked in the right rail before the first
message (they answer `choose_sources`, so no card asks mid-run), then every turn inline.

## Conventions

**Schema changes go in `db/migrations/*.sql`, never in `db/init/02_schema.sql`.** The
baseline is what a brand-new database gets; migrations carry everything after it. See
`db/migrations/README.md`. `0001_`–`0010_` carry the v3 data model on top of the v2 baseline:
provenance columns, the taxonomy, geography, identity, credentials, funder activity, org facts,
proposals and signals. They are purely additive — 23 tables gain columns, 14 are new, nothing is
dropped — so a fresh database is `db/init/02_schema.sql` plus `make migrate`. `0011_`–`0047_`
continue on top (48 files; two are numbered `0044`, both kept because the runner keys on the file
name). Which PR added each one, and what it did, is in `docs/CHANGELOG.md`; the tables they leave are in
`docs/ARCHITECTURE.md` §7. The design and the before/after are in `docs/DATA_PLATFORM.md`.

**Every fetch of a model-supplied URL goes through `guarded_client` (`app/core/egress.py`)**, which refuses
private, loopback and metadata addresses on every redirect hop. TLS is always verified,
against certifi plus `app/core/certs/intermediates.pem`: a site that omits its intermediate gets that one certificate
added there, never `verify=False`; an expired or mismatched certificate (nrlm.gov.in, rchiips.org) stays refused.

**Agent tools never raise, and every row they return is cited.** Two conventions that the
product depends on and that a new tool silently breaks:

- *Errors are return values.* A raised exception aborts the entire agent run; a returned
  error string lets the model see the failure and adapt. Every tool body in `app/agent/tools/` is
  wrapped in `try/except` returning `f"<tool> failed: {exc}"`. `tool_errors()` (`ToolErrorMiddleware`, on every agent and
  subagent) is the backstop for one that forgets: it returns the exception's type, never its message.
- *Every database and graph row carries a citation marker* — `[org:N]`, `[funder:N]`,
  `[activity:N]`, `[score:N]`, `[news:N]`, `[graph:<uuid8>]` — because `app/agent/instructions.md` requires the
  model to repeat it inline next to each fact. A tool that returns uncited rows produces
  uncitable answers. Ask has no web tool: `fetch_url` was removed so a page it read could not steer
  `db_query` rows out to a URL.

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

**List pages share one pattern** (`frontend/components/ui/ListPage.tsx`): `BucketCards` (lean cards,
one always selected, dark sage), one `FilterRow` of dropdowns (dark sage once moved off their default),
a `SearchBox`, and `ListMore`/`useShowMore` for a list that grows as you scroll. Funder Match,
Proposals and Media & Signals use them; a new list page does too rather than its own pills or stats.

**Icons come from Lucide (`lucide-react`); never draw an SVG by hand.** Size, stroke and colour
are set by the `.icon` classes in `globals.css`, never as props: one stroke weight everywhere,
and the colour follows the surrounding text. Text-like marks stay as glyphs (⟨ ⟩ ✓ → ⌘↵), as
the design system's iconography page says.

**Provenance columns on every scraped or extracted table**: `source_url`, `source_name`,
`fetched_at`, `content_hash`, `extractor_version`. Populate them — the product promise is
that every field traces to a source.

**A tool of either agent lives under a `tools/` package, and nothing else does.**
`app/agent/tools/` for Ask Sangam, `app/ingest/tools/` for Sangam Import — five modules
there, split by what the tool touches: `pipeline_tools.py` (the adapter path),
`catalog_tools.py` (what Sangam already holds), `research_tools.py` (the open web),
`library_tools.py` (public documents Sangam archived), `vault_tools.py` (an org's Doc Vault).
Both agents register their list in one place — `build.py` and `agent.py` respectively — and
a test walks the package to prove every tool defined is also registered.

**Sangam Import has one human-in-the-loop step before it reads anything: `choose_sources`.**
It is in `INTERRUPT_ON` in `app/ingest/agent.py`, which `create_deep_agent(interrupt_on=…)` turns
into LangChain's `HumanInTheLoopMiddleware`; the Import screen answers with CopilotKit's
`useInterrupt` (`SourcesCard`: public websites, Sangam's library, Doc Vault files, and for staff the
team spreadsheets) and resumes with `{decisions: [...]}`. The answer stays in the checkpoint as the
tool call's arguments, no table. `ChosenSources` holds every subagent until it exists, and
`RunSources` (`app/ingest/middleware.py`) refuses any read outside it. A picked spreadsheet becomes
a `documents` row, so no script is needed; `make staff-source` still writes the same row. The
supervisor never reads rows: when a request is about everyone in a file, the `workbook-reader`
subagent (one tool, `read_workbook`) returns the names, and a researcher per name follows.

**Models come in tiers, by how hard the work is** (`app/core/config.py`). `MODEL` (Opus 5.5)
reasons: Ask Sangam and the Import supervisor, where one wrong join or merge is the costliest
mistake and the model runs once per turn. `RESEARCH_MODEL` (Sonnet 5.5) runs the
`entity-researcher`s: they read long pages, up to `MAX_PARALLEL_RESEARCH` at once, so they are
most of an import's tokens, and judging evidence still needs a capable model. The `vault-reader`, which reads an org's own Doc Vault files with no web tools, runs on it too. `UTILITY_MODEL`
(Haiku 4.5) does work with a fixed shape — article extraction, the `catalog-writer`, the
`workbook-reader` — and `SQL_AUDIT_MODEL` (Haiku 4.5) the post-answer audit. A blank or unset
model variable means the default in `config.py`, the only place defaults are written; `SQL_AUDIT_MODEL=off`
disables the audit. A deployed backend reads these from its
Vercel env, which beats the code defaults.

**Import's middleware** (`app/ingest/middleware.py`). Each tier falls back to the next one when a call
fails. A researcher has no page, model-call or page-length limit by default: a long page is evicted to a
file it pages back. `RESEARCH_PAGE_LIMIT` and `RESEARCH_MODEL_CALL_LIMIT`, when set, cap pages read (then
it saves what it has) and model calls; Vercel's 1800 s is the stop that always applies.
Once a `save_research` call is refused for a malformed payload, the rest of that run moves to `MODEL`.
A Haiku grader checks the save and summary against `prompts/research_rubric.md` and allows one revision.
Summaries of long runs are written by `UTILITY_MODEL` at the same thresholds as before.

**How many organisations Import researches at once is a setting, not a number in the
prompt.** `MAX_PARALLEL_RESEARCH` (default 8) bounds one *wave*, never the size of the list:
above it the agent researches in waves until every organisation asked for is done.
`app/ingest/instructions.md` carries a `{{MAX_PARALLEL_RESEARCH}}` placeholder —
one of two substitutions an agent prompt gets (the other is Ask's `{{TABLE_MAP}}`, the catalog's table list; Media & Signals' classifier prompts, `app/ingest/news/prompts/`, take their subject and the Registry names the same way) — because a number frozen in prose made the
setting decorative. A SKILL.md is read raw from disk and never substituted, so no skill names a
wave size. It is a plain `.replace()`, not `.format()`: the file is full of literal
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
groups split by entity kind because the kinds genuinely differ; the record, the mapping and the report do not. **The pull pair is the researcher's contract**: they live under
`skills/research/`, which `entity-researcher` declares and the supervisor's listing skips (that folder holds no
`SKILL.md` itself). It reads the one for its kind with `read_file`, and `save_research` refuses a save that
leaves a field with neither a finding nor a gap (`app/ingest/contract.py`). The other five are the supervisor's. Constraints never live there: progressive disclosure
means the model chooses whether to load, and the money-unit rule, the entity-confirmation step and
the access rules cannot be optional. `docs/SKILLS.md` has the mechanism, the discovery rules and
the honest cost.

**Ask Sangam loads its matching procedures the same way**, from `app/agent/skills/`:
`funder-matching` (resolve the organisation → one `compare_fit` over the catalog),
`funder-comparison` (named funders → one `compare_fit` with their ids), `funder-shortlist-brief`
(the write-up), and `news-brief` (what changed in the news for one org or funder, cited `[news:N]`). The rules they lean on — compare_fit judges, call it once, an unknown is "not
recorded" — stay in `instructions.md`, rules 12–16.

**Optional subsystems degrade, they do not crash.** The graph activates only when
`NEO4J_URI` and an OpenAI key are both set (`Settings.graph_enabled`); `graphiti_core` is
imported lazily inside `open_graph()` so the app boots without it, and `search_graph`
returns a message telling the agent to use the database tools instead. Langfuse follows
the same pattern. Preserve this when adding integrations.

**Tracing config lives in `app/integrations/tracing.py`** (Langfuse SDK v4), and several of its
settings are load-bearing in ways the Langfuse docs do not advertise:

- **FastAPI's own OTel spans are off** (`telemetry={"tracing": False}` in `main.py`). Langfuse drops
  them, but as parents they left `sangam_ask` a non-root, so the trace had no input or output.
- The trace's name, input and output come from the root chain: `langfuse_trace_name` in
  `trace_config`'s metadata, and `root_input`/`root_output` reduce the graph state to the question
  and the answer. (v3's `update_trace=True` no longer exists.)
- With LangSmith on, an LLM's parent run is a LangSmith-only middleware run Langfuse never sees;
  the handler maps it back through `langgraph_checkpoint_ns` to its graph node. SQL retriever spans
  and the `answer_audit` score find their parent with `current_observation()`, since v4 puts
  nothing on the OTel context.
- `export_span` drops the middleware hooks that record nothing; add a hook there only once a
  trace shows it empty.
- `SessionScopedAGUIAgent.run` flushes after every run: on Vercel the function freezes once it
  has answered, and unflushed spans are lost.
- The handler groups turns by `metadata.langfuse_session_id` and **ignores LangGraph's
  `thread_id` entirely**. `SessionScopedAGUIAgent` overrides `prepare_stream` — the one hook
  that sees both the per-request `RunAgentInput` and the graph's config — to map one onto
  the other. Without it a six-turn conversation is six unrelated traces.

`LANGFUSE_TRACING_ENVIRONMENT` separates local traces from deployed ones; unset, it falls back to
`VERCEL_ENV`, and `release` to `VERCEL_GIT_COMMIT_SHA`.

**Auth verifies Supabase tokens, and `SUPABASE_URL` turns it on.** `backend/app/core/security.py::get_principal`
checks the access token against the project's JWKS and finds or creates the `users` row for it;
no header is anonymous. With `SUPABASE_URL` empty every request is the seeded dev user, and
`DEV_AUTH=1` accepts `Bearer dev` locally — which `make smoke` sends, so it needs that set.
`require_user`/`require_principal` (401) gate saving, editing, Funder Match, news and chat, and a chat someone else owns is 404 to post in, staff included (they read it over REST). Import (Scout) is for
staff and stewards only (`require_scout`, on the `/ingest` agent route and every `/api/ingest` route): its tools run on the owner pool, so they check `chat_scope` themselves
(`app/ingest/caller.py`), and its pipeline routes keep `require_staff` (403). The frontend sends the token from `lib/api/auth-headers.ts` (browser)
and `auth-headers.server.ts` (server components). REST routes already run as the caller under RLS
(`PoolDep` sets the role and JWT claims per transaction); agent tools, Import and the matching reader
still use the owner pool. The plan is `features-plans/access/auth-plan.md`; its Phase 2 (email-domain
matching, join requests) is not built.

## Deployment

Docker is local development only. Deployed, the stack splits across three hosts:

| Piece | Runs on |
|---|---|
| Next.js frontend | Vercel project `sangam` (root directory `frontend`) |
| FastAPI backend | Vercel project `sangam-backend` (root `backend`, framework preset `fastapi`) |
| Postgres | Supabase (ap-south-1, Mumbai) |
| Neo4j | Neo4j Aura, or omitted |

**Both functions run in `bom1` (Mumbai), beside the database** — `"regions"` in each
`vercel.json`. Left at Vercel's default `iad1`, every Postgres round trip crossed iad1↔Mumbai
(~200 ms), and a 2 ms query cost ~1.2 s once BEGIN, `set_config` and COMMIT were counted.
`curl -sI <backend>/health` should show `x-vercel-id: bom1::bom1`.

Both also run for up to **1800 s**: `functions` in `backend/vercel.json` and `maxDuration` in the
copilotkit route, which every Import turn streams through, so the two must match. An 8-organisation
Import takes 15–20 min, and 1800 s needs Pro's extended-duration beta.

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

<!-- OPENWIKI:START -->

## OpenWiki

@AGENTS.md

<!-- OPENWIKI:END -->
