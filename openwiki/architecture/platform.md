---
type: architecture overview
title: Platform
description: How the Sangam FastAPI backend is assembled, checked and run after the agentkit/ask split. Covers the app factory and routers, Settings and the model tiers, the shared pool and checkpointer, the lifespan with lazy agent loading, Langfuse tracing, the egress guard, the Vercel deploy topology, CI and Codecov, Makefile targets, the performance work behind it (including Ask's tool-result clearing and compare_fit sizing), and known regressions.
tags: [platform, fastapi, settings, model-tiers, lifespan, db-pool, checkpointer, langfuse, tracing, egress, vercel, performance, ci, codecov, makefile, middleware, agentkit]
verified:
  - by: openwiki/0.7.2
    at: 2026-11-05T19:29:31.538Z
sources:
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-cffc175ad16f1cf0f4a9e43f
    resource: repo://.github/workflows/dependency-review.yml
  - id: openwiki-source-6766b7a0c14857435d2077c9
    resource: repo://.github/workflows/deploy.yml
  - id: openwiki-source-510f72ba91d3915e3fb10b24
    resource: repo://backend/app/agentkit/harness.py
  - id: openwiki-source-fe3601d35ecee292c4d2b24d
    resource: repo://backend/app/agentkit/middleware.py
  - id: openwiki-source-cca12af1e5c1e67e98d95ef0
    resource: repo://backend/app/agentkit/models.py
  - id: openwiki-source-aa9356f87b17ea5669cdcc72
    resource: repo://backend/app/api/router.py
  - id: openwiki-source-11c734346bddf773fd80ed0e
    resource: repo://backend/app/api/routes/ingest.py
  - id: openwiki-source-e0103e1ba2cbec5a0f421c56
    resource: repo://backend/app/api/routes/proposals.py
  - id: openwiki-source-424eb6e9128a678a28e6d5ca
    resource: repo://backend/app/api/routes/threads.py
  - id: openwiki-source-319a08aaeaf88078bae3e2e9
    resource: repo://backend/app/ask/agent.py
  - id: openwiki-source-f675a01c36b7a806924914b8
    resource: repo://backend/app/ask/middleware.py
  - id: openwiki-source-cbf2d06ce414c4b575976bab
    resource: repo://backend/app/ask/prompt.py
  - id: openwiki-source-d55b72c3daac4208de6d9806
    resource: repo://backend/app/ask/tools/matching_tools.py
  - id: openwiki-source-ac33fbd2932416f95f8dbbd6
    resource: repo://backend/app/ask/tools/sql/validator.py
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
  - id: openwiki-source-d6ae1b935f35d5f42105acc8
    resource: repo://backend/app/ingest/calls/pull.py
  - id: openwiki-source-7d480e75db10aae51a0f227b
    resource: repo://backend/app/ingest/middleware.py
  - id: openwiki-source-d5862b7945cd467ce8723c8d
    resource: repo://backend/app/ingest/news/pipeline.py
  - id: openwiki-source-d1c2c2d698ef77e881e1ff17
    resource: repo://backend/app/ingest/news/verify.py
  - id: openwiki-source-602238f4e5bb2de7ed53155c
    resource: repo://backend/app/ingest/reading/access.py
  - id: openwiki-source-51e6adf4243b3601b40e5803
    resource: repo://backend/app/ingest/tools/research_tools.py
  - id: openwiki-source-77f44179d2b1ede3192f7afe
    resource: repo://backend/app/integrations/tracing.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-0c2810df96342c5efec98a57
    resource: repo://backend/app/proposals/agent.py
  - id: openwiki-source-9888738c380786cc871715d9
    resource: repo://backend/app/proposals/readers.py
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-8515286617ae84b7b71f0cb9
    resource: repo://backend/tests/test_egress_trust.py
  - id: openwiki-source-8aa878aa91baef3db9c28dbe
    resource: repo://backend/tests/test_tracing.py
  - id: openwiki-source-26b852c215c1dc4649cbde36
    resource: repo://backend/vercel.json
  - id: openwiki-source-a2371d6362e5db4bc834ad03
    resource: repo://CLAUDE.md
  - id: openwiki-source-5f7022cb75865b779a5792a0
    resource: repo://codecov.yml
  - id: openwiki-source-b79fbbd921df689b4bbdc82f
    resource: repo://docker-compose.yml
  - id: openwiki-source-88fdf568b0f25b1d21f041da
    resource: repo://docs/CHANGELOG.md
  - id: openwiki-source-bdac7cc8453a568bc132cac3
    resource: repo://docs/features/2026-10-10-page-load-performance.md
  - id: openwiki-source-e89833baa00bd0952b217a13
    resource: repo://docs/features/2026-10-16-ask-efficiency.md
  - id: openwiki-source-487e1b070f16b33a7aa8a145
    resource: repo://docs/features/2026-10-16-ci.md
  - id: openwiki-source-a0ebc66d448ae6aa5723800b
    resource: repo://frontend/vercel.json
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-11-05T19:29:31.538Z" }
---

# Platform

The platform is the cross-cutting backend layer that every feature runs on. It does not own any one feature's behaviour. It owns:

- how the ASGI app is built;
- where configuration and defaults live;
- what happens at boot and shutdown, and the one database pool;
- when the three agents (Ask, Import, proposal) are constructed;
- how runs are traced and what an outbound fetch may reach;
- how the backend is deployed;
- how every PR is checked (CI, coverage, dependency review), which is separate from deploying.

The agent code is split three ways. `backend/app/agentkit/` holds what every deep agent shares (model resolution, the deepagents harness profile, common middleware). `backend/app/ask/` is Ask Sangam (agent, prompt, SQL tools, `compare_fit`, Ask-only middleware). `backend/app/ingest/` and `backend/app/proposals/` build the Import and proposal agents on top of `agentkit`. The old `backend/app/agent/` package no longer exists.

The agents themselves are covered in [Ask Sangam](ask-sangam.md) and [Sangam Import](sangam-import-scout.md). Identity and row-level security are covered in [Auth, roles and RLS](auth-roles-rls.md). The database schema and migrations are in [Data and migrations](data-and-migrations.md). Vendor setup is in [Deploy and vendors](../operations/deploy-and-vendors.md), [Environments](../operations/environments.md) and [Deploying by hand](../workflows/deploying-by-hand.md). A chat turn end to end is in [Ask turn](../workflows/ask-turn.md).

## App factory and routers

`backend/app/main.py` exposes `app = create_app()`, the ASGI entrypoint (`app.main:app`). `create_app(settings=None)` takes optional settings so tests can build a variant. It does the following:

- **Logging and docs.** It configures logging and creates `FastAPI(title="Sangam API")` with the lifespan from `build_lifespan(settings)` and the `OPENAPI_TAGS` ordering. FastAPI's own OpenTelemetry tracing is disabled with `telemetry={"tracing": False}`. Langfuse drops HTTP spans, but as parents they would leave each agent run without a trace root.
- **Middleware order.** `AuthMiddleware` is added first and `CORSMiddleware` second, so CORS wraps auth. Preflights are answered before auth runs, and auth's 401s still carry CORS headers. The allowed origins come from `Settings.origins` (comma-separated `allowed_origins`). `allowed_origin_regex` admits Vercel preview hostnames and is passed as `None` when blank, because an empty pattern would match every origin.
- **Routes and error handling.** It mounts `api_router`, maps a Postgres `InsufficientPrivilege` error to `403 {"detail": "Not allowed"}`, and defines `GET /health`. `/health` is an open path and returns `{"status": "ok"}` plus pool counts only (`pool_max`, `pool_size`, `pool_available`, `requests_waiting`, `requests_errors`, `connections_errors`), so a reader can see whether requests are queuing for a connection. The counts are empty before the lifespan has published the pool.

`AuthMiddleware` is plain ASGI, not `BaseHTTPMiddleware`, because buffering would break chat streaming. It skips non-HTTP scopes and the open paths `/health`, `/docs`, `/docs/oauth2-redirect`, `/redoc` and `/openapi.json` (`_OPEN_PATHS` in `core/security.py`). For every other request it resolves the caller once (`resolve_principal`: with `SUPABASE_URL` unset everyone is the seeded dev user, except that `DEV_AUTH` also lets `Bearer dev:<email>@local.test` pick a seeded test user; with it set, no header is anonymous, a Supabase token is verified against the project's JWKS, and `Bearer dev` works only when `DEV_AUTH` is on), answers a bad token itself with a JSON 401/409, and stores the principal plus `db_role` (`anon` or `authenticated`) and `db_claims` on the request state.

`get_caller_pool` in `db/pool.py` turns those into a `CallerPool` (anon with empty claims when the middleware did not run), which `PoolDep` hands to routers. Each `connection()` opens a transaction and in one round trip runs `set_config` for `role`, `request.jwt.claims` and `statement_timeout` (`db_statement_timeout_ms`, 15 s by default) with `SET LOCAL` semantics. So RLS applies, the settings end with the transaction even on error, and the connection returns to the shared pool as the owner (see [Auth, roles and RLS](auth-roles-rls.md)). Identity code and agent tools take the owner pool (`OwnerPoolDep`, `get_pool()`). Ask Sangam's SQL reads its caller from the `agent_caller` context variable, and its executor sets its own lower timeout after `set_caller`, which is why the REST timeout is not part of `set_caller`.

`backend/app/api/router.py` is the single mount point. It builds one `APIRouter(prefix="/api")` and includes the per-resource routers: orgs, org_members, funders, profiles, registry, funder_matches, proposals, partner_lines, partner_groups, programs, rfps, contacts, scores, meta, news_stories, documents, ingest, news_runs, me and threads. `OPENAPI_TAGS` fixes the order resources appear in the docs. Routes outside `/api` are `/health` from the factory and the three AG-UI chat routes `/agent`, `/ingest` and `/proposal` (with their `{path}/health`) that the lifespan registers.

## Settings and model tiers

`backend/app/core/config.py` defines a pydantic-settings `Settings` class loaded from the environment and `.env` (unknown keys ignored). `get_settings()` is `lru_cache`d. It is the only place defaults are written.

**Blank means default.** A `mode="before"` validator turns an empty or whitespace string into the field's declared default for the four model settings and for `max_parallel_research`, `research_page_limit`, `research_model_call_limit`, `ask_model_call_limit`, `db_pool_max_size`, `db_pool_timeout_s`, `db_connect_timeout_s` and `db_statement_timeout_ms`. docker-compose forwards `${VAR:-}` as `""`, and a hand-edited `.env` line with nothing after `=` does the same. Without the validator an int field would refuse to parse and the container would not boot. `DEV_AUTH=""` is likewise read as off.

### Model tiers

There are three work tiers plus an audit model. Each is a `provider:model_name` spec resolved by `agentkit/models.py`'s `resolve_model`, which wraps LangChain's `init_chat_model` and accepts the providers `anthropic`, `openai` and `google_genai` (anything else is a `ValueError`).

| Tier | Setting | Default | Used by |
|---|---|---|---|
| Strong | `MODEL` | `anthropic:claude-opus-5-5` | Ask Sangam's main agent (`ask/agent.py`), the Import supervisor (`ingest/agent.py`) and the proposal agent (`proposals/agent.py`). It is also the last fallback for every subagent and the model the researcher escalates to. |
| Research | `RESEARCH_MODEL` | `anthropic:claude-sonnet-5-5` | The `entity-researcher` and `vault-reader` subagents, the news pipeline's grouping model, the optional news verifier, and the proposal reader agents. Researchers run up to `MAX_PARALLEL_RESEARCH` at once, so this tier carries most of an import's tokens. |
| Utility | `UTILITY_MODEL` | `anthropic:claude-haiku-4-5` | The `catalog-writer` and `workbook-reader` subagents, the research rubric and every agent's cheap summarizer, `run_import_now` extraction, `live_status`, the news classifiers and headlines, and the proposal grader. |
| Audit | `SQL_AUDIT_MODEL` | `anthropic:claude-haiku-4-5` | Ask's post-answer SQL audit, added as `answer_audit(...)` middleware only when the value is non-empty. |

Details that matter when changing these:

- Ask, the Import supervisor and the proposal agent share `MODEL`. There is no separate Ask model.
- `SQL_AUDIT_MODEL=off` is normalised to an empty string, which disables the audit. It costs one extra model call per SQL turn, which is why it sits on the cheapest tier.
- To run a tier on the main model, set it to the same spec as `MODEL`. The researcher's escalate-after-failed-save middleware is only added when `research_spec != settings.model`.
- Agents fall back across tiers through `fallback(primary, *candidates)` in `agentkit/middleware.py`, which adds one `ModelFallbackMiddleware` using the first candidate spec that differs from the primary, and nothing when all match. The writer and workbook-reader try research and then strong (so a utility spec equal to the research spec falls through to strong). The researcher and vault-reader fall back from research to `MODEL`. The Import supervisor falls back from strong to research, and so do Ask's agent and the proposal agent (`MODEL` to `RESEARCH_MODEL`).
- Deployed backends read their Vercel environment, and that beats the code defaults. Set or clear the model variables on `sangam-backend` before deploying (see [Deploy and vendors](../operations/deploy-and-vendors.md)).

### The shared harness profile

`agentkit/harness.py` removes what `create_deep_agent` adds by default. `install()` registers a deepagents harness profile for the `anthropic`, `openai`, `google` and `google_genai` providers that disables the `general-purpose` subagent (which would otherwise inherit the supervisor's whole tool list, including the writing ones). `filesystem(...)` returns a `FilesystemMiddleware` that exposes only the tools asked for (`read_file` is the floor the library imposes; both supervisors keep `ls` too, to load skills) and replaces the preset's eight-tool default per agent and per isolated subagent. Every builder calls `install_harness()` before `create_deep_agent`, because the profile is read while the graph is built.

### Shared middleware

`agentkit/middleware.py` holds what every deep agent shares: `tool_errors()` (a tool that raises answers the model with its error type only, never the raw message), `clear_old_tool_results()`, `fallback()` and `cheap_summarizer()` (the agent's own summarization thresholds, with the summary written by the utility model). Ask-only middleware lives in `ask/middleware.py`: `sql_retry_limiter` (5 failed SQL attempts per question), `model_call_cap`, `CompareFitBudget` and `answer_audit`.

### Other settings that shape the platform

- **Database.** `database_url` holds both app data and LangGraph checkpoints. `db_pool_max_size` defaults to 10, sized for a Supabase project with 60 connections minus reserved ones across several deployed instances. `db_gate_slots` is `max(2, pool - 3)`. Concurrency gates sit under the pool, because the checkpointer writes on every graph step through the same pool and a gate equal to the pool size would starve it. `db_pool_timeout_s` (10 s) is how long a request waits for a free connection, `db_connect_timeout_s` (5 s) how long a new one may take to open.
- **Agent limits.** `recursion_limit` is 200. Every middleware hook is its own graph node, so a single model-and-tool cycle costs several steps, and LangGraph's default of 25 is exceeded by a SQL turn. Each subagent gets its own budget of these steps. `ask_model_call_limit` (25, `ASK_MODEL_CALL_LIMIT`) caps the model calls one Ask question may make through `model_call_cap`, which ends a runaway turn long before `recursion_limit`. `max_parallel_research` is 8. `research_page_limit` and `research_model_call_limit` are optional hard stops.
- **Feature switches derived from config.** `auth_enabled` is true when `supabase_url` is set; otherwise every request is the seeded dev user. `storage_enabled` needs both the Supabase URL and the service key. `graph_enabled` needs `neo4j_uri` and an OpenAI key. `langfuse_enabled` needs both Langfuse keys.
- **SQL tool.** `sql_timeout_ms`, `sql_max_rows` and the audit model bound the text-to-SQL tool.
- **News pipeline.** The `news_*` thresholds and costs live here, never in a screen. The verifier is off while `news_verify_max` is 0.
- **No MCP settings.** The old `github_pat`, `mcp_servers` and related settings and the `agent/tools/mcp.py` loader are gone; no agent loads MCP tools.

## One pool, and a checkpointer that does not migrate

`db/checkpointer.py` owns `make_pool`, the one `AsyncConnectionPool` that REST, agent tools and the LangGraph checkpointer all share: `min_size` 1, `max_size` `db_pool_max_size`, `autocommit`, `prepare_threshold=0`, dict rows, the pool timeout above, and `check=AsyncConnectionPool.check_connection` with `max_idle=300`. The health check costs one round trip but covers a thawed Vercel instance holding sockets the pooler has closed.

`open_checkpointer(pool)` no longer runs DDL. It reads `checkpoint_migrations` and raises `RuntimeError("... run make migrate")` when the database is not at the schema version this langgraph expects (`CHECKPOINT_VERSION`), because concurrent cold starts would race on `setup()`. `app.db.migrate` applies the checkpoint migrations (see [Data and migrations](data-and-migrations.md)).

## Egress guard

`core/egress.py` keeps outbound fetches off the internal network. `private_address_refusal(url)` returns a reason (or `None` and never raises) when the URL is not http(s), names `localhost`, is a single-label host, does not resolve, names an address that is not public (loopback, private, link-local, internal, multicast), or when the check itself cannot decide. It also catches numeric host forms such as `2130706433` or `0x7f.1`, and judges IPv6 addresses that embed an IPv4 one (mapped, 6to4, Teredo, NAT64) by the inner address.

`guarded_client()` is an httpx client that runs that check on every request, including each redirect hop, before it is sent, and raises `EgressRefused`. It is used by the robots.txt fetch in `ingest/reading/access.py` and by the RFP call pull (`ingest/calls/pull.py`). The research reader's page and document fetches use their own `_client` in `ingest/tools/research_tools.py`: its request hook runs `check_url` on every hop, which includes `private_address_refusal` plus the registry's access rules and robots.txt, and keeps a read that starts on a path-scoped source on that source's allowed paths. Ask has no fetch tool at all, because `fetch_url` was removed (M4, #247).

**TLS trust.** Both clients verify against `TRUST`, certifi's roots plus `core/certs/intermediates.pem` (intermediates some government sites fail to send). Verification stays on. `tests/test_egress_trust.py` checks that each extra certificate is an intermediate whose root is already trusted and that it stays in date for another year.

## Lifespan and lazy agent loading

`backend/app/core/lifespan.py` owns everything with a startup and shutdown. Boot is deliberately split in two. The lifespan keeps only what REST needs. The agent stack is built later, on first use: the first post to `/agent`, `/ingest` or `/proposal` (each route calls `load_agents`), or the first REST route that calls `get_graph`. The REST callers today are `saved_messages` in `routes/threads.py`, which serves the saved messages of Ask, Import and the proposal chat (`ask_graph`, `ingest_graph`, `proposal_graph`; the Import and proposal routes reuse it), the Import `ask-live` route in `routes/ingest.py` (`ingest_graph`), and the proposals' `start_research` route, which builds the agents because the proposal readers are built together with the proposal agent and no chat may have built them since a restart.

**Boot, in order** (inside one `AsyncExitStack`, so shutdown unwinds in reverse):

1. Create the shared psycopg pool (`make_pool`), open it, and publish it as `app.db.pool.pool` for REST endpoints and agent tools.
2. Run `_verify_sql_catalog`. If the SQL tool's catalog (`ask/tools/sql/catalog.py`) disagrees with the database, it logs each `SQL catalog drift:` problem and raises `RuntimeError`, so **the app refuses to boot on catalog drift**. Tables that exist but are in neither the catalog nor `KNOWN_EXCLUDED` are only logged at info level. They stay invisible to the agent until someone decides.
3. Open the Graphiti graph, which logs and does nothing when the graph is not configured.
4. Open the Postgres checkpointer (a version check, see above).
5. Set `app.state.settings`, `checkpointer`, `agents = None` and an `agents_lock`, then register a route for every path in `AGENT_NAMES`: `/agent`, `/ingest` and `/proposal`.
6. Log boot timings: process age from `/proc`, connect plus catalog time, total boot, the model, the research concurrency, the pool size and the gate.

On shutdown the lifespan flushes and shuts down Langfuse, but only if tracing is enabled and the agents were actually built. It then clears `db_pool.pool`.

**First use.** All three agents are built together by `load_agents(app)` under `agents_lock`, once, and cached on `app.state.agents`. `load_agents` returns `None` outside a lifespan. `_build_agents` does the following:

1. `configure_langfuse(settings)` runs first. Building the client is what registers the mask, and a handler created earlier would bind to an unmasked client.
2. `build_agent` (`ask/agent.py`) builds Ask's graph, `build_ingest_agent` (`ingest/agent.py`) builds Import's and `build_proposal_agent` (`proposals/agent.py`) builds the proposal copilot's, which also builds the proposal file readers (see [Ask Sangam](ask-sangam.md), [Sangam Import](sangam-import-scout.md) and [Proposal Copilot](proposal-copilot.md)).
3. Each graph is wrapped in a `SessionScopedAGUIAgent`. `/agent` is named `sangam_agent`, `/ingest` is `sangam_ingest` and passes `emit_subagent_events=True` so each researcher's steps arrive attributed to its run, and `/proposal` is `sangam_proposal` and passes `emit_raw_events=False`. All three receive `config={"recursion_limit": ...}`.
4. The Langfuse and LangSmith status is logged. A configured-but-failing backend logs a warning, because a silently disabled tracer looks the same as a working one.

The build is synchronous on purpose, since imports and graph compiles are not safe to move off the event loop. The whole thing is logged as "Agents built on first use".

```mermaid
sequenceDiagram
    participant B as Browser
    participant R as AG-UI route
    participant L as load_agents
    participant T as tracing
    participant G as Agent builders
    B->>R: POST /agent, /ingest or /proposal
    R->>R: the path's AGENT_ACCESS checks run
    R->>L: load_agents(app)
    alt agents already built
        L-->>R: cached agents
    else first request on this instance
        L->>L: take agents_lock
        L->>T: configure_langfuse(settings)
        L->>G: build_agent, build_ingest_agent, build_proposal_agent
        L-->>R: agents stored on app.state
    end
    R->>R: clone the AG-UI agent per request
    R-->>B: StreamingResponse of encoded events
    R->>T: flush_traces after the run
```

Caption: the first chat request on an instance builds all three agents under a lock. Later requests reuse them and clone the AG-UI wrapper per request. A REST route that calls `get_graph` triggers the same build when no chat has happened yet.

**The routes.** `_add_agent_route` registers its own `POST` for each path in place of the library's `add_langgraph_fastapi_endpoint`, which needs the built agent at registration time, plus a `GET {path}/health` route that `make smoke` checks. The wrapper is cloned per request because the LangGraph agent keeps per-run state on the instance.

**Per-route chat access.** Who may post is set by `AGENT_ACCESS`, a dict keyed by path. `_add_agent_route` looks the path up directly, so a path missing from it fails at boot instead of falling back to another route's checks. All of them require sign-in (anonymous is 401) and claim the thread in the `threads` table:

| Path | Dependencies | Effect |
|---|---|---|
| `/agent` | `ask_access` | Signed in; the thread is new or yours (someone else's is 404, staff included). Also sets `agent_caller` so Ask's SQL runs as this caller (`anon`/`authenticated`) rather than the owner, and starts a fresh `caveats_given` set for the turn. |
| `/ingest` | `require_scout`, `chat_access` | Staff or a steward of an org (403 otherwise), then the same thread-ownership check. Import keeps the owner pool because it writes the catalog. |
| `/proposal` | `proposal_chat_access` | The thread id must parse as a proposal chat belonging to the caller, on an org the caller can read (else 404); a reader who cannot edit the proposal gets 403. It claims the thread with `use_case="proposal"` and sets `chat_proposal` from the thread, never from the model. |

`_own_thread` and `proposal_chat_access` also set the `chat_user_id` and `chat_scope` context variables (a `CallerScope` of org roles) that the tracing hook and agent tools read; outside a chat request they are unset, which tools treat as no access. A body that fails validation skips the check and is answered by the endpoint's own 422.

**Invariant for REST code.** No REST module may import agent code at module top level. A REST cold start must not pay for `deepagents`, model clients, `copilotkit` or Langfuse. The existing routes follow this:

- `threads.py` imports `ag_ui_langgraph.utils` inside the function that needs it, since that import takes about 0.5 s.
- `ingest.py` imports `live_status` lazily, and `proposals.py` imports `readers` inside the route that needs it.
- `integrations/storage.py` owns `_safe_name` so it does not import the agent's file tools.
- Routes that need a compiled graph call `get_graph(app, "ask_graph" | "ingest_graph" | "proposal_graph")`. It builds the agents if no chat has happened yet, and returns `None` outside a lifespan.

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
| Proposal agent | `sangam_proposal` | `proposal` |
| Proposal file readers | `sangam_proposal_reader` | `proposal`, `reader` |
| News verifier | `sangam_news_verify` | `news`, `verify`, the research spec |

`TRACE_NAME = "sangam_agent"` is only the default when no name is passed.

**The handler.** A subclass of the SDK's `CallbackHandler` adds the following:

- **Observation types.** The graph and each subagent are typed `agent`. The `answer_audit.after_agent` hook is an `evaluator`. Everything else is a `chain`.
- **Root input and output.** The root input is the last human question, and the root output is the final replies that called no tool (or a structured response, such as the news verifier's check). When a turn stopped for approval it appends "Waiting for a person to approve: ...".
- **Parenting.** It re-parents runs whose parent the handler never saw onto the LangGraph node run.
- **Cancellation.** A cancelled turn (browser disconnect) is closed with a "cancelled: client disconnected" message and no error level.

**What is exported.** `export_span` keeps Langfuse's default filter, so FastAPI HTTP spans are dropped, and also drops empty middleware hook spans (`PatchToolCallsMiddleware`, `SkillsMiddleware`, `sql_retry_limiter`, `RunSources` and `DropFilesOnExit`, `before_` or `after_` `agent` or `model`). These never call a model, and unlisted hooks are kept because dropping a parent would orphan its children.

**Masking and clipping.** `mask_payload` runs over every input and output. It always clips strings to `MAX_IO_CHARS` (4,000). When `LANGFUSE_MASK_TOOL_RESULTS` is true, it also redacts warehouse rows. Redaction is shape-aware: it cuts after a `columns: ` header (`db_query`) or an `as stored:` line (`db_profile_column`) and leaves the query, caveats and sources above the cut intact. It is also applied in `on_tool_end`. A failing mask sends the payload unmasked, so a mask bug cannot drop a batch. The tests pin this behaviour, including that bare SQL and prose survive and that nested payloads are masked.

**Sessions, users and SQL spans.**

- `SessionScopedAGUIAgent.prepare_stream` maps the AG-UI `thread_id` to `langfuse_session_id` and the run id to `agui_run_id`. The Langfuse user is the caller's email (`caller_trace`), falling back to the user id, and the request's tags carry `role:staff`, `role:<org role>` and `org:<name>` for each organisation; a proposal run adds `proposal_id`. Without the session mapping each turn is an orphan trace.
- `run()` wraps the run in `propagate_caller`, so every span (not just the root) carries the user, session, trace name, tags and a `version` that groups the caller's organisations (Langfuse v4 dashboards read these per observation).
- It de-duplicates tool results the browser re-sends under its own ids.
- It addresses a legacy resume to one open interrupt through `key_resume`, which is needed because parallel Import writers pause together and LangGraph refuses an unaddressed resume.
- `run()` flushes Langfuse in a thread in a `finally`, because a serverless function freezes once it has answered.
- `sql_span` and `traced_fetch` record each SQL statement as a `retriever` observation under the current tool span, with the dedented SQL, its params and the row count. `score_answer` attaches scores such as `answer_audit` to the current turn's trace.

**LangSmith** needs no wiring. `langsmith_status()` only reports at boot whether it is on, off, or misconfigured.

**Recursion limit is carried twice.** Each builder binds `recursion_limit` to the graph, and the lifespan also passes it as the AG-UI agent's `config`. AG-UI builds each request's config with `ensure_config`, which stamps LangGraph's default of 25 and overrides the graph-bound value. Removing the `config=` argument in `_build_agents` would silently bring the 25-step cap back. A test pins both the trap and the fix, and the setting stays at least 150.

**Focused tests.** `backend/tests/test_tracing.py` covers:

- run naming with tracing off, and handler binding to the configured client;
- graceful degradation when the SDK is broken;
- session, user and run metadata, caller email and org tags, attributes on every span, and survival of graph-level tags;
- SQL spans, masking and clipping, and cancelled turns;
- the bad-credentials error message;
- recursion-limit propagation;
- `key_resume` and parallel pauses;
- a guard that every documented `LANGSMITH_*`, `LANGFUSE_*` and `SUPABASE_*` variable in `.env.example` is forwarded by `docker-compose.yml`.

## Deploy topology

Two Vercel projects deploy from one repository: the frontend (`sangam`, root `frontend`) and the backend (`sangam-backend`, root `backend`, a FastAPI function). Postgres, Auth and Storage are Supabase in `ap-south-1`. Neo4j is optional.

- **Both `vercel.json` files** set `git.deploymentEnabled: false` and `regions: ["bom1"]`. Nothing deploys on push. The only deploy is `.github/workflows/deploy.yml`, which has a `workflow_dispatch` trigger and is run by hand (see [Deploying by hand](../workflows/deploying-by-hand.md)). CI (below) runs on every PR but deploys nothing. `bom1` puts both functions next to the database in Mumbai.
- **`backend/vercel.json`** also sets `functions."app/main.py".maxDuration` to 1800 seconds, which long Import and news runs depend on. It also defines a cron on `/health` every five minutes (`*/5 * * * *`). The cron keeps one instance warm and does nothing for several calls arriving at once.
- **Function limit coupling.** The news verifier budget (`news_verify_seconds`, 600) is chosen so a pull still ends inside the 1,800 s function limit. The frontend's chat route must carry the same maximum duration.
- **Local run.** docker-compose forwards the environment to the backend container, and a test guards that forwarding for the tracing and Supabase variables.

## CI and PR checks

Two workflows check every pull request. Neither deploys anything.

**`.github/workflows/ci.yml`** runs on every `pull_request` and every push to `master`, with `contents: read`, a `concurrency` group per ref that cancels superseded runs, and a `timeout-minutes` cap on each job. It has four independent jobs:

| Job | What it runs |
|---|---|
| `backend-lint` | `uv sync --frozen`, then `ruff check . --output-format=github` in `backend/` (Python 3.12). Only `ruff check`; the ruff formatter is not enforced. |
| `backend-unit` | `pytest -m "not integration" --cov --cov-report=xml`, then uploads `backend/coverage.xml` to Codecov with the flags `backend,backend-unit`. |
| `backend-integration` | A `pgvector/pgvector:pg17` service container on port 5433 (the same image as docker-compose). It applies `db/init/*.sql` with `psql`, runs `python -m app.db.migrate` (with `MIGRATIONS_DIR` pointing at `db/migrations`), `seed.seed` and `seed.taxonomy_seed`, then `pytest -m integration --cov -rs`, and uploads with the flags `backend,backend-integration`. |
| `frontend` | Node 22, `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm run coverage` (Vitest), an upload of `frontend/coverage/lcov.info` with the flag `frontend`, then `npm run build`. |

Details that matter when changing it:

- **The integration job is meant to run, not skip.** `-rs` lists skips, because a test that skips for "Postgres not reachable" means a broken job. It deselects `test_preserved_row_counts` and `test_documents_sequence_advanced` in `tests/test_migration_integrity.py`, which check a restore of the original dump (96 documents) that `make seed` never creates.
- **Coverage upload uses OIDC.** The three uploading jobs have `id-token: write` and pass `use_oidc` as true except on fork PRs, so no token is stored. A fork falls back to tokenless upload.
- **Dependencies are locked.** Python jobs use `uv sync --frozen`, so a stale `uv.lock` fails the job. The dev group in `backend/pyproject.toml` pins `ruff==0.16.8` and adds `pytest-cov`.
- **Ruff config.** `[tool.ruff]` uses line length 110 and `py312`. Lint ignores `B008` (FastAPI's `Depends()` idiom), `RUF012` (class-level constants) and `UP046` (PEP 695 needs 3.12, while `requires-python` is 3.11). Coverage is measured on `app` with branch coverage and relative file paths.

**Codecov thresholds** live in `codecov.yml`. The repo-wide `project` and `patch` statuses are off. Instead the `backend` and `frontend` components (by path) are gated separately, so one side's figure cannot sink the other's. Each has three statuses: a `floor-` project check at 75%, a project check with `target: auto` and a 1% threshold (a PR may not lower that component's coverage by more than 1% against the base commit), and a patch check requiring 75% of the lines a PR adds or changes. Every flag carries forward, so the unit and integration uploads merge into one backend report per commit. `fixes` rules map `coverage.xml` and `lcov.info` paths (relative to `backend/` and `frontend/`) onto repository paths, and the PR comment is condensed (header, diff, flags, components, files).

**`.github/workflows/dependency-review.yml`** runs `actions/dependency-review-action@v4` on every PR with `fail-on-severity: high` and posts its summary as a PR comment only on failure. It fails a PR whose lockfile changes add a package with a high or critical advisory. It checks only what the PR changes, and already-open alerts stay in Security → Dependabot.

**Plan versus code.** `docs/features/2026-10-16-ci.md` was revised in review. Its original design had a self-hosted `coverage` job with `diff-cover` and a `fail_under` ratchet. The shipped design uses Codecov instead, so there is no `coverage` job. The plan's second milestone (a Dependabot config, a Claude review workflow, a PR template and CODEOWNERS) has no matching files under `.github/`: only `ci.yml`, `dependency-review.yml` and `deploy.yml` exist. The plan also lists branch-protection rules and other GitHub settings as manual work, and a workflow file cannot show whether they are on. The raised 75% gates come from `docs/features/2026-10-21-coverage-75.md`. The test tiers CI runs are described in [Testing overview](../testing/overview.md).

### Makefile targets

The `Makefile` is local tooling and deploys nothing. Bare `make` runs `help`, which is built from the `##` comments. `ENV=local|staging` picks the database for the DB-touching targets (staging points your machine at the managed database). `make up` starts Postgres, runs `migrate` and then builds the other containers. Other targets that matter here:

- **`make evals`** runs the golden-question evals on the host venv through the real agent. It costs money. `TAG=canary|cost` selects a subset and `K=<case>` runs one case through pytest `-k`. It sets `LANGFUSE_TRACING_ENVIRONMENT=eval` and the release to the short git sha, so eval traces stay apart from real traffic. Evals are not part of CI.
- **`make smoke`** is the end-to-end check of the running stack. It is not a CI step.
- **`make wiki`, `wiki-update`, `wiki-fix` and `wiki-deploy`** drive OpenWiki (pinned to `openwiki@0.7.2`). `wiki-update` rewrites only pages whose evidence changed.

## Performance

`docs/features/2026-10-10-page-load-performance.md` records the measurements behind the current shape:

- **Distance was the first cost.** Originally both functions ran in `iad1` against a Mumbai database, and each round trip cost about 200 ms. Moving to `bom1` (#148) took warm `/api/funders` from 1.2 s to 0.2 s.
- **Cold starts dominate.** A cold backend call took 8–12 s, from the runtime dependency install (2–4 s) plus imports, connect and the catalog check. About two-thirds of the import time was the agent stack. This is why agent building moved off the boot path (PR 7, lazy `load_agents`), taking a local `import app.main` from 1.84 s to roughly 0.3–0.4 s.
- **Fewer calls per page.** Profile pages use one aggregate endpoint each (`GET /api/orgs/{slug}/profile`, `GET /api/funders/{slug}/profile`, #179), because a page waits for its slowest call and each parallel call can land on a fresh cold instance. `GET /api/ingest/overview` does the same for the Import page.
- **Caching.** Signed-out reads use Next's data cache (`revalidate: 300`) and signed-in reads stay `no-store`, because RLS decides what they see (#180). The `/health` cron is the keep-warm measure.
- **Not done.** The 2–4 s dependency install remains because `graphiti-core` stays in the bundle (PR 2 was closed). Signed-in pages can still meet a cold start. Loading states and the JS trim are deferred. Check the "Not finished" table in [`docs/CHANGELOG.md`](../../docs/CHANGELOG.md) before assuming the plan doc matches the code.

### Ask efficiency: shared middleware and `compare_fit` sizing

`docs/features/2026-10-16-ask-efficiency.md` starts from one production trace of a "what does X do, where does it work, which funders fit it" question: $0.87, 141 s, 21 model calls and 26 tool calls. Its target is under $0.25, under 60 s and under 8 model calls and 8 tool calls. Two of the plan's causes are fixed in code that other agents share.

- **`compare_fit(org_id)` fits in the conversation.** Before, it returned every scored funder at full detail as one JSON line. That went past deepagents' 20k-token tool-result limit, was moved to `/large_tool_results/` as a one-line file the model could not page, and led to repeated `compare_fit` calls. Now `ask/tools/matching_tools.py` renders text, one fact per line. Without `funder_ids` it is a shortlist: the top `FULL_DETAIL_MAX` (10) strong or medium funders in full, every other scored funder on one line (score, tier, first gap), then the funders not scored. The header counts only scored funders. With `funder_ids` every named funder is shown in full with its summary. Unknown criteria stay "unknown" and are never folded into weak. `matching.may_run` still refuses anyone who is not staff, a steward or an admin. Errors come back as `compare_fit failed:` strings, never raised.
- **Tool-result clearing keeps the prompt cache stable.** `clear_old_tool_results()` in `agentkit/middleware.py` wraps `SteppedClearToolUsesEdit`. The trigger rose from 40k to `TOOL_RESULT_CLEAR_TRIGGER_TOKENS = 60_000` and the last `TOOL_RESULTS_KEPT = 5` results stay. Past the trigger it reclaims `ceil((tokens − trigger) / step) × step` from the oldest end, with `TOOL_RESULTS_CLEAR_STEP = 20_000`. What is sent stays under about 60k, and the set of cleared results (and so the cached prefix) changes once per 20k of growth instead of on every call. A fixed `clear_at_least` would reclaim the same amount forever. Results of `compare_fit` are in `NEVER_CLEARED`, because clearing them made the model call it again.
- **Blast radius.** The function is shared: Ask (`ask/agent.py`), Sangam Import (`ingest/agent.py`), the proposal agent (`proposals/agent.py`) and the proposal readers all call it, so all of them get the new trigger and stepping. The `compare_fit` exclusion does nothing outside Ask.
- **Eval measurement (M1).** `tests/evals/harness.py` has `RunStats` (tool calls by name, model calls, tokens). Cases can carry `max_calls` and `max_large_result_reads`, and with Langfuse keys the selected cases run once as a dataset experiment on `ask-golden`, under environment `eval` (see `make evals` above).
- **In-code budgets.** `CompareFitBudget` (`ask/middleware.py`) refuses a repeated `compare_fit` (same org and funder ids this turn) and any call past `MAX_COMPARE_FIT_CALLS = 3`, and `model_call_cap(settings.ask_model_call_limit)` ends a turn at 25 model calls. Both are built into Ask's middleware in `ask/agent.py`.

**Status.** The CHANGELOG still lists M1 (evals) and M2 (`compare_fit` text and stepped clearing) as `(unmerged)`, although the code for both is present in the tree. M3, M4 and M5 are merged and in the tree: the prompt carries a `{{TABLE_MAP}}` and the SQL validator adds `__cite__` columns (M3), `fetch_url` is gone so Ask registers six tools and `db_profile_column` errors count toward the five-attempt SQL limit (M4), and a proposal run with no new message ends without a model call through `nothing_to_answer` (M5). The plan's Draft v2 status line has not been updated.

## Known regressions

- **`emit_raw_events` is back on for Ask and Import.** The CopilotKit-removal plan had the `SessionScopedAGUIAgent(...)` calls in `core/lifespan.py` pass `emit_raw_events=False`. With raw events off, one answer went from 1.69 MB to 107 KB (#167–#169). Then #178 removed that argument from the two existing agents. The `SessionScopedAGUIAgent` constructor defaults `emit_raw_events=True`, and `_build_agents` passes only `emit_subagent_events=True` for `/ingest` and nothing for `/agent`. So every AG-UI event on those two routes again carries a copy of the LangGraph event it came from, including run metadata such as `langfuse_user_id` and model settings. The newer `/proposal` agent is built with `emit_raw_events=False` and is not affected. The fix for the others is to pass `emit_raw_events=False` too. See the [CHANGELOG "Not finished" table](../../docs/CHANGELOG.md) and the Performance entry for #167–#169.

## Where to change things

- **A new REST resource:** add a router module under `api/routes`, include it in `api/router.py`, add an `OPENAPI_TAGS` entry, and import any agent code inside functions.
- **A new default or model tier:** edit `core/config.py` only, add the field to the blank-means-default validator if it is an int or a model spec, and forward the variable in `docker-compose.yml`. Set it in Vercel for deployed backends.
- **Something every agent should share:** put it in `agentkit/` (models, harness, middleware). Ask-only behaviour goes in `ask/`, and Import's in `ingest/`.
- **A new agent or trace root:** pass a distinct `name` and tags to `trace_config`, build the graph in `_build_agents`, wrap it in `SessionScopedAGUIAgent`, and register the path in both `AGENT_NAMES` and `AGENT_ACCESS`. A path without an access entry fails at boot.
- **A new outbound fetch of a model- or user-supplied URL:** go through `guarded_client()` (or `check_url` for research reads), never a bare httpx client.
- **A new table the SQL tool may read:** update the SQL catalog, or the lifespan's catalog check will refuse to boot.
