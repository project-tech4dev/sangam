# Sangam

Grant intelligence for Indian CSOs and the funders who back them. Local dev scaffold:
**Next.js + CopilotKit** → **FastAPI + LangGraph** (via the AG-UI protocol) → **Postgres + pgvector**,
seeded with real cohort data (NGO Darpan registry records, GDELT news monitoring, and
hand-vetted KABIL funder-fit scores on rubric v1/v2).

```
browser ── Next.js (:3000) ── /api/copilotkit (CopilotKit v2 runtime)
                │                    │ AG-UI (SSE)
                │ REST               ▼
                └────────── FastAPI (:8000) ── LangGraph deep agent
                                     │              │ tools: search_orgs, get_funder,
                                     ▼              ▼        get_fit_scores, fetch_url
                              Postgres + pgvector (:5432, checkpoints + app data)
```

## Quickstart

Requirements: Docker Desktop.

```bash
cp .env.example .env        # set ANTHROPIC_API_KEY (or another provider's key + MODEL)
make up                     # postgres + backend + frontend (frontend runs `next dev`)
make seed                   # loads orgs, funders, rubrics, scores, news
```

Open:

- http://localhost:3000 — **Ask Sangam** chat (agent tool calls render inline)
- http://localhost:3000/orgs — cohort registry (10 orgs: 8 Darpan + KABIL + BDF)
- http://localhost:3000/funders — funders with KABIL fit scores (v1/v2)
- http://localhost:8010/docs — FastAPI OpenAPI

Prove the agent → Postgres → citation loop in the chat:

1. *“Which NGOs in our database work in Assam?”* → visible `search_orgs` call, answer cites `[org:N]`.
2. *“How well does KABIL fit Axis Bank Foundation, and why did Eligibility lose points?”*
   → `get_fit_scores` call; the answer should cite the CSR-1 gap (16/20 on criterion 2, rubric v1)
   and mention the hand-vetting adjustment (Relationship 10 → 7, grant concluded ~March 2022).
3. Refresh mid-conversation and continue — threads persist in Postgres (LangGraph checkpointer).

## Layout

```
db/init/        # schema; runs once on first `make up` (plain SQL, lexical order)
seed/           # vendored data + idempotent seed script (see seed/data/README.md for provenance)
backend/        # FastAPI + LangGraph deep agent, AG-UI endpoint at /agent
frontend/       # Next.js App Router + CopilotKit
```

Useful targets: `make logs`, `make psql`, `make db-reset` (drop volume, recreate, re-seed),
`make dev-backend` / `make dev-frontend` (run either outside docker against compose Postgres).

## Knowledge graph (Graphiti + FalkorDB)

Relationship facts extracted from source text live in a temporal graph (FalkorDB, one small
Redis-based container; browser UI at http://localhost:3010). The agent's `search_graph` tool
answers connection questions — "what links KABIL to Tata Trusts?" — with time-bounded facts.

- Requires `OPENAI_API_KEY` in `.env` (Graphiti's extraction LLM + embeddings; Anthropic has
  no embedding models). Without it the stack runs fine and the tool reports the graph as off.
- `make graph-seed` builds the graph **from Postgres** (funder profiles, org registrations,
  the hand-vetting adjustment log). Postgres stays the system of record; the graph is derived
  and rebuildable — safe to wipe (`docker compose down -v` clears it along with everything else).

## Design notes

- **Auth is a stub** (`backend/app/auth.py` returns a seeded dev user; the frontend already
  sends `Authorization: Bearer dev`). Swapping to Supabase JWT later changes only that function.
- **Provenance discipline**: every scraped-fact table carries `source_url/source_name/fetched_at/
  content_hash/extractor_version`; scores carry `scored_by/scored_at` and a manual-override audit
  log (`score_adjustments`). The agent's system prompt requires inline `[org:N]`-style citations.
- **Rubrics are versioned** (`rubrics`/`rubric_criteria` with self-referencing sub-criteria), so a
  future model-based rubric judge writes `fit_scores` rows with `scored_by='model:<name>'` next to
  the human baseline rather than overwriting it.
- **Migrations**: plain SQL in `db/init/` while the schema is young; these files become the first
  Supabase migration when hosted auth/storage arrives.
