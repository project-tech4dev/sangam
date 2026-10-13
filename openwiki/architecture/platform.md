---
type: architecture overview
title: Platform
description: How the Sangam FastAPI backend is assembled and run. Covers the app factory and routers, Settings and the model tiers, the lifespan with lazy agent loading, Langfuse tracing, the Vercel deploy topology, the performance work behind it, and known regressions.
tags: [platform, fastapi, settings, model-tiers, lifespan, langfuse, tracing, vercel, performance]
sources:
  - id: openwiki-source-d1e8740dfb3dd3dd2e214ddc
    resource: repo://backend/app/agent/build.py
  - id: openwiki-source-959bf3d4c031baf336a996e1
    resource: repo://backend/app/agent/tools/mcp.py
  - id: openwiki-source-aa9356f87b17ea5669cdcc72
    resource: repo://backend/app/api/router.py
  - id: openwiki-source-11c734346bddf773fd80ed0e
    resource: repo://backend/app/api/routes/ingest.py
  - id: openwiki-source-424eb6e9128a678a28e6d5ca
    resource: repo://backend/app/api/routes/threads.py
  - id: openwiki-source-df5be7b214c1649f540daf09
    resource: repo://backend/app/core/CLAUDE.md
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-933c62fa2383d76225c96eb5
    resource: repo://backend/app/core/egress.py
  - id: openwiki-source-e136029ec7d24feaceb8ce72
    resource: repo://backend/app/core/lifespan.py
  - id: openwiki-source-b52886aad1fc413e4e030f22
    resource: repo://backend/app/core/security.py
  - id: openwiki-source-51ead927cc43f35e220ea627
    resource: repo://backend/app/db/checkpointer.py
  - id: openwiki-source-10e08c1deca7d7728d8240c4
    resource: repo://backend/app/db/pool.py
  - id: openwiki-source-62958d5b14b0717233a7ec0b
    resource: repo://backend/app/ingest/agent.py
  - id: openwiki-source-d5862b7945cd467ce8723c8d
    resource: repo://backend/app/ingest/news/pipeline.py
  - id: openwiki-source-d1c2c2d698ef77e881e1ff17
    resource: repo://backend/app/ingest/news/verify.py
  - id: openwiki-source-77f44179d2b1ede3192f7afe
    resource: repo://backend/app/integrations/tracing.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-8aa878aa91baef3db9c28dbe
    resource: repo://backend/tests/test_tracing.py
  - id: openwiki-source-26b852c215c1dc4649cbde36
    resource: repo://backend/vercel.json
  - id: openwiki-source-88fdf568b0f25b1d21f041da
    resource: repo://docs/CHANGELOG.md
  - id: openwiki-source-347b4d4918c606dd60546748
    resource: repo://docs/features/2026-10-09-model-tiers.md
  - id: openwiki-source-bdac7cc8453a568bc132cac3
    resource: repo://docs/features/2026-10-10-page-load-performance.md
  - id: openwiki-source-a0ebc66d448ae6aa5723800b
    resource: repo://frontend/vercel.json
