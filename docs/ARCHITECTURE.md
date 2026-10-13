# Architecture

How Sangam works **today** (verified against `master` @ f7a8614, 2026-10-13). One section per subsystem:
what it is for, its files, how a request moves through it, and the rules that must not break. Read the
section for the area you are changing before opening its code; open the code only for what this does
not answer. How each piece got here is `docs/HISTORY.md`.

**Keeping it true:** a PR that changes a section's facts (a tool, a table, a route, a flow) edits that
section in the same PR. A wrong line here is worse than no line, because agents trust it.

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

- **Two agents, one backend.** Ask Sangam answers questions over the catalog. Sangam Import (named
  "Sangam Scout" on screen) researches organisations on the open web and writes what it finds into the catalog.
- **Two paths from frontend to backend.** Server components call REST through `frontend/lib/api/client.ts`.
  The chat posts to `/api/copilotkit/[[...slug]]`, which proxies AG-UI to `/agent` (agent `sangam_agent`)
  or `/ingest` (agent `sangam_ingest`). `AGENT_URL` ends in `/agent`; the REST base is it minus `/agent`.
- **Postgres is the system of record.** The graph and the published briefs can both be rebuilt from Postgres and
  Storage.
- **Local** is Docker (`make up`): frontend :3000, backend :8010, Postgres :5433, Neo4j :7474/7687.

## 2. Backend layout

```
backend/app/
  main.py          create_app(); /health; AuthMiddleware → CORS; InsufficientPrivilege → 403
  core/            config (Settings) · security (auth) · lifespan · logging · egress (guarded_client)
  db/              pool (CallerPool = PoolDep, owner pool = get_pool) · checkpointer · migrate · replicate
  api/             router.py (17 routers under /api) · deps.py (paging) · routes/<resource>.py
  repositories/    hand-written SQL, one module per resource (no ORM)
  schemas/         Pydantic, one module per resource
  agent/           Ask Sangam: build · harness · middleware · audit · models · prompt · instructions.md · skills/ · tools/
  ingest/          Sangam Import: agent · instructions.md · prompts/ · skills/ · tools/ + the pipeline modules · news/
  matching/        Funder Match: rubric · rules · assessment · match · service · run
  integrations/    graphiti (Neo4j) · tracing (Langfuse v4) · storage (Supabase Storage)
```

**A REST resource is three files.** Each has a router in `api/routes/<r>.py`, SQL in `repositories/<r>.py` and
Pydantic models in `schemas/<r>.py`, plus one line in `api/router.py`. `routes/profiles.py` is the one exception:
it composes other routes into one response per registry profile page.

**REST routes** (all under `/api`):

| Router | Main endpoints |
|---|---|
| `orgs` | list · `/{slug_or_id}` |
| `org_members` | `/orgs/{id}/members` GET/POST/PATCH/DELETE (admins of that org, staff) |
| `funders` | list · `/{slug_or_id}` · `/{id}/scores` · `/{slug}/brief` (signed Storage URL) |
| `profiles` | `/orgs/{slug}/profile`, `/funders/{slug}/profile` — one call per profile page |
| `funder_matches` | `GET ?org=` latest run · `/{id}/detail` · `POST /runs?org=` |
| `partner_lines` | list · `/{id}` (grants are `funder_activity` partner lines) |
| `programs`, `rfps`, `contacts`, `scores` | list/detail; RFP match PATCH, contact POST/PATCH, score adjustments |
| `meta` | `/stats`, `/tags`, `/locations` |
| `news_stories` | `/news/stories` (keyset-paged) · `/orgs/{slug}/news` · `/funders/{slug}/news` · hide (staff) |
| `documents` | Doc Vault list · signed upload URL · record upload · `/{id}/file` |
| `ingest` | staff: sources, proposals, runs, queue, workbooks, undo, delete research · anyone signed in: overview, research, review, coverage, save, threads, ask-live |
| `news_runs` | `/ingest/news-runs/plan` (staff; what a pull would cost, writes nothing) |
| `me`, `threads` | the caller and their org roles · the caller's Ask chats and messages |

`lifespan.py` adds `POST /agent` and `POST /ingest` itself (`_add_agent_route`). The agents are built on
the **first chat turn**, not at boot (`load_agents()`, under a lock). A REST module must import agent code
inside the function that uses it, never at the top of the file. At boot, lifespan only opens the pool, checks the SQL catalog
against the live schema (it **raises** on drift), opens the graph if one is configured, and opens the checkpointer.

