# Architecture

The **why** of Sangam: the shape of the system, the rules that must not break, the decisions behind them and the
known regressions. The **what** (tool lists, routes, tables, settings, file maps) is generated in
[`openwiki/`](../openwiki/quickstart.md) and kept current by `make wiki-update`; each section below links its page.
Source code wins over both. How each piece got here is `docs/CHANGELOG.md`.

**Keeping it true:** a PR that changes a rule or decision here edits this file in the same PR. A PR that only
changes a fact (a tool, a column, a route) runs `make wiki-update` instead.

Contents: [1 System](#1-system) · [2 Backend layout](#2-backend-layout) · [3 Ask Sangam](#3-ask-sangam) ·
[4 Sangam Import / Scout](#4-sangam-import--scout) · [5 Funder Match](#5-funder-match) ·
[6 Media & Signals](#6-media--signals) · [7 Data](#7-data) · [8 Auth, roles and RLS](#8-auth-roles-and-rls) ·
[9 Frontend](#9-frontend) · [10 Models and settings](#10-models-and-settings) ·
[11 Deploy, tracing, performance](#11-deploy-tracing-performance) · [12 Knowledge graph](#12-knowledge-graph) ·
[13 Deeper docs](#13-deeper-docs)

---

## 1. System

```
browser ── Next.js (Vercel "sangam", bom1)
             │  server components ── REST ──────────────┐
             │  /api/copilotkit (CopilotKit v2 runtime)  │
             │        │ AG-UI over SSE                    ▼
             │        └────────────► FastAPI (Vercel "sangam-backend", bom1)
             │                         ├─ /api/*      REST, runs as the caller under RLS
             │                         ├─ /agent      Ask Sangam   (deep agent, Opus)
             │                         └─ /ingest     Sangam Import (deep agent + 4 subagents)
             ▼                                │
   Supabase Auth (Google)        Postgres + pgvector (Supabase, Mumbai) · Supabase Storage
                                 Neo4j (optional) · Tavily (web/news search) · Langfuse (traces)
```

- **Two agents, one backend.** Ask Sangam answers questions over the catalog. Sangam Import ("Sangam Scout" on
  screen) researches organisations on the open web and writes what it finds into the catalog.
- **Two paths from frontend to backend.** Server components call REST; the chat proxies AG-UI through
  `/api/copilotkit`. `AGENT_URL` ends in `/agent`; the REST base is it minus `/agent`.
- **Postgres is the system of record.** The graph and the published briefs can both be rebuilt from Postgres and Storage.

Walkthroughs: [one Ask turn](../openwiki/workflows/ask-turn.md), [one Import turn](../openwiki/workflows/import-turn.md).

## 2. Backend layout

Generated map: [platform](../openwiki/architecture/platform.md).

- **A REST resource is three files**: router, hand-written SQL repository, Pydantic schema, plus one line in
  `api/router.py`. No ORM, so no Alembic. `routes/profiles.py` is the one exception: it composes other routes.
- **Agents are built on the first chat turn, not at boot.** Most cold starts serve a REST call, and two-thirds of the
  import time was the agent stack. A REST module therefore imports agent code inside the function that uses it, never at
  the top.
- **Boot raises when the SQL catalog and the live schema disagree**, on purpose: a catalog that is wrong produces
  confidently wrong answers.

## 3. Ask Sangam

Generated detail (tools, skills, middleware order, prompt rules): [ask-sangam](../openwiki/architecture/ask-sangam.md).

- **The model writes its own SQL**; there are no curated lookup tools. The four removed ones (`search_orgs`, …) were a
  cached query plan, and a worse one: asked about Assam, `search_orgs` returned ten orgs, the model's own SQL found seven.
- **The tool list is pinned by tests.** deepagents adds filesystem tools and a general-purpose subagent with every tool;
  `harness.py` strips both, and the next library upgrade is free to add more.
- **The SQL path has four layers** (`docs/SQL_AGENT.md`): the catalog is the allowlist, the regenerated sqlglot AST is
  what executes (never the model's string), a read-only transaction with a timeout, and cited rendering.
- **Ask's SQL runs on the owner pool, a superuser**, so the catalog is the only guard. Adding a table to it is a security
  decision. Running it as the caller is branch `fix/ask-sql-runs-as-caller`, not merged.
- **Tools never raise, and every row is cited.** A raised exception aborts the run; a returned error lets the model adapt.
  An uncited row makes an uncitable answer.
- **The answer audit never blocks or edits** — the answer has already streamed when it runs. It appends a caveat.

## 4. Sangam Import / Scout

Generated detail (agents and their tools, middleware, skills, frontend): [sangam-import-scout](../openwiki/architecture/sangam-import-scout.md).

> `docs/INGEST.md` predates #192–#197 and is wrong in places (its header lists where).

- **The person makes every choice.** `choose_sources` comes before any read, and `RunSources` refuses a read outside it;
  `run_import_now` and every catalog-writer `promote_research` pause too.
- **The supervisor never reads the web or writes catalog rows.** Researchers read; `writer.py` writes, always with fixed
  SQL. The model never writes SQL here.
- **The brief is the record** (`source-archive/entities/<slug>.md`, no table). Every run merges into it by `fact_key`; the
  later run wins unless the earlier source is stronger. Facts no column can hold stay in the brief only. Promotion reads
  the merged brief, not one research row, and every fact ends in a stated outcome — nothing is dropped silently.
- **The pull skills are the researcher's contract.** `save_research` refuses a save that leaves a field with neither a
  finding nor a gap. Constraints never live in skills, because loading a skill is the model's choice.
- **A subagent inherits no filesystem limits.** Each one carries its own `filesystem(...)` middleware, or it gets all
  eight tools, including writes to real disk. A test walks the compiled subagent graphs.
- **Geography is a closed list.** The matcher never creates a place; a weak near-match is held, not guessed.
- **Undo replays `catalog_writes` newest-first**, and refuses when a row has changed since.
- **Tools run on the owner pool**, so each checks `chat_scope` itself; private findings are stripped for non-staff.
- **Scout is for staff and stewards only.** `require_scout` refuses everyone else (403) on the `/ingest` agent route
  and every `/api/ingest` route, before a thread is claimed; the sidebar link and `/import` are hidden from them too.

## 5. Funder Match

Generated detail (criteria, points, tiers, saved runs): [funder-match](../openwiki/architecture/funder-match.md).

- **Judged in code, not by a model.** Two model-judged versions came first and were removed for running ~35 open-ended
  queries per subagent. A rule change is `rules.py`; a point value or tier is `rubric.py`.
- **Unknown is not zero.** An unknown criterion leaves both earned and possible points; a funder sharing no place and no
  theme gets no score.
- **Theme compares the taxonomy tree**, not Darpan's sector tags.
- **A saved run is written by the people responsible for the org** — staff, or the org's admins and stewards — and no
  role may update or delete one.

### RFP Watch

Plans: [2026-10-15-rfp-watch](features/2026-10-15-rfp-watch.md), [2026-10-19-rfp-watch-scout](features/2026-10-19-rfp-watch-scout.md).

- **Supply is a fixed pipeline, not an agent** (`app/ingest/calls/`, `make calls-pull`): per funder, one search of
  its own domain, a Haiku pick of one page, a Haiku extraction, and `writer.write_rfp`. Every page passes `check_url`
  first, so robots.txt and the source registry decide, as in Import.
- **The pinned list is read first and never skipped** (`calls/pinned.json`); a dead end there is a "Needs a look"
  line, and its `note` records what a person found, so it is not rediscovered each run.
- **No column of its own.** A call goes into `rfps`, `rfp_locations` and `rfp_tags`; a re-run reads a funder's
  page again from the newest call *the pull* wrote (`extractor_version` = the calls prompt's), so a page that held
  no call is searched afresh, and a call Scout's research wrote, which names a report, never becomes the calls page.
- **Only a call with a future deadline is written.** Past and undated calls are reported, not stored.
- **Scout starts the pull; it doesn't do it.** `run_import_now(sources="funder_calls")` is the news pull's shape: no
  `choose_sources`, no researcher, one approval card naming the funders, then `calls.pull.run`'s report. No new tool,
  subagent or interrupt, so Scout's tool set is unchanged. Staff only (`staff_only`). The CLI stays for staging.
- **A call reaches an org through a shared domain, in one SQL insert** (`repositories/rfps.py::flag_matches`):
  both sides' tags roll up through `tags.parent_id` to a `domain`, and only orgs with members get rows. No score and
  no match-v2: a call says little about place, size or eligibility that a person can't read faster on the card.
- **Rows exist before anyone acts**, because `rfp_matches` RLS allows UPDATE only; Save and "Not for us" are an
  update to `saved` / `dismissed`, open to the org's members and admins and staff.
- **`rfp_matches.status` belongs to the NGO**; matching inserts with `ON CONFLICT DO NOTHING`, so a re-run never
  changes it. A saved call stays in the feed after it closes.
- **The screen asks the server once per org** (`features/ask/views/RfpWatchView.tsx`): the buckets, search and theme
  filter all narrow that one feed in the browser, and the buttons show only when `can_act` says RLS would allow them.
  "Ask about this call" fills a new chat's composer and sends nothing.

### Proposals: file readers

- **A ticked file is either the org's upload or a public page Sangam saved about it.** Step 2 lists every `documents`
  row linked to the org, and most are Import's archives (`source-archive/`, `.md` pages and PDFs), not Doc Vault
  uploads. So the file reader's one tool, `read_org_file`, opens both: a vault file through `vault.read`, cited
  `[vault:<id>#…]`, and a public copy through `_archived`, whose facts are web facts citing the page's own link.
  `RunSources` still lets a reader open only the one document it was given.
- **A reader sees a file one window at a time, and forgets old windows.** Every read is cut at `MAX_CHARS` and names
  where to carry on (a text page by `[line N]`); the reader saves facts as it goes, and `clear_old_tool_results`
  drops all but the last five windows past 60k tokens. The chat never holds a file: only each reader's closing note
  reaches it.
- **Pitch reads, it never fetches.** A `documents` row with no stored copy (a bare link) has nothing to read, so step 2
  does not list it, and Pitch neither pulls the web for it nor writes `documents`. A reader given one ticked earlier
  says "upload the file instead".

### Proposals: secondary research

- **Two readers, two rules.** The facts a proposal's parts cite come from the public researcher (a deep agent whose
  every page passes `check_url`, so robots.txt and the source registry decide, and whose facts code traces). The brief
  on the Secondary research card comes from one call with Anthropic's own web search and fetch
  (`app/proposals/brief.py`), outside `check_url`: it only cites links, never reaches the proposal text, and
  Anthropic's fetcher follows robots.txt itself. Chosen 2026-10-22 because the guarded reader could not open the
  sources a good brief needs (NFHS, the Census, NITI, journals).
- **The brief's task never names the organisation.** Server-side search cannot be filtered by `PublicGuard`, so the
  name, the org's files and the fact list are never given to it.
- **The card's buttons start the search, not the chat.** `POST /api/proposals/{id}/research` claims the run under
  the row lock and runs it in the background (`readers.search`). Through the chat, Sangam Pitch could decline to
  retry after interrupted runs, and a search outlasting the chat's stream (about five minutes) left no reply.
  Asking Pitch in words still runs it through `read_files`.
- **A supervisor splits public research; no number caps it.** `readers.BUILT.public` is a deep agent with only
  `task`: it picks the angles that fit the proposal and launches one `public-researcher` per angle, all at once
  (`prompts/public_supervisor.md`). Each researcher is isolated, so it carries its own `RunSources` and `PublicGuard`;
  `ResearchProgress` adds the run's task to every angle and writes each one's line to `readers.public.slices`. All
  share one `PublicRun` (contextvars copy into each parallel task), so a page one read is quotable by any. Chosen
  2026-10-22 over a fixed split in code: the split depends on the proposal and the person's focus.

## 6. Media & Signals

Generated detail: [media-and-signals](../openwiki/architecture/media-and-signals.md).

- Classification is cheap (Haiku); grouping into stories needs Sonnet. The verifier is a bounded deep agent, off until
  `NEWS_VERIFY_MAX` is above 0.

## 7. Data

Generated detail (table groups, buckets, migration list): [data-and-migrations](../openwiki/architecture/data-and-migrations.md),
and [writing a migration](../openwiki/workflows/writing-a-migration.md).

- **Baseline plus migrations.** Schema changes go only in `db/migrations/`; they are not automatic, and the managed DB is
  migrated by hand after a backup.
- **Provenance on every scraped or extracted table** (`source_url`, `source_name`, `fetched_at`, `content_hash`,
  `extractor_version`): every field traces to a source.
- **Storage is global, not per environment**: a local backend still writes to the cloud bucket.
- `proposals` exists but nothing uses it; proposals live in the browser.

## 8. Auth, roles and RLS

Generated detail: [auth-roles-rls](../openwiki/architecture/auth-roles-rls.md).

- **Two pools.** REST runs as the caller (`CallerPool` sets the role and JWT claims per transaction, so RLS applies).
  Agent tools, Import, the matching reader and seeds run on the **owner** pool, a superuser, and check access themselves.
- **RLS is on for every table** (`0027`); a new table needs its policies in the same migration.
- Not built yet: Phase 2 of `features-plans/access/auth-plan.md` (email-domain matching, join requests).

### Who may do what

One row per action. A ✓ means the request succeeds for that caller in their own organisation. A member, admin or
steward never reaches another org's private rows. **Gate** is what refuses everyone else, route first, then RLS.
`tests/test_permission_table.py` fails when a route uses a gate this table does not name, or has no gate and is not
listed as open.

| action | anon | member | admin | steward | staff | gate |
|---|---|---|---|---|---|---|
| read the Registry, profiles, funders, programs, RFPs, news on a profile | ✓ public | ✓ | ✓ | ✓ | ✓ all | none (`get_current_user`) + RLS `*_read`: `is_public` or `app.my_org_ids()` |
| read `/me` | ✓ empty | ✓ | ✓ | ✓ | ✓ | none |
| read an org's private rows (contacts, documents, proposals) | — | ✓ | ✓ | ✓ | ✓ | RLS `app.my_org_ids()` |
| read Funder Match | — | ✓ | ✓ | ✓ | ✓ | `require_principal` + RLS `funder_matches_read` |
| read RFP Watch | — | ✓ | ✓ | ✓ | ✓ | `require_user` + RLS `rfp_matches_read` |
| read Media & Signals | — | listed | listed | listed | ✓ all | `require_principal` + RLS `news_stories_auth` |
| read your own chat history | — | ✓ | ✓ | ✓ | ✓ | `require_user` + RLS `threads_read` |
| save a Funder Match run | — | — | ✓ | ✓ | ✓ | `require_principal` + RLS `app.my_match_org_ids()` (`0042`) |
| start or edit a proposal | — | — | ✓ | ✓ | ✓ | `require_principal` + RLS `app.my_match_org_ids()` (`0048`) |
| chat with Sangam Pitch | — | 403 | ✓ own | ✓ own | ✓ own | `proposal_chat_access`, then `CallerScope.can_edit_proposal` |
| upload to the Doc Vault | — | ✓ | ✓ | ✓ | ✓ | `require_user` + RLS `documents_insert` (`0048`) |
| delete a Doc Vault upload and its file | — | — | — | — | ✓ | `require_staff`; owner pool (no RLS DELETE policy) |
| add or edit a contact | — | ✓ | ✓ | — | ✓ | `require_user` + RLS `app.my_writable_org_ids()` |
| save or dismiss an RFP match | — | ✓ | ✓ | — | ✓ | `require_user` + RLS `app.my_writable_org_ids()` |
| adjust a fit score | — | ✓ | ✓ | — | ✓ | `require_user` + RLS `app.my_writable_org_ids()` |
| add, change or remove org members | — | — | ✓ | — | ✓ | `require_user` + the `app.*` member functions (`0028`) |
| chat with Ask Sangam | — | ✓ own | ✓ own | ✓ own | ✓ own | `ask_access`; its SQL runs as the caller |
| use Scout: chat, research, save research | — | — | — | ✓ | ✓ | `require_scout`, plus `chat_access` on `/ingest`; tools check `chat_scope` |
| Import pipeline: sources, runs, queue, workbooks, undo, delete research | — | — | — | — | ✓ | `require_scout` + `require_staff` |
| hide a news story, plan a news run | — | — | — | — | ✓ | `require_staff` |

Someone else's chat is 404 to post in, staff included; staff read it over REST.

**Known inconsistency:** the three writes on `app.my_writable_org_ids()` (`0024`: member and admin) exclude stewards,
and the two on `app.my_match_org_ids()` (`0042`: admin and steward) exclude members. Example: Ravi, a steward, can
save a Funder Match run and write the proposal, but cannot save the RFP he found for the same org. This is recorded,
not fixed: changing it is a migration and a product decision.

## 9. Frontend

Generated detail (routes, features, workspace views): [frontend](../openwiki/architecture/frontend.md).

- `app/` holds routes only; everything else goes in `features/`.
- **A screen Back should undo lives in the URL as a `pushState` entry**: Ask's `?view=`, `?thread=` and `?proposal=`,
  Import's `?thread=`, a profile's `?tab=`. Filters (Registry, Funder Match's `?org=`) use `replaceState`, so Back leaves
  the page rather than undoing each one. Native `history` calls, not `router.push`: `/ask` is `force-dynamic` and a
  router navigation refetches it. An in-app back link names its parent URL; it never calls `history.back()`.
- **Proposals live in `localStorage`** only, started from a Funder Match card; drafting and assembly are not built.
- **Every list page uses `ListPage.tsx`'s pattern**, not its own pills or stats.
- **The design system is the system of record**; a UI PR updates it (`docs/DESIGN_SYSTEM.md`). Styles in classes,
  icons from Lucide.

## 10. Models and settings

Generated detail (every setting and default): [platform](../openwiki/architecture/platform.md),
[environments](../openwiki/operations/environments.md).

- **Models are tiered by how hard the work is**: Opus reasons once per turn, Sonnet reads long pages in parallel, Haiku
  does fixed-shape work. Defaults are written only in `core/config.py`.
- **`MAX_PARALLEL_RESEARCH` is the only placeholder substituted into a prompt**, because a number frozen in prose made the
  setting decorative. The pool size moves with it; Supabase allows 60 connections across every instance.

## 11. Deploy, tracing, performance

Generated detail: [deploy-and-vendors](../openwiki/operations/deploy-and-vendors.md),
[deploying by hand](../openwiki/workflows/deploying-by-hand.md).

- **Nothing deploys automatically.** Every push to twenty branches once built both projects, 40 deployments in a day.
- **Both functions run in `bom1`, beside the database.** In `iad1` a 2 ms query cost ~1.2 s.
- **Both may run 1800 s**, and the backend's limit and the copilotkit route's `maxDuration` must match.
- **Known regression:** #178 dropped `emit_raw_events=False` from both agents (`core/lifespan.py`). Raw events stream
  again: one answer was 1.69 MB with them, 107 KB without.
- Tracing settings that look optional are load-bearing (CLAUDE.md, "Tracing config").
- **The pool's limits are written down** (`db/checkpointer.py::make_pool`, settings in `core/config.py`):
  - A request waits `DB_POOL_TIMEOUT_S` (10 s) for a connection, then fails.
  - A new connection gets `DB_CONNECT_TIMEOUT_S` (5 s).
  - Every checkout is checked, because a thawed Vercel instance can hold sockets the pooler closed.
  - Every REST statement stops after `DB_STATEMENT_TIMEOUT_MS` (15 s). Ask's executor sets a lower one.
  - `/health` shows the pool's counts.
- **The checkpointer's tables are migrated by `make migrate`, never at boot.**
  - Boot only checks the version and refuses to start when it lags.
  - Before this, `saver.setup()` ran DDL on every cold start, 3,771 times.
  - Concurrent cold starts after a langgraph upgrade would have raced each other on its version table.

## 12. Knowledge graph

Optional; on only when `NEO4J_URI` and an OpenAI key are both set, and imported lazily so the app boots without it.
**Nothing may live only in the graph** — `make graph-seed` rebuilds it from Postgres.

## 13. Deeper docs

| Doc | Read when |
|---|---|
| [`openwiki/quickstart.md`](../openwiki/quickstart.md) | you need a fact about an unfamiliar area (generated; source wins) |
| `docs/SQL_AGENT.md` | changing the SQL tools, catalog, validator or executor |
| `docs/INGEST.md` | Import's sources, access rules, amounts and fiscal years (check its stale-list header first) |
| `docs/SKILLS.md` | how skills are discovered and loaded, for either agent |
| `docs/DATA_PLATFORM.md` | the v3 data model and why it is shaped this way |
| `docs/DESIGN_SYSTEM.md` | any UI change |
| `docs/features/*.md` | the plan behind a feature; check `CHANGELOG.md` → "Not finished" before trusting a plan's status |
| `db/migrations/README.md` | writing a migration |
