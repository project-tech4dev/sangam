# Page-load performance — stacked PRs (Draft v2)

Draft v1 (2026-10-10) planned six PRs. Two shipped, one was closed, and the 2026-10-12 re-measure
changed the diagnosis, so the rest is replanned as a second stack, PRs 7–10, below. The v1 text
follows unchanged as the record of what was decided then.

## Status

| PR | What | State |
|---|---|---|
| 1 `perf/1-region` | both functions in bom1 | merged (#148): warm `/api/funders` 1.2 s → 0.2 s |
| 2 `perf/2-cold-start` | graph and MCP packages out of the bundle | closed (#149): Neo4j goes to production (#128) and needs graphiti-core |
| 3 `perf/3-round-trips` | fewer queries per funder detail | not started; warm pages already < 0.5 s, so dropped |
| 4 `perf/4-waterfalls` | independent calls start together | merged (#155) |
| 5 `perf/5-cache-loading` | anonymous cache, loading states | folded into PR 9 (cache); loading states deferred |
| 6 `perf/6-js-weight` | lighter first-load JS | deferred |
| 7 `perf/7-boot` | the agent stack stays off the boot path | this stack |
| 8 `perf/8-profile-calls` | one backend call per profile page | this stack |
| 9 `perf/9-public-cache` | anonymous reads cached; a warm-up cron | this stack |
| 10 `perf/10-db` | Supabase advisor fixes; Import upsert | this stack |

## 2026-10-12: warm is fast, cold is the whole problem

Measured with curl on the live site, Vercel runtime logs and `pg_stat_statements`:

| | Cold | Warm |
|---|---|---|
| `/registry` | 11.8–12.1 s | 0.24–0.47 s |
| `/` (frontend's own cold start) | 3.3 s | 0.2 s |
| backend `/api/orgs`, `/api/funders`, `/api/programs`, … | 8–12 s | 0.17–0.30 s, database included |

- **Almost every page visit hits a cold backend.** The last 24 h of logs show a cold start on nearly
  every visit, one per parallel call: one org-profile load at 05:41:34 started five instances at once.
- **A warm instance doesn't save a fanned-out page.** Six parallel calls at a warm backend: five
  answered in ~0.3 s, the sixth started an instance and took 8.5 s. A page waits for its slowest call.
- **Where a cold start's ~8.5 s goes** (`/api/funders` at 08:00:58):
  - Vercel installs the Python dependencies at runtime: 2–4 s. With graphiti-core staying, this is the floor.
  - Imports, Supabase connect, catalog check: 4.6–6.7 s. Locally `import app.main` is 1.84 s, and about
    two-thirds of it is the agent stack (deepagents, langchain-anthropic, trafilatura, copilotkit, langfuse),
    which a REST call never uses.
  - `saver.setup()` and the catalog check together cost ~25 ms on the server, and building both
    agents takes 0.09 s. Neither is the problem, so both stay.
- **Supabase is not slow.** The REST queries are not in the top 25 by total time. The boot-time
  `information_schema.columns` check ran 380 times at 22 ms, i.e. ~380 cold starts in the stats window.
  The advisor flags two duplicate permissive policies (`users`, `org_members`) that both run on every
  RLS read, and 82 foreign keys without an index, mostly on log tables.
- **Import, not page load:** the `ingest_source_proposals` upsert peaks at 1,986 ms (mean 8.5 ms),
  because parallel researchers queue on the same host's row inside an explicit transaction.

## Second stack (PRs 7–10)

```
origin/master
 └─ perf/7-boot             (PR 7 → master; this plan's commit is its first)
     └─ perf/8-profile-calls   (PR 8 → perf/7-boot)
         └─ perf/9-public-cache   (PR 9 → perf/8-profile-calls)
             └─ perf/10-db           (PR 10 → perf/9-public-cache)
```

Same mechanics as v1: worktree `../sangam-perf-boot`, no new tests, each PR runs
`pytest -m "not integration"`, `ruff check .`, `npm run lint` and `npm run build`. When PR N merges,
retarget N+1 to `master` and rebase it.

### Milestone 7 — PR 7: the agent stack stays off the boot path
- **Deliverable:** a cold REST call imports only what REST needs; the agents are built on the first chat turn.
- **Key tasks:**
  - [ ] `core/lifespan.py`: boot keeps the pool, catalog check, graph and checkpointer. Langfuse setup,
        both agent builds and their AG-UI agents move into one builder, run once under a lock on the
        first `/agent` or `/ingest` request, in the documented order (configure tracing, then build).
  - [ ] Our own thin `/agent` and `/ingest` POST routes replace `add_langgraph_fastapi_endpoint`
        (which needs the agent at registration), keeping `chat_access` and the `GET …/health` routes
        `make smoke` checks.
  - [ ] one `get_graph(app, name)` accessor for `threads.py` and `ingest.py`, which read the graphs directly.
  - [ ] lazy imports in the routes that pull agent code: `threads.py` (`ag_ui_langgraph`),
        `documents.py` (`agent.tools.files`), and whatever `-X importtime` on `app.api.router` still shows.
  - [ ] log each boot phase's elapsed time, so the next cold start can be read from the logs.
- **Example:** a signed-out visitor opens `/registry` on a cold backend. Before, `/api/funders`
  waited ~4.6 s for imports that included deepagents and trafilatura. After, it imports FastAPI,
  psycopg and the routes, and the agent stack waits for the first Ask turn.
- **Trade:** the first chat turn on a fresh instance pays the deferred ~1–3 s of imports.
- **Exit gate (after deploy):** the boot-phase log shows imports + connect + verify ≤ 2 s (was 4.6–6.7 s);
  cold `/api/orgs` ≤ 5 s (was 8.5–12 s).

### Milestone 8 — PR 8: one backend call per profile page
- **Deliverable:** an org profile makes 1 call instead of 5, a funder profile 1 instead of 5.
- **Key tasks:**
  - [ ] `GET /api/orgs/{slug}/profile` and `GET /api/funders/{slug}/profile`: `asyncio.gather` over the
        existing repository calls, each on its own caller connection (RLS unchanged). The funder brief
        is a nullable field, so a funder that has not been researched is not a failure.
  - [ ] both profile pages call the aggregate once.
- **Example:** before, one cold org-profile load started five instances (05:41:34) and waited for the
  slowest. After, it is one request, so it is at most one cold start.
- **Conflict:** `feat/media-signals` changes the news both profiles show. Whichever merges second
  moves the `news` field to the other's shape.
- **Exit gate:** opening a profile shows one backend request in the runtime logs.

### Milestone 9 — PR 9: signed-out reads come from a cache
- **Deliverable:** a signed-out visitor's pages render from Next's data cache, whatever state the backend is in.
- **Key tasks:**
  - [ ] `lib/api/client.ts`: with no session, fetch without the auth header and with
        `next: { revalidate: 300 }` in place of `cache: "no-store"`. Signed-in calls stay `no-store`,
        because RLS decides what they see.
  - [ ] the funder profile's signed brief link is minted only for a signed-in caller, so no signed URL is cached.
  - [ ] `backend/vercel.json`: a cron hitting `/health` every 5 minutes, to keep one instance warm.
- **Example:** a funder opens a shared `/registry` link signed out. Before, 12 s on a cold backend.
  After, the cached render, refreshed in the background at most every 5 minutes.
- **Exit gate:** signed-out `/registry` < 0.5 s on three hits ten minutes apart. The cron stays only if
  `/api/orgs` hit at 10 random minutes over an hour answers under 0.5 s at least 9 times; otherwise PR 10 removes it.
  It keeps one instance warm and does nothing for several calls arriving at once.

### Milestone 10 — PR 10: Supabase advisor fixes, and the Import upsert
- **Deliverable:** one read policy per table, indexes for the profile joins, no queue on the proposals row.
- **Key tasks:**
  - [ ] migration `0044_`: fold `users_read_by_admin` into `users_read` and `org_members_read_by_admin` into
        `org_members_read` (permissive policies already OR together, so who sees what is unchanged);
        index `org_tags(tag_id)`, `funder_tags(tag_id)` and `funder_activity(program_id)`.
        `feat/media-signals` holds 0044/0045 on its branch: whichever merges second renumbers.
  - [ ] `ingest/access.py::_note_proposal`: drop the explicit transaction around the single upsert (the pool
        autocommits), so the row lock lasts one statement. An Import fix, not page load.
  - [ ] the CLAUDE.md migration count and list.
- **Exit gate:** the performance advisor no longer lists `multiple_permissive_policies`; the upsert's max
  in `pg_stat_statements` after an 8-organisation Import is < 100 ms.

## Known gaps — what this stack does NOT make true

- A cold start still costs the 2–4 s dependency install; only a smaller bundle removes it, and graphiti-core stays.
- Signed-in pages still call the backend on every render, so a signed-in visitor can still meet a cold start.
- The frontend's own ~3 s cold start is untouched.
- Loading states (v1 PR 5) and the JS trim (v1 PR 6) are not in this stack.

---

# Draft v1 (2026-10-10), as approved

## Context

The live site was measured in Chrome (signed in), with curl and from the build output on
2026-10-10. Slow pages:

| Page | Warm | Cold | Where the time goes |
|---|---|---|---|
| Funder profile | ~5.0 s | 27.3 s | 1 call, then 4 calls in parallel, all before any HTML is sent |
| `/import` | ~5 s | 8.6 s | `/api/me`, then 5 calls fetched by the browser |
| `/settings` | ~4 s | 4.5 s | 4 sequential server calls |
| `/ask` | 2.3 s (+2 s for the thread list) | 2.8 s | 5 calls, then `/api/threads`; 866 KB of JS |
| `/registry` | ~1.75 s | 23.3 s | 2 calls, ~1.2 s each |

**Goal: every warm page renders in under 1 s, and a cold first visit takes under 5 s.**
Success means the five rows above, re-measured on the live site the same way, meet that target.

### What Supabase shows (checked: pg_stat_statements, the perf advisor, postgres logs)

- **No app query is slow.** The heaviest app queries average 0.6–30 ms:
  - registry stats count: 12–17 ms;
  - `list_research` `DISTINCT ON`: 7–30 ms;
  - funder detail: 2–6 ms;
  - `users` lookup: 0.6 ms.
  - The only statements over 1 s are dashboard `COPY` exports and Supabase's own catalog introspection.
- **BEGIN, `set_config` and COMMIT cost about 0 ms on the server.** Each one still costs a full network round trip.
- **The cost is distance.** Both Vercel functions run in iad1 (US East); the header reads `x-vercel-id: bom1::iad1`, and neither `vercel.json` sets a region. The database is in ap-south-1 (Mumbai).
  - Each round trip is about 200 ms.
  - **Example:** `/api/funders` makes 4 round trips (BEGIN, `set_config`, the query, COMMIT). That is about 0.8 s, and the query itself takes 2 ms.
- **There are signs of connection churn:**
  - 9,651 `pgbouncer.get_auth` calls, i.e. new connections, mostly from cold starts;
  - 610 `DISCARD ALL` at 26 ms each, issued by Supavisor when a session ends, not by our code.
- **Advisor:** 72 foreign keys with no index and 35 unused indexes. At this data size (75 MB, of which 48 MB is checkpoint blobs) they cost nothing measurable. Not in scope.

## Decisions (confirmed with the user)

- Both functions move to **bom1**. The cost: each Claude call from the agent adds about 200 ms (India to the US).
- **Scope:** server, waterfalls, caching and JavaScript. The CopilotKit trim (~575 KB) is deferred because it needs an upstream change.
- **Gate per PR:** I open the PR; the user merges it and runs Deploy; I re-time the live site and record the numbers in the next PR's description.

## Stack mechanics

- **Worktree:** `../sangam-perf` from `origin/master`, because other sessions share the main checkout.
- **Branches:**

```
origin/master
 └─ perf/1-region        (PR 1 → master)
     └─ perf/2-cold-start   (PR 2 → perf/1-region)
         └─ perf/3-round-trips  (PR 3 → perf/2-cold-start)
             └─ perf/4-waterfalls   (PR 4 → perf/3-round-trips)
                 └─ perf/5-cache-loading (PR 5 → perf/4-waterfalls)
                     └─ perf/6-js-weight    (PR 6 → perf/5-cache-loading)
```

- When PR N merges, retarget PR N+1 to `master` (`gh pr edit --base master`) and rebase it onto `origin/master`.
- No new tests (per the user's rule); fix only tests that a change breaks.
- Each PR runs `pytest -m "not integration"`, `ruff check .`, `npm run lint` and `npm run build`.

## Blast radius (built by hand from CLAUDE.md, `catalog.py` and the code)

| Surface | Why it's affected | Status |
|---|---|---|
| `backend/vercel.json`, `frontend/vercel.json` | gain `regions` | PR 1 |
| `backend/pyproject.toml`, `uv.lock`, `Dockerfile` | graph and MCP packages become an optional extra | PR 2 |
| `backend/app/repositories/funders.py`, `routes/funders.py` | fewer queries | PR 3 |
| `backend/app/core/security.py`, `repositories/users.py` | short in-memory cache of the user lookup | PR 3 |
| registry profile pages, `SettingsPage.tsx`, `ImportView.tsx` | calls run in parallel | PR 4 |
| `frontend/lib/api/client.ts` | anonymous reads are cached | PR 5 |
| `loading.tsx` (new) and registry links | loading state; no prefetch of profiles | PR 5 |
| `components/layout/NavBar.tsx`, `Nav.tsx`, `features/auth/sign-in-button.tsx` | sign-in UI loads lazily | PR 6 |
| `features/ask/preview/AskPreview.tsx` | sample answer rendered on the server | PR 6 |
| Redirect-only pages (`/orgs`, `/funders`, `/taxonomy`, …) | move to `next.config.ts` `redirects()` | PR 6 |
| SQL catalog, agent tools, prompts, migrations | untouched: no schema change, the agent's DB path is unchanged | out of scope |
| Checkpointer, `lifespan.py` boot checks | kept. After bom1 their round trips are ~1 ms; skipping `verify_against_db` would weaken a deliberate safety check | out of scope unless PR 1 numbers show boot > 1 s |
| Design system | PR 5 adds a loading look and PR 6 restructures the navbar. Use existing tokens and classes only; sync `ui_kits/sangam-web/` if anything visible changes | PR 5, PR 6 |
| CopilotKit bundle | needs an upstream headless provider | deferred |

## Milestones

### Milestone 1 — PR 1: run both functions next to the database (bom1)
- **Deliverable:** both Vercel functions run in Mumbai.
- **Key tasks:**
  - [ ] commit this plan as `docs/features/2026-10-10-page-load-performance.md`
  - [ ] add `"regions": ["bom1"]` to `backend/vercel.json` and `frontend/vercel.json`
  - [ ] confirm on the Vercel projects (MCP `get_project`, read-only) that no dashboard setting overrides it
  - [ ] update CLAUDE.md's Deployment table: functions in bom1, beside Supabase ap-south-1
- **Exit gate (after the user deploys):**
  - `curl -sI …/health` shows `x-vercel-id: bom1::bom1`.
  - Warm `/api/funders` < 0.4 s.
  - Warm `/registry` < 0.6 s.
  - Re-time one Ask turn and note the change.

### Milestone 2 — PR 2: shorter cold starts
- **Deliverable:** smaller backend bundle; a new instance no longer spends 3–18 s on "runtime dependencies".
- **Key tasks:**
  - [ ] move `graphiti-core[anthropic]` (lazy import at `integrations/graphiti.py:31`; pulls in numpy and neo4j) and `langchain-mcp-adapters` (only `agent/tools/mcp.py`, imported nowhere) into `[project.optional-dependencies]`. Have the local `Dockerfile` install with the extras so `make graph-seed` still works.
  - [ ] keep `langchain-tavily`: it is imported eagerly at `agent/tools/web.py:8`, so removing it breaks boot.
  - [ ] keep `langchain-google-genai`: `models.py:8` supports `google_genai` as a provider.
  - [ ] measure the bundle before and after (`vercel build` output, or deployment `list_deployment_files`)
  - [ ] check whether Fluid compute is on for `sangam-backend` (read-only) and recommend it in the PR body. Turning it on is a dashboard change the user makes.
  - [ ] note in CLAUDE.md that the graph needs the `graph` extra
- **Exit gate:**
  - Cold `/registry` < 5 s on three cold hits.
  - Backend runtime logs no longer show "Installing/Using cached runtime dependencies".

### Milestone 3 — PR 3: fewer round trips per request
- **Deliverable:** the funder detail and signed-in calls do less sequential work.
- **Key tasks:**
  - [ ] `repositories/funders.py::get_funder`: fold the separate tags, locations and contacts queries into the main SELECT as `jsonb_agg` subqueries (tags and locations are already computed there as arrays). This goes from 4 queries to 1.
  - [ ] `routes/funders.py::funder_brief`: look up only `slug` (one small SELECT) instead of the full `get_funder`.
  - [ ] `core/security.py`: an in-process time-to-live (TTL) cache of `auth_user_id → (id, email, is_staff)`, 60 s and bounded in size, in front of `resolve_auth_user`. Skip the cache on a first sign-in or an email change.
  - [ ] check the response shape against `schemas/funders.py` is unchanged (`FunderDetail`)
- **Example:** Priya opens the SBI Foundation profile. `/api/funders/sbi-foundation` was 4 queries plus BEGIN/COMMIT, and the auth lookup added 3 more round trips. Now it is 1 query, and the auth lookup is served from memory.
- **Risk:** for up to 60 s, staff rights that were just granted or revoked still reflect the old value. This is acceptable because RLS is still enforced on every query.
- **Exit gate:** existing tests in `tests/test_funders*.py` and `tests/test_security*.py` pass; warm funder detail < 0.3 s on the live site.

### Milestone 4 — PR 4: remove the frontend waterfalls
- **Deliverable:** pages start every independent call at once.
- **Key tasks:**
  - [ ] `app/registry/funders/[slug]/page.tsx:14-27` and `app/registry/[slug]/page.tsx:16-27`: start the detail call and the 4 sub-calls in one `Promise.all`, using the URL `slug`. If `funder.slug !== slug` (the URL used an id or an old slug), `redirect()` to the canonical URL.
  - [ ] `features/settings/SettingsPage.tsx:14-22`: run `getUser()`, `/api/me` and the staff `/api/orgs` in parallel. The members calls still depend on `/me`.
  - [ ] `features/ingest/ImportView.tsx:42-56`: start `/api/ingest/research` alongside `/api/me`. The staff panels still wait on `/me`.
- **Example:** before, the BEML profile was 1.65 s for the detail call, then ~1.5 s for the four sub-calls. After, it is the slower of the five calls.
- **Exit gate:**
  - `npm run build` passes.
  - Live funder profile warm < 1 s.
  - `/settings` < 1 s.
  - `/import` panels fill < 1.5 s.

### Milestone 5 — PR 5: caching for anonymous visitors, and visible loading
- **Deliverable:** signed-out reads come from a cache, and a click shows a loading state instead of a frozen screen.
- **Key tasks:**
  - [ ] `lib/api/client.ts`: when there is no session, call `fetch` with `next: { revalidate: 300 }` and no auth header. Signed-in calls stay `no-store`, because what they see depends on row-level security (RLS).
  - [ ] `loading.tsx` for `app/registry`, `app/registry/[slug]`, `app/registry/funders/[slug]` and `app/settings`, built from existing classes and tokens only.
  - [ ] registry list links: `prefetch={false}` on profile links. One registry visit currently fires about 10 prefetches, each running 5 backend calls.
- **Exit gate:**
  - Signed-out `/registry` warm < 0.4 s.
  - The click from `/` to `/registry` shows the loading state within 100 ms.
  - No `_rsc` prefetch storm in the network tab.

### Milestone 6 — PR 6: lighter JavaScript on every page
- **Deliverable:** about 80–95 KB gzipped less first-load JS per route, and 46 KB less on signed-out `/ask`.
- **Key tasks:**
  - [ ] Navbar: keep `Nav` a server component with a small client island for the sign-in slot. `dynamic()` import the user menu and `LoginForm`, and `await import('@/lib/supabase/client')` inside the effect. There is no visual change, because the button already renders `null` until the session resolves (`sign-in-button.tsx:71`).
  - [ ] `features/ask/preview/AskPreview.tsx`: render `SAMPLE_ANSWER` through `AnswerCard` in a server component and pass it in as children, so react-markdown stays off the client.
  - [ ] replace the six redirect-only pages with `redirects()` in `next.config.ts` (with a `has` query matcher for `/taxonomy`).
- **Exit gate:**
  - Rebuild and recompute First Load JS: `/terms` < 170 KB gz, signed-out `/ask` < 210 KB gz.
  - Old links (`/orgs`, `/funders`, `/taxonomy?domain=…`) still land on the right page.

## Security review

- **No new endpoints. RLS is unchanged.**
- The PR 3 auth cache keys only on a verified token's subject. A cache hit still runs every query under the caller's role, so the worst case is a staff flag that is 60 s stale.
- The PR 5 cache applies only to requests that carry no `Authorization` header, so cached data is exactly what `anon` sees.
- Region and dependency changes touch no secrets.

## Verification (per PR, plus the end-to-end run)

- **Local:** `cd backend && pytest -m "not integration" && ruff check .`, `cd frontend && npm run lint && npm run build`, then `make up && SMOKE_SKIP_LLM=1 make smoke`.
- **Live, after each deploy:**
  - curl TTFB three times per page;
  - the same Chrome pass as the baseline (navigation timing, network tab);
  - Vercel runtime logs for cold-start lines;
  - Supabase `pg_stat_statements` to confirm the funder detail now runs 1 statement.
- **Final:** re-run the baseline table and put before/after numbers in PR 6's description.

## Open questions and risks

- **Ask turns slower:** after the region move, each Claude call adds about 200 ms. Measured in M1; accepted by the user.
- **Fluid compute and Hobby-plan region limits** are dashboard settings. I report them; the user changes them.
- **Deploys are manual:** the GitHub Actions deploy is blocked by billing (STATE.md). The user deploys via the workflow or Vercel.
- **Data:** live `/api/orgs` returns `[]` (0 orgs), so organisation profiles cannot be timed. This is a data gap, not a performance issue, and is flagged only.