## 3. Ask Sangam

**What it is:** a deep agent (`app/agent/build.py`, `create_deep_agent`) that answers questions over the
catalog by writing its own SQL. Every fact in an answer carries a citation.

**Tools: exactly seven**, plus two for reading skills:

| Tool | Does |
|---|---|
| `db_list_tables`, `db_describe_table`, `db_profile_column`, `db_query` | schema discovery and a model-written SELECT (`tools/sql_tools.py`) |
| `search_graph` | Graphiti search; says "use the database tools" when the graph is off |
| `fetch_url` | one live page through `guarded_client`; uncapped; carries no citation marker |
| `compare_fit` | Funder Match — fixed SQL + code rules (§5); refuses callers who may not run a match |
| `read_file`, `ls` | read `/skills/` only (`harness.filesystem(keep=SKILL_READING_TOOLS)`) |

There are no subagents and no `task` tool. `harness.install()` turns off deepagents' general-purpose
subagent for every provider, and `harness.filesystem()` strips the six writing filesystem tools. Tests pin both.

**Skills** (`app/agent/skills/`, read on demand): `funder-matching`, `funder-comparison`,
`funder-shortlist-brief`, `news-brief`.

**Middleware, in order:** filesystem → `sql_retry_limiter` (5 failed `db_query`s end the turn) →
`clear_old_tool_results` → `answer_audit`. The audit is on by default, runs on Haiku, and checks grain, filters, false zeros
and numbers. On a problem it appends a "⚠️" caveat. It never blocks or edits the answer. It also scores the run `answer_audit` in Langfuse.

**The SQL path has four layers** (full design: `docs/SQL_AGENT.md`):
1. `sql/catalog.py` is the allowlist, as data: **37 tables**. A column not listed does not exist for the
   agent. `defects` attach data caveats to every result that touches a table. **22 tables** are
   `KNOWN_EXCLUDED`: checkpoints, users, org_members, threads, research and import tables, news scoring,
   funder_matches, proposals, schema_migrations. Adding a table is a security decision.
2. `sql/validator.py` (pure): sqlglot parses the query, and the **regenerated AST is what executes**. The model's string never runs.
3. `sql/executor.py`: a read-only transaction with `SET LOCAL statement_timeout` (5 s) and `prepare=True`, at most 50 rows.
4. `sql/render.py` returns the rows with their citation markers, the data caveats and a `sources:` block.

The agent's SQL runs on the **owner pool**, which is a superuser, so the catalog is the only guard. Moving it to the caller's
role is branch `fix/ask-sql-runs-as-caller`, which is not merged.

**Prompt:** `instructions.md`, sent verbatim. Rules 1–5 cover answering, citations, freshness and scores. Rules 6–11
are about SQL: discover the schema first, profile a column before filtering on a literal, project ids, stop after five
failures, treat zero rows as an answer, and what a registration means. Rules 12–16 are about matching: `compare_fit` judges,
call it once, repeat its output, "unknown" means "not recorded".

**Citation markers:** `[org:N]`, `[funder:N]`, `[activity:N]`, `[score:N]`, `[news:N]`, `[graph:<uuid8>]`.

**Frontend:** `features/ask/` holds AskWorkspace, ChatPane, AnswerCard, TraceCard, EvidenceRail and Sidebar.
`lib/citations.ts` turns markers into chips that link to the Registry. Past chats come from `/api/threads`, which
reads the checkpointer. Signed out, `/ask` shows `AskPreview`.

**Adding an Ask tool takes four edits:** the function in `app/agent/tools/` (it never raises and cites every row), a line in
`build.py`, a mention in `instructions.md` (a test checks this), and a label in `features/ask/lib/toolLabels.ts`.

## 4. Sangam Import / Scout

**What it is:** a supervisor deep agent (`app/ingest/agent.py`, `build_ingest_agent()`) that researches funders
and NGOs from sources the person chooses. It saves cited findings, merges them into one **brief per
organisation**, and promotes the brief into the catalog when someone saves it. The route is `/import`, threads are
`import-<uuid>`, and the backend and prompts call it "ingest".