generated: { by: "openwiki/0.7.2", at: "2026-10-13T18:20:59.385Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-10-13T18:59:48.420Z
---

# Platform

The platform is the cross-cutting backend layer that every feature runs on. It does not own any one feature's behaviour. It owns:

- how the ASGI app is built;
- where configuration and defaults live;
- what happens at boot and shutdown;
- when the two agents are constructed;
- how runs are traced;
- how the backend is deployed.

The agents themselves are covered in [Ask Sangam](ask-sangam.md) and [Sangam Import](sangam-import-scout.md). Identity and row-level security are covered in [Auth, roles and RLS](auth-roles-rls.md). Vendor setup is in [Deploy and vendors](../operations/deploy-and-vendors.md), [Environments](../operations/environments.md) and [Deploying by hand](../workflows/deploying-by-hand.md).

## App factory and routers

`backend/app/main.py` exposes `app = create_app()`, the ASGI entrypoint (`app.main:app`). `create_app(settings=None)` takes optional settings so tests can build a variant. It does the following:

- **Logging and docs.** It configures logging and creates `FastAPI(title="Sangam API")` with the lifespan from `build_lifespan(settings)` and the `OPENAPI_TAGS` ordering. FastAPI's own OpenTelemetry tracing is disabled with `telemetry={"tracing": False}`. Langfuse drops HTTP spans, but as parents they would leave each agent run without a trace root.
- **Middleware order.** `AuthMiddleware` is added first and `CORSMiddleware` second, so CORS wraps auth. Preflights are answered before auth runs, and auth's 401s still carry CORS headers. The allowed origins come from `Settings.origins` (comma-separated `allowed_origins`). `allowed_origin_regex` admits Vercel preview hostnames and is passed as `None` when blank, because an empty pattern would match every origin.
- **Routes and error handling.** It mounts `api_router`, maps a Postgres `InsufficientPrivilege` error to `403 {"detail": "Not allowed"}`, and defines `GET /health`.

`AuthMiddleware` is plain ASGI, not `BaseHTTPMiddleware`, because buffering would break chat streaming. It skips non-HTTP scopes and the open paths `/health`, `/docs`, `/docs/oauth2-redirect`, `/redoc` and `/openapi.json` (`_OPEN_PATHS` in `core/security.py`). For every other request it resolves the caller once and stores the role (`anon` or `authenticated`) and claims on the request state. `PoolDep` then runs the request's queries as that caller (see [Auth, roles and RLS](auth-roles-rls.md)).

`backend/app/api/router.py` is the single mount point. It builds one `APIRouter(prefix="/api")` and includes the per-resource routers: orgs, org_members, funders, profiles, funder_matches, partner_lines, programs, rfps, contacts, scores, meta, news_stories, documents, ingest, news_runs, me and threads. `OPENAPI_TAGS` fixes the order resources appear in the docs. Two routes are not under `/api`: `/health` from the factory, and the AG-UI chat routes `/agent` and `/ingest` that the lifespan registers.

## Settings and model tiers

`backend/app/core/config.py` defines a pydantic-settings `Settings` class loaded from the environment and `.env` (unknown keys ignored). `get_settings()` is `lru_cache`d. It is the only place defaults are written.

**Blank means default.** A `mode="before"` validator turns an empty or whitespace string into the field's declared default for the four model settings and for `max_parallel_research`, `research_page_limit`, `research_model_call_limit` and `db_pool_max_size`. docker-compose forwards `${VAR:-}` as `""`, and a hand-edited `.env` line with nothing after `=` does the same. Without the validator an int field would refuse to parse and the container would not boot. `DEV_AUTH=""` is likewise read as off.

### Model tiers

There are three work tiers plus an audit model. Each is a `provider:model_name` spec resolved through LangChain's `init_chat_model`.

| Tier | Setting | Default | Used by |
|---|---|---|---|
| Strong | `MODEL` | `anthropic:claude-opus-5-5` | Ask Sangam's main agent (`agent/build.py`) and the Import supervisor (`ingest/agent.py`). It is also the last fallback for every subagent and the model the researcher escalates to. |
| Research | `RESEARCH_MODEL` | `anthropic:claude-sonnet-5-5` | The `entity-researcher` and `vault-reader` subagents, the news pipeline's grouping model, and the optional news verifier. Researchers run up to `MAX_PARALLEL_RESEARCH` at once, so this tier carries most of an import's tokens. |
| Utility | `UTILITY_MODEL` | `anthropic:claude-haiku-4-5` | The `catalog-writer` and `workbook-reader` subagents, the research rubric and cheap summarizer, `run_import_now` extraction, `live_status`, and the news classifiers and headlines. |
| Audit | `SQL_AUDIT_MODEL` | `anthropic:claude-haiku-4-5` | Ask's post-answer SQL audit, added as `answer_audit(...)` middleware only when the value is non-empty. |

Details that matter when changing these:

- Ask and the Import supervisor share `MODEL`. There is no separate Ask model, and the plan in `docs/features/2026-10-09-model-tiers.md` lists extended-thinking budgets as out of scope.
- `SQL_AUDIT_MODEL=off` is normalised to an empty string, which disables the audit. It costs one extra model call per SQL turn, which is why it sits on the cheapest tier.
- To run a tier on the main model, set it to the same spec as `MODEL`. The researcher's escalate-after-failed-save middleware is only added when `research_spec != settings.model`.
- Subagents fall back down or up the tiers through `fallback(...)` middleware. For example the writer falls back from utility to research to strong.
- Deployed backends read their Vercel environment, and that beats the code defaults. Set or clear the four model variables on `sangam-backend` before deploying (see the [Deploy and vendors](../operations/deploy-and-vendors.md) page).

### Other settings that shape the platform

- **Database.** `database_url` holds both app data and LangGraph checkpoints. `db_pool_max_size` defaults to 10, sized for a Supabase project with 60 connections minus reserved ones across several deployed instances. `db_gate_slots` is `max(2, pool - 3)`. Concurrency gates sit under the pool, because the checkpointer writes on every graph step through the same pool and a gate equal to the pool size would starve it.
- **Agent limits.** `recursion_limit` is 200. Every middleware hook is its own graph node, so a single model-and-tool cycle costs several steps, and LangGraph's default of 25 is exceeded by a SQL turn. `max_parallel_research` is 8. `research_page_limit` and `research_model_call_limit` are optional hard stops.
- **Feature switches derived from config.** `auth_enabled` is true when `supabase_url` is set; otherwise every request is the seeded dev user. `storage_enabled` needs both the Supabase URL and the service key. `graph_enabled` needs `neo4j_uri` and an OpenAI key. `langfuse_enabled` needs both Langfuse keys.
- **SQL tool.** `sql_timeout_ms`, `sql_max_rows` and `sql_max_attempts` bound the text-to-SQL tool.
- **News pipeline.** The `news_*` thresholds and costs live here, never in a screen. The verifier is off while `news_verify_max` is 0.
- **Egress guard.** `core/egress.py` has `guarded_client()`. Every outbound request, including each redirect hop, is refused if the host is loopback, private, link-local, internal, or resolves to such an address. A check that cannot decide refuses. It is shared by Import's research tools and Ask's `fetch_url`.

### MCP settings are dead

`github_pat`, `github_mcp_url`, `playwright_mcp_url`, `mcp_servers` and `github_tool_allowlist` are read only by `app/agent/tools/mcp.py`. Nothing under `backend/app` imports that module or calls its `load_mcp_tools`, so setting them has no effect on the running agents. The agent builders in `agent/build.py` and `ingest/agent.py` pass their own `TOOLS` lists. Treat the MCP settings as unwired until something calls `load_mcp_tools`.

## Lifespan and lazy agent loading

`backend/app/core/lifespan.py` owns everything with a startup and shutdown. Boot is deliberately split in two. The lifespan keeps only what REST needs. The agent stack is built later, on first use: the first post to `/agent` or `/ingest`, or the first REST route that calls `get_graph`.

**Boot, in order** (inside one `AsyncExitStack`, so shutdown unwinds in reverse):

1. Create the shared psycopg pool (`make_pool`: min 1, `autocommit`, `prepare_threshold=0`, dict rows), open it, and publish it as `app.db.pool.pool` for REST endpoints and agent tools.
2. Run `_verify_sql_catalog`. If the SQL tool's catalog disagrees with the database, it logs each `SQL catalog drift:` problem and raises `RuntimeError`, so **the app refuses to boot on catalog drift**. Tables that exist but are in neither the catalog nor `KNOWN_EXCLUDED` are only logged at info level. They stay invisible to the agent until someone decides.
3. Open the Graphiti graph, which logs and does nothing when the graph is not configured.
4. Open the Postgres checkpointer (`AsyncPostgresSaver.setup()`, idempotent DDL).
5. Set `app.state.settings`, `checkpointer`, `agents = None` and an `agents_lock`, then register the `/agent` and `/ingest` routes.
6. Log boot timings: process age from `/proc`, connect plus catalog time, total boot, the model, the research concurrency, the pool size and the gate.

On shutdown the lifespan flushes and shuts down Langfuse, but only if tracing is enabled and the agents were actually built. It then clears `db_pool.pool`.

**First use.** Both agents are built together by `load_agents(app)` under `agents_lock`, once, and cached on `app.state.agents`. The trigger is whichever comes first: a post to `/agent` or `/ingest` (the AG-UI route calls `load_agents`), or a REST route that calls `get_graph` (`routes/ingest.py` and `routes/threads.py` do):

1. `configure_langfuse(settings)` runs first. Building the client is what registers the mask, and a handler created earlier would bind to an unmasked client.
2. `build_agent` builds Ask's graph, and `build_ingest_agent` builds Import's.
3. Each graph is wrapped in a `SessionScopedAGUIAgent`. `/agent` is named `sangam_agent`. `/ingest` is named `sangam_ingest` and passes `emit_subagent_events=True`, so each researcher's steps arrive attributed to its run.
4. The Langfuse and LangSmith status is logged. A configured-but-failing backend logs a warning, because a silently disabled tracer looks the same as a working one.

The build is synchronous on purpose, since imports and graph compiles are not safe to move off the event loop. The whole thing is logged as "Agents built on first use".

```mermaid
sequenceDiagram
    participant B as Browser
    participant R as AG-UI route
    participant L as load_agents
    participant T as tracing
    participant G as Agent builders
    B->>R: POST /agent or /ingest
    R->>R: chat_access checks sign-in and thread owner
    R->>L: load_agents(app)
    alt agents already built
        L-->>R: cached agents
    else first request on this instance
        L->>L: take agents_lock
        L->>T: configure_langfuse(settings)
        L->>G: build_agent and build_ingest_agent
        L-->>R: agents stored on app.state
    end
    R->>R: clone the AG-UI agent per request
    R-->>B: StreamingResponse of encoded events
    R->>T: flush_traces after the run
```

Caption: the first chat request on an instance builds both agents under a lock. Later requests reuse them and clone the AG-UI wrapper per request. A REST route that calls `get_graph` triggers the same build when no chat has happened yet.

**The routes.** `_add_agent_route` registers its own `POST` for each path in place of the library's `add_langgraph_fastapi_endpoint`, which needs the built agent at registration time. It keeps `Depends(chat_access)` (signed in, and the thread is new or yours, with staff allowed on any thread, otherwise a 404) and a `GET {path}/health` route that `make smoke` checks. The wrapper is cloned per request because the LangGraph agent keeps per-run state on the instance.

**Invariant for REST code.** No REST module may import agent code at module top level. A REST cold start must not pay for `deepagents`, model clients, `copilotkit` or Langfuse. The existing routes follow this:

- `threads.py` imports `ag_ui_langgraph.utils` inside the function that needs it, since that import takes about 0.5 s.
- `documents.py` and `ingest.py` import agent tool modules and `live_status` lazily.
- `integrations/storage.py` owns `_safe_name` so it does not import the agent's file tools.
- Routes that need a compiled graph call `get_graph(app, "ask_graph" | "ingest_graph")`. It builds the agents if no chat has happened yet, and returns `None` outside a lifespan.

The cost is a trade: the first request that needs an agent on a fresh instance pays the deferred imports and build (about 1.4 s measured locally).

## Tracing with Langfuse

`backend/app/integrations/tracing.py` wires Langfuse (SDK v4) and a few AG-UI behaviours. Telemetry is built never to take the app or a turn down. Failures are logged and the app continues untraced.

**Enabling.** Tracing is on only when both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set. `configure_langfuse` builds the client once with the mask and a span filter, and takes the environment and release from `LANGFUSE_TRACING_ENVIRONMENT` or `VERCEL_ENV`, and `LANGFUSE_RELEASE` or `VERCEL_GIT_COMMIT_SHA`. It then verifies two things that would otherwise fail silently:

- **Mask check.** The client's `_mask` must be `mask_payload`. Langfuse shares resources per public key and the first construction wins, so a client built earlier would leave masking off. On mismatch it logs an error and reports tracing as not live.
- **Credential check.** `auth_check()` must succeed. Wrong keys for the host would otherwise be rejected with a 401 on a background thread that nobody reads, so it logs that traces will be dropped and points at `LANGFUSE_HOST`.

**Trace roots and names.** `trace_config(settings, name, tags)` returns the `run_name` and, when enabled, a Langfuse callback handler plus metadata (`langfuse_trace_name`, and tags `sangam`, the agent's own tags and `settings.model`). The name is set even with tracing off so graphs are not all called "LangGraph". Each graph passes its own name, since a trace's name is all that is shown before opening it:

| Graph | Trace name | Extra tags |
|---|---|---|
| Ask Sangam | `sangam_ask` | `ask` |
| Sangam Import | `sangam_import` | `import`, `research`, the research and utility specs |
| News verifier | `sangam_news_verify` | `news`, `verify`, the research spec |

`TRACE_NAME = "sangam_agent"` is only the default when no name is passed.

**The handler.** A subclass of the SDK's `CallbackHandler` adds the following:

- **Observation types.** The graph and each subagent are typed `agent`. The `answer_audit.after_agent` hook is an `evaluator`. Everything else is a `chain`.
- **Root input and output.** The root input is the last human question, and the root output is the final replies that called no tool. When a turn stopped for approval it appends "Waiting for a person to approve: ...".
- **Parenting.** It re-parents runs whose parent the handler never saw onto the LangGraph node run.
- **Cancellation.** A cancelled turn (browser disconnect) is closed with a "cancelled: client disconnected" message and no error level.

**What is exported.** `export_span` keeps Langfuse's default filter, so FastAPI HTTP spans are dropped, and also drops empty middleware hook spans (`PatchToolCallsMiddleware`, `SkillsMiddleware`, `sql_retry_limiter`, `RunSources` and `DropFilesOnExit`, `before_` or `after_` `agent` or `model`). These never call a model, and unlisted hooks are kept because dropping a parent would orphan its children.

**Masking and clipping.** `mask_payload` runs over every input and output. It always clips strings to `MAX_IO_CHARS` (4,000). When `LANGFUSE_MASK_TOOL_RESULTS` is true, it also redacts warehouse rows. Redaction is shape-aware: it cuts after a `columns: ` header (`db_query`) or an `as stored:` line (`db_profile_column`) and leaves the query, caveats and sources above the cut intact. It is also applied in `on_tool_end`. A failing mask sends the payload unmasked, so a mask bug cannot drop a batch. The tests pin this behaviour, including that bare SQL and prose survive and that nested payloads are masked.

**Sessions, users and SQL spans.**

- `SessionScopedAGUIAgent.prepare_stream` maps the AG-UI `thread_id` to `langfuse_session_id`, the chat user (`chat_user_id`) to `langfuse_user_id`, and the run id to `agui_run_id`. Without the mapping each turn is an orphan trace.
- It de-duplicates tool results the browser re-sends under its own ids.
- It addresses a legacy resume to one open interrupt through `key_resume`, which is needed because parallel Import writers pause together and LangGraph refuses an unaddressed resume.
- `run()` flushes Langfuse in a thread in a `finally`, because a serverless function freezes once it has answered.
- `sql_span` and `traced_fetch` record each SQL statement as a `retriever` observation under the current tool span, with the dedented SQL, its params and the row count. `score_answer` attaches scores such as `answer_audit` to the current turn's trace.

**LangSmith** needs no wiring. `langsmith_status()` only reports at boot whether it is on, off, or misconfigured.

**Recursion limit is carried twice.** `build_agent` binds `recursion_limit` to the graph, and the lifespan also passes it as the AG-UI agent's `config`. AG-UI builds each request's config with `ensure_config`, which stamps LangGraph's default of 25 and overrides the graph-bound value. Removing the `config=` argument in `_build_agents` would silently bring the 25-step cap back. A test pins both the trap and the fix, and the setting stays at least 150.

**Focused tests.** `backend/tests/test_tracing.py` covers:

- run naming with tracing off, and handler binding to the configured client;
- graceful degradation when the SDK is broken;
- session, user and run metadata, and survival of graph-level tags;
- SQL spans, masking and clipping, and cancelled turns;
- the bad-credentials error message;
- recursion-limit propagation;
- `key_resume` and parallel pauses;
- a guard that every documented `LANGSMITH_*`, `LANGFUSE_*` and `SUPABASE_*` variable in `.env.example` is forwarded by `docker-compose.yml`.

## Deploy topology

Two Vercel projects deploy from one repository: the frontend (`sangam`, root `frontend`) and the backend (`sangam-backend`, root `backend`, a FastAPI function). Postgres, Auth and Storage are Supabase in `ap-south-1`. Neo4j is optional.

- **Both `vercel.json` files** set `git.deploymentEnabled: false` and `regions: ["bom1"]`. Nothing deploys on push. A deploy is run by hand from CI, as described in [Deploying by hand](../workflows/deploying-by-hand.md). `bom1` puts both functions next to the database in Mumbai.
- **`backend/vercel.json`** also sets `functions."app/main.py".maxDuration` to 1800 seconds, which long Import and news runs depend on. It also defines a cron on `/health` every five minutes (`*/5 * * * *`). The cron keeps one instance warm and does nothing for several calls arriving at once.
- **Function limit coupling.** The news verifier budget (`news_verify_seconds`, 600) is chosen so a pull still ends inside the 1,800 s function limit. The frontend's chat route must carry the same maximum duration.
- **Local run.** docker-compose forwards the environment to the backend container, and a test guards that forwarding for the tracing and Supabase variables.

## Performance

`docs/features/2026-10-10-page-load-performance.md` records the measurements behind the current shape:

- **Distance was the first cost.** Originally both functions ran in `iad1` against a Mumbai database, and each round trip cost about 200 ms. Moving to `bom1` (#148) took warm `/api/funders` from 1.2 s to 0.2 s.
- **Cold starts dominate.** A cold backend call took 8–12 s, from the runtime dependency install (2–4 s) plus imports, connect and the catalog check. About two-thirds of the import time was the agent stack. This is why agent building moved off the boot path (PR 7, lazy `load_agents`), taking a local `import app.main` from 1.84 s to roughly 0.3–0.4 s.
- **Fewer calls per page.** Profile pages use one aggregate endpoint each (`GET /api/orgs/{slug}/profile`, `GET /api/funders/{slug}/profile`, #179), because a page waits for its slowest call and each parallel call can land on a fresh cold instance. `GET /api/ingest/overview` does the same for the Import page.
- **Caching.** Signed-out reads use Next's data cache (`revalidate: 300`) and signed-in reads stay `no-store`, because RLS decides what they see (#180). The `/health` cron is the keep-warm measure.
- **Not done.** The 2–4 s dependency install remains because `graphiti-core` stays in the bundle (PR 2 was closed). Signed-in pages can still meet a cold start. Loading states and the JS trim are deferred. Check the "Not finished" table in [`docs/CHANGELOG.md`](../../docs/CHANGELOG.md) before assuming the plan doc matches the code.

## Known regressions

- **`emit_raw_events` is back on.** The CopilotKit-removal plan had both `SessionScopedAGUIAgent(...)` calls in `core/lifespan.py` pass `emit_raw_events=False`. With raw events off, one answer went from 1.69 MB to 107 KB (#167–#169). Then #178 removed that argument. The `SessionScopedAGUIAgent` constructor defaults `emit_raw_events=True`, and `_build_agents` passes only `emit_subagent_events=True` for `/ingest`. So every AG-UI event again carries a copy of the LangGraph event it came from, including run metadata such as `langfuse_user_id` and model settings. The plan doc found that no frontend file reads `rawEvent`. The fix is to pass `emit_raw_events=False` for both agents. See the [CHANGELOG "Not finished" table](../../docs/CHANGELOG.md) and the Performance entry for #167–#169.

## Where to change things

- **A new REST resource:** add a router module under `api/routes`, include it in `api/router.py`, add an `OPENAPI_TAGS` entry, and import any agent code inside functions.
- **A new default or model tier:** edit `core/config.py` only, add the field to the blank-means-default validator if it is an int or a model spec, and forward the variable in `docker-compose.yml`. Set it in Vercel for deployed backends.
- **A new agent or trace root:** pass a distinct `name` and tags to `trace_config`, wrap the graph in `SessionScopedAGUIAgent`, and register the path in `AGENT_NAMES` and `_build_agents`.
- **A new table the SQL tool may read:** update the SQL catalog, or the lifespan's catalog check will refuse to boot.
