# Deploying Sangam

Docker is local development only. Deployed, the stack splits across three hosts.

| Piece | Runs on | Why |
|---|---|---|
| Next.js frontend | **Vercel** | Natural fit; every data-fetching route is server-rendered on demand |
| FastAPI + LangGraph backend | **A container host** (Railway, Render, Fly) | Long-lived process — see below |
| Postgres | **Supabase / Neon** | Holds app data *and* LangGraph chat checkpoints |
| Neo4j *(optional)* | **Neo4j Aura**, or omit | Graph features disable themselves cleanly when unset |

## Why the backend cannot go on Vercel

It is not a request/response API. It holds a psycopg connection pool, a Graphiti
client, and a LangGraph agent that streams SSE for the length of an agent turn.
On serverless functions each invocation would re-open the pool, and a long
agent turn would be cut off mid-stream. `backend/Dockerfile` is already
production-shaped — its `CMD` has no `--reload` (compose overrides it for dev) —
so any container host can build the repo as-is.

---

## 1. Postgres

Create the database, then fill the `STAGING_DB_*` block in `.env` and run **one** of:

```bash
make db-push-remote ENV=staging   # schema AND data — use this one
make db-init-remote ENV=staging   # empty schema only, then: make seed ENV=staging
```

**Use `db-push-remote`.** `make seed` does not create the 96 documents — those
were restored from a dump and the seeder has no knowledge of them — so the
init-and-seed path yields a working stack with an empty `documents` table and no
obvious sign that anything is missing.

Requirements: Postgres 15+, the `vector` and `pg_trgm` extensions available, and
a role with `CREATE` on `public` (the checkpointer creates its tables at boot).

## 2. Backend

Point the host at `backend/Dockerfile`. Environment:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Keyword form is fine and avoids percent-encoding: `host=… port=5432 user=… password=… dbname=… sslmode=require` |
| `ANTHROPIC_API_KEY` | The agent's reasoning model |
| `MODEL` | Defaults to `anthropic:claude-sonnet-5` |
| `OPENAI_API_KEY` | Only for Graphiti extraction/embeddings. Omit to run without the graph |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Omit to disable the graph |
| `EMBEDDING_DIM` | **`768`** if you reuse the existing graph — mixing dimensions fails |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | Optional tracing. `LANGFUSE_BASE_URL` is also read, and wins over `LANGFUSE_HOST` |
| `LANGFUSE_TRACING_ENVIRONMENT` | Trace bucket, e.g. `production`. Unset means deployed traces land beside local ones |
| `LANGFUSE_RELEASE` | Optional build stamp on each trace, e.g. the git sha |
| `ALLOWED_ORIGINS` | Comma-separated exact origins, e.g. your production Vercel domain |
| `ALLOWED_ORIGIN_REGEX` | For Vercel preview domains — see below |

With `NEO4J_URI` unset, `search_graph` returns a message telling the agent the
graph is unconfigured and to use the database tools instead. Nothing crashes.

## 3. Frontend on Vercel

Import the repo and set **Root Directory = `frontend`**. This is a monorepo;
Vercel defaults to the repository root, where there is no Next app.
`Dockerfile.dev` is ignored — Vercel builds Next natively.

| Variable | Used by |
|---|---|
| `AGENT_URL` | Server components and the CopilotKit runtime route. Set to `https://your-backend/agent` — `api.ts` strips the `/agent` suffix to derive the REST base |
| `NEXT_PUBLIC_API_URL` | The browser. `VaultView`, `MediaView` and `ScoreCard` fetch the backend directly, so this is required too |

Optional: `COPILOTKIT_TELEMETRY_DISABLED=true` to silence the runtime's
telemetry notice during builds.

## CORS and Vercel previews

Every Vercel preview deployment gets a fresh hostname, so an exact-match list
cannot cover them: production works while previews fail in the browser with CORS
errors *even though server-rendered pages still load* — a confusing half-broken
state. Set both:

```bash
ALLOWED_ORIGINS=https://sangam.vercel.app
ALLOWED_ORIGIN_REGEX=^https://sangam-[a-z0-9-]+\.vercel\.app$
```

**Anchor the pattern.** Verified behaviour with the regex above:

| Origin | Result |
|---|---|
| `https://sangam-git-main-tech4dev.vercel.app` | allowed |
| `https://sangam-abc123xyz.vercel.app` | allowed |
| `https://sangam-abc.vercel.app.attacker.com` | **blocked** |
| `https://notsangam.vercel.app` | **blocked** |

Without `^…$`, that third row would be allowed.

---

## ⚠️ Before you expose a public URL: there is no authentication

`backend/app/core/security.py::get_current_user` returns a hardcoded UUID regardless of
the token presented, and the frontend sends the literal string `Bearer dev`.
Consequences of a public deployment as it stands:

- Every funder and NGO record, every document, and every fit score is readable
  by anyone who finds the URL.
- Anyone can run the agent, **billed to your Anthropic key**.

Until Supabase JWT verification lands (the swap is confined to that one
function), protect the backend at the platform level — an IP allowlist, basic
auth, or the host's built-in access control. That is configuration rather than
code and takes minutes.

Note that platform-level basic auth will also block the three browser-side
fetches (`VaultView`, `MediaView`, `ScoreCard`), since the browser has no
credentials for it. The Doc vault, Media view and score breakdowns will show
their empty states while everything server-rendered keeps working. If you need
those working under lockdown, route them through Next server-side handlers so
the credential stays on Vercel.

## What triggers a deploy

Nothing deploys automatically. `frontend/vercel.json` and `backend/vercel.json` set
`git.deploymentEnabled: false`, which switches off Vercel's Git integration for both projects,
and `.github/workflows/deploy.yml` is the only thing that deploys — when someone runs it.

| Event | Deploys |
|---|---|
| Push to any branch | nothing |
| Merge to `master` | nothing |
| Actions tab → Deploy → Run workflow (on `master`) | both |

There are **no preview deployments**. Before this, every push to any of the repo's twenty
branches built both projects — 40 deployments in a day — because the Git integration cannot
tell which directory a commit touched.

Two things to know before changing it:

- **Each `vercel.json` must stay in its project's Root Directory.** Vercel reads it from
  there, not from the repo root; a repo-root `vercel.json` is silently ignored when Root
  Directory is set, which is how the old one sat tracked and inert for weeks.
- **The workflow does not build.** It runs `vercel deploy --prod` without `--prebuilt`, so
  Vercel still builds exactly as it did under the Git integration. The workflow only decides
  whether and what to deploy. It needs one repository secret, `VERCEL_TOKEN`.

The `ALLOWED_ORIGIN_REGEX` guidance above is now belt-and-braces: with previews disabled,
no preview hostname is generated. Keep it in case previews are ever re-enabled.

## Post-deploy check

```bash
BACKEND_URL=https://your-backend FRONTEND_URL=https://your-frontend make smoke
```

`scripts/smoke.sh` takes both URLs from the environment, so the same 17 checks
that guard local development also verify a deployment.