> `docs/INGEST.md` predates #192–#197 and is wrong in places (its header lists where). **Where the two
> disagree, this section wins.**

### Agents

| Agent | Model | Tools | Notes |
|---|---|---|---|
| supervisor | `MODEL` (Opus) | `list_import_sources`, `plan_import`, `run_import_now`, `import_run_summary`, `pending_resolutions`, `choose_sources`, `funder_dossier`, `compare_with_catalog`, `coverage_report`, `record_registry_check`, `publish_brief` + `read_file`, `ls`, `task`, `write_todos` | Has no web tools and never writes catalog rows itself. Plans in waves of `MAX_PARALLEL_RESEARCH` (8). |
| `entity-researcher` | `RESEARCH_MODEL` (Sonnet) | `research_goals`, `funder_dossier`, `list_library_documents`, `read_library_document`, `read_source_rows`, `search_public_sources`, `read_page`, `fetch_document`, `read_document_pages`, `save_research` | One per organisation, run in parallel. Reads its pull skill first. |
| `vault-reader` | `RESEARCH_MODEL` | `list_vault_documents`, `read_vault_document`, `research_goals`, `save_vault_findings` | Reads an org's Doc Vault before the web; has no web tools. |
| `catalog-writer` | `UTILITY_MODEL` (Haiku) | `promote_research`, `funder_dossier` | Saving from chat. Every `promote_research` call pauses for the person (`SaveQuestions`). |
| `workbook-reader` | `UTILITY_MODEL` | `read_workbook` | Returns the names in a staff spreadsheet; one researcher per name follows. |

Every subagent is `mode="isolated"` and carries its **own** `filesystem(...)` middleware. Without it,
deepagents gives a subagent all eight filesystem tools, including writes to real disk. `TestASubagentRunsOnlyTheToolsItsSpecDeclares` walks the compiled subagent graphs to check this.

**Human-in-the-loop pauses:** `choose_sources` (only when nothing was ticked before sending) and
`run_import_now` (in `INTERRUPT_ON`), plus `promote_research` (through `save_questions()` on the catalog-writer).

### One turn, end to end

1. `/import` → `ScoutChat` → `useAgentChat("sangam_ingest")`. The sources ticked in the right rail go out as AG-UI context.
2. `choose_sources` comes first. `TickedSources` fills its arguments from the ticks. The answer lives only in the checkpoint.
   `ChosenSources` blocks every `task` until it is answered. `RunSources` refuses any read outside it.
   Ticked staff workbooks become `documents` rows.
3. The supervisor reads `funder_dossier`, then plans with `write_todos`. If the vault was chosen, a `vault-reader` runs first
   (writing `vault_research`), then one `entity-researcher` per organisation.
4. The researcher confirms the organisation and its kind with one search. It reads `/skills/research/<kind>/SKILL.md`,
   then `research_goals` and `funder_dossier`, then searches and reads. `read_page` and `fetch_document` archive what they read to
   the `source-archive` bucket.
5. `save_research` is refused when:
   - `contract.unanswered()` finds a field in the kind's contract with neither a finding nor a gap. Yearly concepts need one per
     asked fiscal year (default: the last 3), and identity fields need `themes`.
   - the caller is neither staff nor a steward and the organisation is an NGO.
   - the save is shorter than the stored one and does not pass `replace=true`.
   - a non-staff caller would overwrite another person's row from the same day.
   
   On success it upserts `entity_research` on `(slug, researched_on)`, then `brief.publish()`.
6. **The brief is the record** (`brief.py`), stored at `source-archive/entities/<slug>.md`. There is no brief table. Each fact line
   carries its typed finding in a hidden `<!-- fact {json} -->` block. A new save merges into the brief by `fact_key`, and the later run wins
   unless the earlier source is stronger (evidence tier, then confidence). Facts no field can hold go in
   `<!-- unplaced -->` and **exist only in the brief**. If Storage cannot be read, the brief is left alone.
7. **Saving** happens two ways: the Review screen (`POST /api/ingest/research/{slug}/save`) or "save X" in chat (the catalog-writer).
   Both call `save_to_catalog()` (`tools/catalog_tools.py`), which runs one transaction per organisation:
   `undo.start` → `promote()` → `_record_save` → `undo.finish`. `promote()` reads `brief.promotable()` (every run merged),
   not one row.
8. **`promote()`** (`promote.py`) runs the kind's branch. For a funder:
   - resolve the entity, preferring the one an earlier save wrote to;
   - write the funder, its CSR years and its tags;
   - write a `documents` row for **every public source a fact cites**;
   - write programmes parents-first (a held parent holds its children), and spend lines as `kind='component'` programmes;
   - write the facts in `WRITE_ORDER`;
   - write `document_links` (owner, programme, FY, pages).
   
   Every fact ends in one state: written, confirms, conflicts, waiting, kept, skipped, held or no column. Those states are written back into the brief.
9. **Undo** (staff): `POST /api/ingest/promotions/{id}/undo` replays `catalog_writes` newest-first. It refuses if a row has
   changed since. 19 tables are logged (`undo.LOGGED`).

### The writer and matcher

- `writer.py` is the only place Import writes, always with fixed SQL; the model never writes SQL. `Gate` sorts each fact into five cases: same value; a newer source,
  which updates; an older or undated source, which asks; a close name, which asks update/new/skip; and new, which inserts. `Gate(plan=True)` writes nothing,
  and that is what `compare_with_catalog`, coverage and the review screen use.
- `matcher.resolve_funder` tries, in order: CIN (only if it also looks like the same organisation), exact name, alias, name variants, website
  domain, boilerplate, then trigram. The first five merge; a trigram match becomes a Review question.
- `geography.py` matches against a **closed list** (36 states and UTs, 784 LGD districts) and never creates a place. A near match is
  taken only above `NEAR_FLOOR`/`NEAR_MARGIN`; anything less is held.
- Money is always `{value, unit, text}`. Staff spreadsheet figures are checked against the cell they cite.

### Middleware (`app/ingest/middleware.py`)

- `fallback`: on failure, use the next model tier.
- `SaveRefusal`: turns a pydantic error into a short list of fixes.
- `EscalateAfterFailedSave`: after one malformed save, the rest of the run uses `MODEL`.
- `ResearchRubric`: a Haiku grader checks the save against `prompts/research_rubric.md`, allowing one revision.
- `cheap_summarizer`: Haiku writes the summaries of long runs.
- `ReadingLimit` and `call_limit` apply only if `RESEARCH_PAGE_LIMIT` / `RESEARCH_MODEL_CALL_LIMIT` are set; neither is set by default.
- `StaffLastLock`: once a staff spreadsheet is read, only a short allowlist of tools stays open.
- `CallerNote`: tells the model what this caller may do.
- `DropFilesOnExit`: the vault-reader's files never reach a researcher.

### Skills (`app/ingest/skills/`)

- **What to pull:** `research/funder-intake-research` and `research/ngo-credential-research`. These are the researcher's contract, and
  only the researcher sees them.
- **What to produce:** `entity-record`, `funder-scan-for-fundraisers`, `ngo-brief-for-funders`.
- **What the catalog did:** `catalog-mapping`, `catalog-write-report`.

The supervisor indexes five. Constraints never live in a skill, because loading a skill is the model's choice.
Mechanism: `docs/SKILLS.md`.

### Access

Anyone signed in may use Import. Tools run on the owner pool, so each one checks `chat_scope` itself
(`ingest/caller.py`), and private findings (staff and vault sources) are stripped for non-staff. Pipeline
routes are `require_staff`. Every fetch of a model-supplied URL goes through `guarded_client`, which refuses private,
loopback and metadata addresses on every redirect.

### Frontend (`features/ingest/`)

- Layout: `ImportView` → `ScoutChat`, with `StepBar` (Start → Working → Review → Done), `ScoutRail` and `ScoutRunPanel`.
- Pauses: `SourcesCard` (the `choose_sources` pause), `ImportApproval` (`run_import_now`), `SaveQuestions`/`ReviewCard`.
- Panels: `ScreenReview`, `DoneReport`, `ResearchedRecently` (undo and delete).
- One call, `GET /api/ingest/overview`, fills the page's panels.
- Research brief page: `/registry/funders/[slug]/brief` fetches the signed URL from the profile, then `parseBrief` → `BriefArticle`.

## 5. Funder Match

**What it is:** a score of one org against funders, judged **in code** under the **match-v2** rubric. No model is involved.

- `repositories/matching.py` loads an `OrgProfile` and `FunderProfile`s with fixed SQL, in a read-only transaction.
  `may_run()` allows staff, or an admin or steward of the org.
- `matching/rubric.py` (`RUBRIC_VERSION = "match-v2"`):

  | Criterion | Points |
  |---|---|
  | theme | 25 |
  | geography | 15 |
  | population | 15 |
  | eligibility | 20 |
  | relationship | 10 |
  | funding size | 10 |
  | capacity | 5 |

  Tiers: strong ≥ 75, medium ≥ 55, otherwise weak. A criterion that is unknown is left out of both
  the earned and the possible points. A funder sharing no place and no theme gets **no score**.
- `matching/rules.py` (pure, no I/O) judges each criterion; a criterion's status is computed from its points. Theme compares the **taxonomy
  tree**, not Darpan's sector tags: a tag brings its ancestors, and a sub-theme brings its Schedule VII clauses. The finest level both sides share sets the points: theme 25, clause 15, domain 10.
- `matching/match.py` builds the card lines, the summary and "what would raise the score" from templates.
- Where it is used:
  - **In Ask:** `compare_fit`, guided by the `funder-matching` / `funder-comparison` / `funder-shortlist-brief` skills.
  - **Saved runs:** `service.run_and_save()`, called by `POST /api/funder-matches/runs?org=` and by `make match`. It reads as the owner and writes as the caller, every funder in one transaction.
    `0042`'s RLS lets only staff and the org's admins and stewards insert, and members read. No role may update or delete a run.
  - **Page:** the Ask workspace's Funder Match view (`features/ask/views/FunderMatchView.tsx`), built on the list pattern, with a Rerun button.
- To change a rule, edit `rules.py`. To change a point value or a tier, edit `rubric.py`.

## 6. Media & Signals

- Pipeline: `app/ingest/news/`. `run_import_now` with the `tavily_news` source, or `make news-pull`, runs Tavily
  searches per subject or feed. Then:
  - Haiku classifies each item's entity, topic and headline.
  - Sonnet groups items into stories.
  - Visibility bars decide what is shown.
  - Results go to the seven `0044_news` tables (`news_stories`, `news_links`, …).
- The optional verifier (`news/verify.py`) is a bounded deep agent that re-reads borderline matches. It is off while `NEWS_VERIFY_MAX=0`.
- On screen: the Media view in the Ask workspace (buckets org / funder / general, plus filters) and "In the news" on profiles.
  In Ask, the `news-brief` skill answers with `[news:N]` citations.

## 7. Data

- **Baseline plus migrations.** `db/init/` (`02_schema.sql`) is what a brand-new database gets. Every change since is in `db/migrations/`
  (**48 files**, two of them numbered `0044`). Migrations are **not automatic**: run `make migrate` (`ENV=staging` for the
  managed DB, after a backup). The backend refuses to boot when the SQL catalog and the schema disagree.
- **Table groups:**

  | Group | Tables |
  |---|---|
  | CSOs | `orgs`, `org_identifiers` (with a status), `org_locations`, `org_tags`, `org_financials`, `metrics`, `programs`, `program_tags`, `contacts` — evidence tier (`source_type`, `evidence`) on each |
  | Funders | `funders`, `funder_activity` (spend, footprint, partner lines; a grant is a partner line `[activity:N]`), `funder_csr_years`, `funder_locations`, `funder_tags` |
  | Taxonomy | `tags` (every vocabulary, by `kind`: domain → theme → sub_theme, csr_sector, sdg, …), `tag_links` |
  | Geography | `locations` (LGD, closed list), `location_designations` |
  | Documents | `documents`, `chunks` (pgvector), `document_links`, `extraction_log` |
  | Import | `entity_research`, `vault_research`, `ingest_runs`, `ingest_run_items`, `resolution_queue`, `ingest_source_proposals`, `promotions`, `catalog_writes` |
  | Scores and RFPs | `rubrics`, `rubric_criteria`, `fit_scores` (a human rater's score), `fit_score_items`, `score_adjustments`, `rfps`, `rfp_*`, `reference_figures` |
  | Match | `funder_matches`, `funder_match_details` |
  | News | `news_stories`, `news_links`, `news_link_scores`, `news_story_*`, `news_watch` |
  | Access | `users`, `org_members`, `threads` |
  | Infrastructure | `schema_migrations`, LangGraph `checkpoint*` |

- **Provenance** columns go on every scraped or extracted table: `source_url`, `source_name`, `fetched_at`, `content_hash`,
  `extractor_version`.
- **Storage buckets:**
  - `source-archive`: every fetched document, page text, and `entities/<slug>.md` briefs.
  - `org-vault`: what orgs upload to their Doc Vault.
  - `staff-sources`: staff spreadsheets, readable only by staff.
  
  Storage is global, not per environment: a local backend still writes to the cloud bucket.
- `proposals` exists (from `0009`) but nothing uses it. Proposals live in the browser (§9).
- Full model and its history: `docs/DATA_PLATFORM.md`, `db/migrations/README.md`.

## 8. Auth, roles and RLS

- `core/security.py`: `AuthMiddleware` verifies the Supabase JWT against the project's JWKS and finds or creates the
  `users` row.
  - No header means anonymous.
  - With `SUPABASE_URL` unset, every request is the seeded dev user, who is staff.
  - `DEV_AUTH=1` accepts `Bearer dev`, which `make smoke` relies on.
- Dependencies:
  - `require_user` / `require_principal` return 401 for anonymous callers.
  - `require_staff` returns 403 for non-staff.
  - `request_scope` / `CallerScope` decide what a caller may read, research and save.
  - `chat_access` gates `/agent` and `/ingest`. Someone else's thread is 404 unless the caller is staff.
- **REST runs as the caller.** `PoolDep` (`CallerPool`) sets `role` (`anon`/`authenticated`) and the JWT claims in each
  transaction, so RLS applies. `get_pool()` is the **owner** pool, a superuser. These use it: agent tools, Import, the matching reader and seeds.
- Roles:
  - `users.is_staff`.
  - `org_members.role` ∈ `admin` / `member` (one org each) and `steward` (many orgs; reads their private data).
- In SQL: `0023` creates the DB roles, `0024` the `app.*` access functions, `0025` the grants, and `0027` turns RLS on for every table. `0028` lets admins manage members. Later migrations add their tables' policies.
- Frontend: `lib/api/auth-headers.ts` (browser) and `auth-headers.server.ts` (server) send the Supabase token as Bearer.
  `proxy.ts` sends a signed-out visitor to `/import` on to `/auth/login?next=`.
- Not built yet: Phase 2 of `features-plans/access/auth-plan.md` (email-domain matching, join requests).

## 9. Frontend

- `app/` holds **routes only**:
  - `/` — home
  - `/ask` — workspace, or the preview when signed out; `?view=import` redirects to `/import`
  - `/import` — Scout
  - `/registry`, `/registry/[slug]`, `/registry/funders/[slug]`, `/registry/funders/[slug]/brief`
  - `/resources/[tab]` — methodology, taxonomy
  - `/settings`, `/terms`, `/auth/*`
  - `/api/copilotkit/[[...slug]]` — `maxDuration` 1800
  - plus redirect-only legacy paths
- `features/` holds one folder per screen: `ask`, `auth`, `home`, `ingest`, `registry`, `resources`, `settings`, `taxonomy`, `terms`.
- **Ask workspace views are in-app state, not URLs:** ask, chats, funder-match, proposals, rfpwatch (a
  placeholder), vault, media.
- **Proposals** are kept in the browser only (`localStorage` key `sangam.proposals.v1`) and are started from a Funder Match card.
  Built so far: steps 1–2. Drafting and assembly are not built.
- `components/ui/` holds display primitives and `ListPage.tsx` (`BucketCards`, `FilterRow`, `SearchBox`, `ListMore`). Every
  list page uses that pattern. `components/layout/` holds Nav and Footer.
- `lib/` holds `api/` (`client.ts`, types, auth headers), `supabase/`, `AgentProviders.tsx`, `useAgentChat.ts`, `format.ts` and `safe-next-path.ts`.
- Signed-out GETs are cached by Next (`revalidate 300`) in production. A profile page makes one backend call.
- **Design rules:**
  - The Claude Design project "Sangam Design System v2" is the system of record, and a UI PR updates it.
  - Styles go in classes in `globals.css`, not `style={{}}`.
  - Icons come from Lucide.
  - Cross-folder imports use `@/`.
  
  See `docs/DESIGN_SYSTEM.md`.

## 10. Models and settings

| Setting | Default | Used by |
|---|---|---|
| `MODEL` | `anthropic:claude-opus-5-5` | Ask, the Import supervisor, escalation |
| `RESEARCH_MODEL` | `anthropic:claude-sonnet-5-5` | entity-researcher, vault-reader, news grouping and verifier |
| `UTILITY_MODEL` | `anthropic:claude-haiku-4-5` | catalog-writer, workbook-reader, rubric grader, summaries, news classification |
| `SQL_AUDIT_MODEL` | `anthropic:claude-haiku-4-5` (`off` disables) | Ask's answer audit |
| `MAX_PARALLEL_RESEARCH` | 8 | researchers per wave; the only placeholder substituted into a prompt |
| `DB_POOL_MAX_SIZE` | 10 | concurrency gates derive from it (`max(2, pool − 3)`) |
| `RESEARCH_PAGE_LIMIT`, `RESEARCH_MODEL_CALL_LIMIT` | unset | optional caps on a researcher |
| `NEWS_VERIFY_MAX` | 0 | news verifier off |
| `RECURSION_LIMIT` | 200 | both agents |

Defaults are written only in `core/config.py`, and a blank value means the default. A deployed backend reads these settings from
its Vercel env. The MCP settings (`github_*`, `playwright_mcp_url`, `mcp_servers`) do nothing: `agent/tools/mcp.py` is
imported nowhere. `TAVILY_API_KEY` *is* used, by Import's `search_public_sources` and the news pipeline.

## 11. Deploy, tracing, performance

| Piece | Host |
|---|---|
| Frontend | Vercel project `sangam` (root `frontend`) — https://sangam-six-beta.vercel.app |
| Backend | Vercel project `sangam-backend` (root `backend`, preset fastapi) — https://sangam-backend-one.vercel.app |
| Postgres + Storage + Auth | Supabase, ap-south-1 (use the **session pooler**, port 5432; the direct host is IPv6-only) |
| Neo4j | Aura, or omitted |

- **Nothing deploys automatically.** Run Actions → Deploy on `master` by hand. Both `vercel.json` files set
  `git.deploymentEnabled: false`.
- Both functions run in `bom1`, beside the database, and may run 1800 s: the backend's `functions` and the copilotkit route's `maxDuration` must match.
  A cron in `backend/vercel.json` hits `/health` every 5 minutes to keep one instance warm.
- **Tracing** (`integrations/tracing.py`, Langfuse v4):
  - Trace roots are `sangam_ask`, `sangam_import` and `sangam_news_verify`.
  - `SessionScopedAGUIAgent` maps the AG-UI thread to a Langfuse session, de-dupes re-sent tool results and flushes after every run.
  - FastAPI's own OTel spans are off.
- **Known regression:** #178 dropped `emit_raw_events=False` from both agents (`core/lifespan.py`). Raw events stream
  again: one answer was 1.69 MB with them, 107 KB without.
- `make smoke` checks the wiring end to end, and `make evals` runs golden questions through the real agent (this costs money).
- `docs/DEPLOY.md` describes a container-host setup that was never used; the table above is the live one.

## 12. Knowledge graph

Optional. It turns on only when `NEO4J_URI` and an OpenAI key are both set.
- `integrations/graphiti.py` imports `graphiti_core` lazily, so the app boots without it.
- `make graph-seed` (`seed/graph_seed.py`) rebuilds the graph from Postgres episodes: funder and org profiles, partner lines and vetting notes.
- Nothing may live only in the graph.

## 13. Deeper docs

| Doc | Read when |
|---|---|
| `docs/SQL_AGENT.md` | changing the SQL tools, catalog, validator or executor |
| `docs/INGEST.md` | Import's sources, access rules, amounts and fiscal years (check its stale-list header first) |
| `docs/SKILLS.md` | how skills are discovered and loaded, for either agent |
| `docs/DATA_PLATFORM.md` | the v3 data model and why it is shaped this way |
| `docs/DESIGN_SYSTEM.md` | any UI change |
| `docs/features/*.md` | the plan behind a feature; check `HISTORY.md` → "Not finished" before trusting a plan's status |
| `db/migrations/README.md` | writing a migration |
