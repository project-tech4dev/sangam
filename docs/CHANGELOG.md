# Changelog

Everything that has landed on `master`, from the first scaffold (2026-09-22) to Import M4 (2026-10-13),
by subsystem and in date order within each. One line per change; a PR that touched two areas appears under both. A date is the day it merged, which is
often later than its plan doc's filename. `#N` is the PR; a short sha means a commit before PRs.

How the system looks *today* is `openwiki/` (facts) and `docs/ARCHITECTURE.md` (rules); this file is how it got there. Add a line here
in the PR that ships a change, under its subsystem.

---

## Foundation and scaffold

- 2026-09-22 · dce571d · Initial scaffold: Next.js + CopilotKit, FastAPI + LangGraph, Postgres + FalkorDB, a seeded registry, cited chat.
- 2026-09-22 · b0f89e9 · Pydantic schemas and a repository layer for the v2 model (`Page[T]`, `COUNT(*) OVER()` paging).
- 2026-09-22 · e66cb92 · Per-resource routers replace `rest.py`; targeted writes on contacts, RFP matches and score adjustments.
- 2026-09-22 · bb2a58c · Backend pytest suite on the stub-app pattern; `uv.lock`.
- 2026-09-25 · #32 · Per-environment config (`ENV=local|staging`), external Postgres, and the migration runner.
- 2026-09-26 · #50 · CLAUDE.md added; SSE route duration capped for Vercel.
- 2026-09-26 · #52 · Restructure: backend into `core/ db/ api/routes/ integrations/`, frontend into `app/` (routes only) + `features/`.
- 2026-10-01 · #63, #69 · The frontend container reinstalls npm deps when the manifests change, not on a flag.
- 2026-10-01 · #68 · Supabase auth variables read from the root `.env`.
- 2026-10-02 · #78 · `make help` is the default goal; `make seed` runs `migrate` first; README rewritten.
- 2026-10-21 · (unmerged) · Codecov's patch gate rises from 70% to 75% on both sides (the frontend's stays informational); the plan to reach 75% overall is `docs/features/2026-10-21-coverage-75.md`.
- 2026-10-21 · (unmerged) · Backend tests for Import's write path, tools and pipelines, Pitch, tracing, storage, egress and the migration runner take backend coverage from 60% to 94%; the backend's project target is now 75%.

## Data model and migrations

- 2026-09-22 · 4df88d1 · v2 normalised schema (`db/init/02_schema.sql`): locations, tags, identifiers, contacts, programs, grants.
- 2026-09-22 · 6081d57 · Seed restructured for v2: vocabularies first, then identifiers, contacts, tags, grants, programs.
- 2026-09-29 · #57 · The v3 data model as ten additive migrations `0001`–`0010`: provenance, taxonomy, geography (LGD), identity, documents, credentials, funder activity, org facts, proposals, signals.
- 2026-10-04 · #61 · `app/db/replicate.py` copies one database into another; loaded Supabase (2,104 rows, 50 tables).
- 2026-10-08 · #103 · `0031`: nine funder tables become five; spend, footprints and partners fold into `funder_activity`; eligibility and templates become `documents` rows.
- 2026-10-08 · #109 · `0033`: CSO tables gain `source_type` + `evidence`; `org_identifiers` gets a status; `credential_events` and `program_locations` dropped.
- 2026-10-08 · #110 · `0034`: grants become `funder_activity` partner lines; `grants`/`grant_locations` dropped; citations go `[grant:N]` → `[activity:N]`.
- 2026-10-11 · #160 · Places: districts matched against the LGD list instead of created; a clear nearest district is taken, anything less is held.
- 2026-10-12 · #181, #188 · Two migrations share the number `0044`; both are kept because staging applied `0044_news` first and the runner keys on file name.
- 2026-10-13 · #196 · `0046`: columns for Import's researched identity, place and partner-tier facts; `programs.kind` gains `'component'`.
- 2026-10-13 · #197 · `0047`: `document_links` — which owner, programme and year each document backs, with the pages cited.
- 2026-10-16 · #231 · `0049`: `rfp_matches.status` may be `saved` (RFP Watch). Numbered after `0048_proposal_work`.
- 2026-10-21 · (unmerged) · `0050`: proposals at step 3 or later move up one step, in `work` and `summary`, for Make a case.
- 2026-10-28 · #348 · `0051`: `GRANT DELETE ON documents` to `authenticated`, and `documents_delete`: staff only, and only a private, org-owned `vault_upload`.
- 2026-10-28 · #350 · `0052`: `GRANT DELETE ON proposals`, `proposals_delete` and `documents_delete_draft`: a proposal and its `proposal_draft` rows, for the org's admins and stewards and staff.
- 2026-10-30 · #353 · `0053`: `deleted_documents` and the `log_document_delete` trigger: every deleted `documents` row is kept, and the vault and proposal deletes move the file to `org-vault/trash/`.

Which PR brought each remaining migration: `0011`–`0019` #58 · `0020` #61 · `0021` #89 · `0022` #74 ·
`0023`–`0029` #92/#97 · `0030` #98 · `0032` #105 · `0035` #127 · `0036`–`0037` #100 · `0038` #130 ·
`0039`–`0041` #137–#139 · `0042` #142 · `0043` #162 · `0044_news`/`0045` #188 · `0044_one_read…` #181.

## Ask Sangam (the SQL agent)

- 2026-09-22 · 85e99b6 · First tools on the v2 schema: `search_orgs`, `get_funder`, `get_grants` (all later removed).
- 2026-09-23 · f052461 · Ask workspace: CopilotKit v2 headless, tool-call trace cards, `[kind:id]` citation chips, evidence rail.
- 2026-09-23 · d3b0f1d, 542d47f · Ask goes full-bleed with internally scrolling panes; mobile/tablet layout.
- 2026-09-27 · #54 · Safe text-to-SQL: the model writes a SELECT, sqlglot regenerates it, a catalog allowlists it, read-only transaction runs it; the four fixed-query tools go. `docs/SQL_AGENT.md`, `make evals`.
- 2026-10-05 · #91 · One trace, one task, a source per row: `db_query` appends provenance columns; the rail shows executed SQL and sources.
- 2026-10-08 · #122, #124 · Sidebar: collapsible Recent chats, Use Cases, a question-first new chat, Lucide icons.
- 2026-10-08 · #125 · Reopening a past chat shows its messages from any browser (`/api/threads`, read from the checkpointer).
- 2026-10-12 · #178 · Both agents are built on the first chat turn, not at boot (`load_agents()`).
- 2026-10-13 · #191 · Ask's `fetch_url` reads a page without a length cap.
- 2026-10-17 · (unmerged) · Ask efficiency M2: `compare_fit(org_id)` replies in text with the top 10 strong/medium fits in full and every other funder on one line (worst case ≈10k tokens, was one JSON line past the 20k eviction); tool-result clearing, past 60k, clears the oldest results in 20k steps (what is sent stays under 60k, the cached prefix moves once per step) and never `compare_fit`. Header counts only scored funders. Ask, Sangam Pitch and Sangam Import share it.
- 2026-10-19 · Ask efficiency M4: `fetch_url` removed, so Ask fetches no model-supplied URL (#247); `db_profile_column` errors carry their own prefix and count toward the 5-attempt limit; prompt rules that restated a tool's description shrink to a line.
- 2026-10-19 · Ask's limits in code: a question stops after `ASK_MODEL_CALL_LIMIT` (25) model calls, `compare_fit` refuses a repeat of the same arguments and a fourth call, and Ask falls back to `RESEARCH_MODEL` and summarizes on `UTILITY_MODEL` as Import and Pitch do (#248, #249).
- 2026-10-19 · Ask efficiency M3: the prompt carries the table list (`{{TABLE_MAP}}`, from `catalog.py`); `db_query` adds each table's id when none is selected, so plain rows come back cited; a one-row result shows text up to 2,000 characters; a table's caveats come in full once a turn, then as one line; the SQL that ran moves from the text to the tool's artifact (the evidence rail shows the model's SELECT).

## Knowledge graph

- 2026-09-22 · dce571d · Graphiti graph on FalkorDB in the scaffold.
- 2026-09-22 · 8847079, 6182381 · Neo4j replaces FalkorDB; `search_graph` reads Neo4j; `graph_seed.py` rebuilds it from Postgres.

## Sangam Import (on screen: Sangam Scout)

- 2026-10-01 · #58 · Import, a second agent on `/ingest`: migrations `0011`–`0019`, a typed-record writer (the model writes no SQL), 74 sources with access rules, the `/import` page. `docs/INGEST.md`, `docs/SKILLS.md`.
- 2026-10-04 · #61 · Supabase Storage (`0020`): every fetched document archived to `source-archive`; orgs upload to `org-vault`; the entity brief is published.
- 2026-10-04 · #82 · Agent architecture: the supervisor stops researching; subagents run only the tools they declare; the kind (funder/NGO) decides the tables.
- 2026-10-04 · #84 · Seven skills in three groups (what to pull, what to produce, what the catalog did).
- 2026-10-04 · #85 · Org writer: `resolve_org`/`write_org`; NGO research is promoted, not turned away.
- 2026-10-05 · #89 · `0021` funder_eligibility and the open-call field (the table was dropped again by `0031`).
- 2026-10-08 · #105 · Staff-only source workbooks: private `staff-sources` bucket (`0032`), `read_source_rows`, the staff-last lock.
- 2026-10-08 · #111 · `record_registry_check`: a staff Darpan/FCRA/MCA check, ranked as `manual_check`.
- 2026-10-08 · #112 · Give.do and GuideStar readable only on named paths; prior research pinned; egress to private addresses blocked.
- 2026-10-08 · #113 · Staff figures checked against the cell they cite; one money-unit rule (`{value, unit, text}`).
- 2026-10-08 · #117 · Staff pick workbooks from Storage through a human-in-the-loop pause (replaced by `choose_sources` in #141).
- 2026-10-08 · #120 · Five cases per funder fact: matched, newer → update, older/undated → ask, close match → ask, new → add.
- 2026-10-08 · #127 · Coverage report (`0035`): expected vs found by concept, year and field; every catalog write confirmed.
- 2026-10-09 · #130 · Guided Import, Start → Working → Review → Done (`0038`); `/import` becomes its own page with past imports.
- 2026-10-09 · #131 · Security-review safeguards pinned by tests (403 on every staff route, fixed kind map, safe links).
- 2026-10-09 · #133 · Model tiers: Opus reasons, Sonnet researches, Haiku formats.
- 2026-10-09 · #134 · Import middleware: per-tier fallbacks, escalation after a failed save, the research rubric grader, cheaper summaries.
- 2026-10-10 · #136–#139 · Import for every role: private sources stay out of briefs; opens by role; `vault-reader` reads the Doc Vault first (`0040`); who saved what and staff undo (`0039`, `0041`).
- 2026-10-10 · #141 · One pause before anything is read: `choose_sources`; `RunSources` refuses reads outside the choice.
- 2026-10-10 · #144 · Sangam Scout: Import becomes one chat thread like Ask; staff can read any org's Doc Vault.
- 2026-10-11 · #157 · Import runs may last 1800 s; re-sent tool results are dropped.
- 2026-10-11 · #158 · Ticked sources reach the supervisor as context; three refused saves accepted.
- 2026-10-11 · #162 · Import writes taxonomy tags on programmes, orgs and funders; `0043` logs them for undo.
- 2026-10-11 · #165 · Scout review fixes: one run order, `run_import_now` pauses before writing, Import canary evals, `ask-live` mid-run.
- 2026-10-12 · #166, #170 · `save_research` accepts what researchers really send; the rubric grades instead of erroring.
- 2026-10-12 · #183 · `/api/ingest/overview` returns the Import page's panels in one call (9 requests → 2).
- 2026-10-12 · #186 · `/registry/funders/<slug>/brief` renders the research brief in the app, with a PDF download.
- 2026-10-13 · #191 · No read limits: page and model-call limits unset by default; long pages evicted to a file instead of cut.
- 2026-10-13 · #192 · The brief merges every run for a slug, with full programmes; programmes must carry themes.
- 2026-10-13 · #194 · M1: the pull skills are the researcher's contract; `contract.py` refuses a save that leaves a field with neither a finding nor a gap.
- 2026-10-13 · #195 · M2: the brief is the record; saves merge by `fact_key`, and the stronger source wins.
- 2026-10-13 · #196 · M3: promotion reads the brief; every fact ends written, confirms, conflicts, waiting or held (`0046`).
- 2026-10-13 · #197 · M4: every public source a fact cites becomes a typed `documents` row, linked by `document_links` (`0047`).
- 2026-10-14 · `feat/scout-steward-staff-only` · Scout is for staff and stewards only: `require_scout` (403) on `/ingest` and `/api/ingest`; the sidebar link and `/import` are hidden from everyone else.

## Funder Match and the taxonomy

- 2026-09-23 · a700748 · Resources, methodology and taxonomy pages.
- 2026-10-08 · #98 · The theme taxonomy lives in `tags` (domain → theme → sub_theme); `0030` adds `tag_links` (sub-theme → SDG, Schedule VII clause, scheme).
- 2026-10-08 · #101 · Environment and Others domains; no Draft labels.
- 2026-10-11 · #100 · `compare_fit` in Ask under match-v1: seven criteria judged in code, Strong/Medium/Weak tiers (`0036`, `0037`).
- 2026-10-11 · #142 · Saved runs (`0042`): staff, stewards and org admins run and save; `make match`.
- 2026-10-11 · #150, #152 · The Funder Match page with Rerun, then on the shared list pattern.
- 2026-10-11 · #161 · match-v2: theme compares the taxonomy tree, not Darpan sectors; Others is never a shared area.
- 2026-10-11 · #164 · Taxonomy page: a theme is the fallback when the source is no more specific.

## Auth, roles and RLS

- 2026-10-01 · #64 · Supabase Google sign-in.
- 2026-10-07 · #74 · JWT verification in `core/security.py`, route guards, the signup trigger (`0022`).
- 2026-10-07 · #92 · REST requests run as the caller: `CallerPool` sets role + claims per transaction; `0023`–`0027` roles, access functions, grants, RLS on every table.
- 2026-10-07 · #97 · Settings page, `/api/me`, org member management (`0028`, `0029`).
- 2026-10-12 · #181 · One read policy each on `users` and `org_members`, three FK indexes.
- 2026-10-14 · Each agent route declares its access in `AGENT_ACCESS`; a route with none fails at boot instead of falling back.
- 2026-10-15 · Only a thread's owner may post a turn in it, staff included, so rows read as one user are never replayed to another.

## Frontend and design system

- 2026-09-23 · 040eb94 – 50e834d · Design system and shell, Registry over real data, org and funder profile pages.
- 2026-10-01 · #60 · shadcn/ui and Tailwind v4 themed with Sangam tokens; new home page.
- 2026-10-04 · #86 · Public Ask preview, one navbar everywhere, `?next=` validated, Resources as one tabbed page.
- 2026-10-08 · #107, #108 · Sangam Design System v2 is the system of record; every UI PR keeps it in step.
- 2026-10-10 · #146 · Design-system mapping for Sangam Scout.
- 2026-10-11 · #151 · One list pattern for list pages (`components/ui/ListPage.tsx`).
- 2026-10-12 · #175 · Registry cards wrap long theme tags; styles move to `.reg-*` classes.
- 2026-10-16 · #236 · Phone nav folds its links into a menu beside Sign in; Home's five steps become one numbered card; hero copy.
- 2026-10-17 · #242 · Registry rows show domains (most programmes first) and up to three populations served, with "+N more"; a Theme filter names the sub-themes it matched. Lenses move to their own line on the profile.
- 2026-10-21 · #273 · Back returns to the previous screen: Ask views, chats and proposals, Import threads and profile tabs are pushed URL entries; Registry filters and Funder Match's organisation are replaced into the URL. Vitest cases in `lib/__tests__/back-navigation.test.ts` pin the URL round trips.
- 2026-10-21 · (unmerged) · Component tests: jsdom and Testing Library under Vitest (`*.test.tsx`, `tests/setup.ts`), and tests for every screen take frontend coverage from 1% to 97%; the frontend's patch gate now blocks and its project target is 75%.
- 2026-10-22 · #311 · Design system catch-up: the UI kit recreates Funder Match, Proposals (Sangam Pitch), RFP Watch and Scout's open-calls pull; a new `tokens/workspace.css` holds the workspace screens' classes; the list-page classes live once, in `base.css`; partner logos and hidden composer stubs synced. The mapping in `docs/DESIGN_SYSTEM.md` and the sync notes follow.
- 2026-10-27 · #343 · Doc Vault shows "No documents linked yet" when the server refuses the list (401/403), instead of crashing on `docs.length` (#282).
- 2026-10-27 · #344 · Doc Vault names a document by its title, else its source label, else its website, so cited-only sources no longer read "Untitled document"; Import now writes a title for a URL a fact cites with no document finding (`cited_title`), and fills an untitled row it matches again. VaultView's styles move to `.vault-*` classes (#290).
- 2026-10-27 · #346 · Five bugs pinned by `it.fails`/`xfail(strict)` tests fixed and their markers removed (#345): a metric of 0 prints in the Import brief; a year before a comma is not a missed number; a news run with one working scope classifies its hits; Ask's step label lists a table once; the staff members picker drops a slow answer for an organisation no longer picked.

## Proposals

- 2026-10-11 · #153 · Proposals screens and steps 1–2, kept in the browser (`localStorage`), started from a Funder Match card.
- 2026-10-15 · — · Proposals and RFP Watch show "Coming soon" (`COMING_SOON` in `features/ask/lib/comingSoon.ts`); Funder Match's proposal button and filter are hidden with them.
- 2026-10-15 · M2 · Proposal Copilot agent (`/proposal`): steps advance only through code, each editor has their own private chat in the side panel, teammates' changes reach it from the proposal's log.
- 2026-10-15 · M3a · Sangam Pitch facts and asking: facts from the record checked against it and shown in words with Yes / No, change it / Don't use it; one question at a time, by rule, never asked of two people; "Later" frees it for anyone.
- 2026-10-15 · M3b · Sangam Pitch reads the ticked files and what the funder looks for, one reader each, in parallel, from "Write the first draft"; every screen shows each file's progress, and "Try again" re-reads only a file that failed.
- 2026-10-15 · M4 · Sangam Pitch writes each part from the facts: "Write" per tab, every number, amount, place and partner traced to a fact cited in the same paragraph or refused, a gap where no fact supports it, parts in dependency order with the Summary last, each scored 0–2.
- 2026-10-15 · M5 · "Before you send it": every fact the text uses with Yes / change it / Don't use it and Confirm all; a correction rewrites each sentence that states the old value word for word and marks the rest for a rewrite, facts worked out from it go back to amber, and Fix first / Worth checking decide Ready.
- 2026-10-15 · M6 · Finish: "Smooth the language" in one model call, kept only when code finds every figure, place, name and gap unchanged (else it says what changed); "Download as a Word file" saves the next version to the org's Doc Vault (`proposal_draft`, written with AI) with a snapshot of the facts it cites, and every version stays listed.
- 2026-10-15 · M7 · Suggested wording: asked to improve a sentence, Sangam Pitch calls `suggest_edit` and a card shows it before and after with why; only "Use this" saves it, as the part's next rev, and code refuses wording whose figures, places or names trace to no cited fact before the person sees it.
- 2026-10-15 · M8 · Write in place: step 3 is the prototype's four tabs, with each part a text box that saves as the person types, sources as [1], [2] that code maps back to facts, and any typed figure, place or name with no source listed under the part and in Fix first; Done grades the part once on its text, and typing clears the old grade. Ticked files must be the org's own, and a saved link is shown as one Sangam cannot read.
- 2026-10-16 · — · Proposals are on for everyone: `"proposals"` leaves `COMING_SOON`, so the sidebar, the view and Funder Match's Start a proposal button and filter come back. RFP Watch stays Coming soon.
- 2026-10-19 · Ask efficiency M5: a Sangam Pitch run with no new message ends without a model call (`nothing_to_answer`), instead of asking Claude to continue its own reply and failing with a 400.
- 2026-10-20 · (unmerged) · Sangam Pitch public research: its own card in step 2 and its own button, "Search public sources", runs a reader with web search, from the registry's public rows only, for the problem at district, state and India level, why this place, government schemes and plans, SDGs and what worked elsewhere; each fact's quote must be on a page it read in that run, and it never searches for the org. Its facts are kept or dropped in that card, grouped by topic, beside the sites it could not open. Off without `TAVILY_API_KEY`.
- 2026-10-22 · (unmerged) · Sangam Pitch fill-the-form M1, backend only: `POST /versions {shape: "form"}` reads the funder's form from step 2 once (`proposals/form.py`, a PDF sent to the model as a document), fills its prose headings from the written parts in one call (`proposals/fill.py`), and saves a Word file in the form's headings with a report. Code refuses an answer that adds a figure, place or name and falls back to the parts as written or an [Add: …] mark; fields, tables and annexes are [You fill: …]. The button is M2.
- 2026-10-22 · (unmerged) · Sangam Pitch fill-the-form M2: step 5 has "Download in the <funder> form" when a form was chosen in step 2, with a report under it (answered, cut to fit, put in as written, nothing for, left for you). Step 2 now says the form shapes the download, not the writing; a blank form uploaded among the documents to read is caught by its reader (`looks_like_form`) and "Use it as the funder's form" moves it in one change.
- 2026-10-22 · (unmerged) · Sangam Pitch fill-the-form, after an end-to-end test on the RF form: one call now sees every written part plus the org's name and country, and answers prose and field headings from any part, rephrased to fit. A refused answer (an added figure, or over the limit) becomes a plain `[Add: … (the form allows N characters)]` mark and is logged; nothing is pasted as written any more. Fixes a part shared by 3(a)–3(s) pasted under each, an empty "Proposed strategy", gap-only answers counted as answered, and known fields left blank. The report is answered / still to add / left for you. An answer only over the limit is cut at its last sentence end or ";" that fits, never at a comma. The file shows each heading's limit and the form's own field groups ("Personal Information of Head of Organization") as headings over their fields; the byline date is India's; step 2 no longer lists the chosen form among the files to read. The form reader no longer matches headings to Sangam's parts: it lists the form as it is, and the one fill call finds the answer in any part.
- 2026-10-22 · (unmerged) · Word files are read where only PDFs were: a .docx link (`read_page` points it to `fetch_document`, which names an extensionless download by its type), a downloaded one (`read_document_pages`), and an archived library or funder document (`read_library_document`, `read_funder_document`), by numbered paragraph with table rows kept. Uploaded files already were. Report fixes: a dropped `[Add: …]` is not a cut, an answer that is only gaps counts as nothing, and a fresh upload is no longer shown as a link.
- 2026-10-21 · (unmerged) · Make a case: a new step 3 between "Your documents and style" and the writing, holding the Summary (locked, "Written after your plan", until every other part has text), Context and target area, Problem and baseline, and Secondary research (public research renamed and moved out of step 2). It is left once Context and Problem are written. Each research topic lists its facts with their sources, and one Use this / Don't use for the whole topic. "Write the proposal" becomes step 4, Make a plan, whose first tab is "Objectives and plan" (A4–A7). `0050` moves existing proposals at step 3 or later up one step.
- 2026-10-21 · (unmerged) · The step bar goes forward too: a step can be clicked when every step before it can be left (`summary.furthest`, `POST /advance?to=N`); `work.apply` refuses any jump a step on the way would block.
- 2026-10-21 · (unmerged) · Secondary research can be steered from the chat: `read_files(public=True)` takes the person's ask, focus angles and sites, recorded as `work.research_asks` (no migration); the run gets a Focus block and what is already found, never the person's text or files, and angles naming the org or a partner are dropped. Its facts carry the ask's id and join the five topics; the card lists what was asked and how many facts each added.
- 2026-10-22 · (unmerged) · Research deeper from your case: once Context and target area and Problem and baseline are marked done, `GET /api/proposals/{id}/research/angles` has the utility model read the case (Summary included when written, citations taken out) into up to eight search angles, every `[Add: …]` gap first, dropping any naming the org, funder, a partner or a person; the person removes or adds angles on the card, and "Search these" runs `read_files(public=True, deeper=True)` with them.
- 2026-10-22 · (unmerged) · Secondary research ends with a brief, like a researcher's: what it is based on, Problem magnitude and Impact evidence (at most ten high-quality links each, ordered region → state → India → global, evidence by design), and caveats. The brief is written by one call with Anthropic's web search and fetch (`brief.py`, `research_brief.md`, outside `check_url`, never given the org's name) beside the guarded fact reader, kept on `readers.public.brief` and shown first on the Secondary research card, with the facts behind it, by topic, in one closed section; Sangam Pitch only says in a line what it is doing and, after, what it found at a high level.
- 2026-10-22 · (unmerged) · Secondary research can be started fresh or deleted: `DELETE /api/proposals/{id}/research` (refused while a search runs) removes the brief, asks and every public fact no part cites, derives from or corrected, so a new search can find them again; the card asks before either.
- 2026-10-22 · (unmerged) · The Secondary research card's Search and Start fresh buttons start the search themselves (`POST /api/proposals/{id}/research`, run in the background by `readers.search`), not by a chat message: Sangam Pitch could decline to retry, and a search longer than the chat's stream left no reply. The brief's fetched pages are capped (`max_content_tokens`), a brief that still overflows the context (a PDF fetched whole) is written again with search alone, and a call to a tool it lacks is answered, so long reports no longer leave it empty.
- 2026-10-22 · (unmerged) · Secondary research runs a supervisor that launches one researcher per angle at once, as many as the proposal needs, and the card lists each while it runs, with the sources found so far. `repo.save` locks and writes in one transaction, so parallel researchers never drop each other's facts.
- 2026-10-22 · (unmerged) · Step 2's form card confirms an upload: "✓ Uploaded" with the file's name, "Sangam Pitch reads the form then" until it is read, and the date and number of written questions once it is; a form that is not a PDF or Word file is refused before it uploads, as `form.read` would refuse it in step 5. Recording an upload drops NUL bytes from the extracted text: Postgres refuses them, and the 500 reached the browser as "Failed to fetch".
- 2026-10-22 · (unmerged) · Sangam Pitch reads the public pages and reports Sangam saved for an org, not only its Doc Vault uploads: `read_org_file` replaces `read_vault_document` in the file reader, saved `.md`/`.txt` pages read by numbered line (also in Import's library reader and the funder's documents, and a vault text upload), and readers clear old windows of a long file. Step 2 no longer lists a link with no saved copy. In production 85 saved pages and 22 PDFs had been ticked and refused as "no readable file".

## Media & Signals

- 2026-10-12 · #188 · Tavily news pipeline (`0044_news`, `0045` drops `news_mentions`), one list page, "In the news" on profiles, the `news-brief` Ask skill, an optional verifier agent.

## Performance, deploy and ops

- 2026-09-25 · #33 · CORS ready for Vercel.
- 2026-10-01 · #71, #72, #76 · A GitHub Actions deploy workflow; Vercel's git deploys turned off.
- 2026-10-01 · #77 · `pypdf` locked; production had returned 500 on every route.
- 2026-10-03 · #79 · Only `/ask` and `/import` load the chat runtime.
- 2026-10-08 · #106 · Deploy runs only by hand.
- 2026-10-10 · #148 · Both Vercel functions in `bom1` beside Supabase (warm `/api/funders` 1.2 s → 0.2 s).
- 2026-10-11 · #155 · The frontend starts independent backend calls together.
- 2026-10-12 · #167–#169 · Plan to drop CopilotKit; frontend container restarts; `emit_raw_events=False` (an answer went from 1.69 MB to 107 KB).
- 2026-10-12 · #179 · One backend call per registry profile page.
- 2026-10-12 · #180 · Signed-out reads come from Next's data cache; a cron keeps one backend warm.
- 2026-10-14 · Signed-out cached reads are keyed per deploy, so a new deploy never renders the last one's API shapes (profile pages 500ed after #202).
- 2026-10-16 · Dependabot: `next` 16.3.8 (RCE in `next/og`, image SSRF), CopilotKit 1.75.2 (last on AG-UI 0.0.x), `undici`/`katex` overrides, PyJWT 2.15.1. A `Dependency review` check fails any PR that adds a high or critical advisory.
- 2026-10-16 · CI on every PR: ruff, unit and integration tests (pgvector, migrate, seed), coverage on Codecov (no drop over 1%, 70% of changed lines), and the frontend's lint, types and build.
- 2026-10-19 · langchain 1.4.6, deepagents 0.7.28; `ToolErrorMiddleware` on every agent and subagent, so a tool that raises answers the model with its error type instead of ending the run (#252, #253).
- 2026-10-21 · (unmerged) · Outbound fetches trust certifi plus `app/core/certs/intermediates.pem`, so censusindia.gov.in (which omits emSign SSL CA - G1) can be read; verification stays on, and a test fails a year before an intermediate expires.
- 2026-10-21 · MIT license. The frontend gets Vitest and its own Codecov flag; backend and frontend coverage are gated and badged separately in the README.
- 2026-10-21 · The README is rewritten for newcomers (127 lines from 449: features, how it works, quickstart); setup and conventions move to `CONTRIBUTING.md`, beside `SECURITY.md`, a code of conduct and issue and PR templates.
- 2026-10-21 · README screenshots in `docs/assets/readme/`: Ask with citations as the hero, then Registry, Funder Match and Scout.
- 2026-10-21 · — · Funder Match, RFP Watch and Media & Signals open with one call, not two in a row: the `/ask` page hands its `/api/me` to `useOrgChoices`. `?org=` is optional on `/api/funder-matches` and `/api/rfps/feed` (the caller's first organisation by name), and the Funder Match list reads in one transaction (`repo.read_latest`).
- 2026-10-21 · #285 · The pool's limits are written down:
  - wait, connect and REST statement timeouts;
  - a checked checkout;
  - counts on `/health`;
  - checkpointer DDL moved from every cold start to `make migrate`;
  - one who-may-do-what table in ARCHITECTURE §8.
- 2026-10-22 · `search_public_sources` checks its hits at once, not in turn (a Pitch search took 10–34 s against Tavily's 2–7 s); Pitch and Import both use it.

## Tracing and evals

- 2026-09-23 · 5f51ee1, 60340f8 · Langfuse tracing (env-gated); `make smoke`.
- 2026-09-27 · #53 · Conversation-scoped traces; each SQL statement a span under its tool call.
- 2026-10-11 · #156 · Langfuse SDK v4: `sangam_ask` is the trace root, the `answer_audit` score, flush after each run.
- 2026-10-16 · (unmerged) · Ask efficiency M1: evals count tool calls, model calls and tokens per case, fail on `max_calls` budgets, and run as a Langfuse dataset experiment (`ask-golden`, environment `eval`) so runs compare side by side; `make evals K=<case>`; the Better Life Foundation cost case.
- 2026-10-22 · (unmerged) · Chat traces name the caller: Langfuse's user is their email, and tags carry `org:<name>` and `role:<role>` for each organisation they belong to (`role:staff` for staff); Pitch traces add `proposal_id`.
- 2026-10-22 · (unmerged) · Every span of a chat run, not just its root, carries the caller, session, tags and trace name (`propagate_attributes`), Pitch's file readers included, so Langfuse v4 dashboards can sum cost per user and per organisation; the caller's organisations also go in the trace `version` (`FFRH + SeSTA`, `Sangam staff`), the one field Langfuse can group a chart by.
- 2026-10-19 · Import evals count every tool call, subagents' under their own name (`entity-researcher.save_research`), and the two canaries fail on `max_calls`: one sources card, no bulk import, at most two `task`s and three saves (#250).

## Docs

- 2026-09-23 · 4b97d7e, eb84385 · README architecture section.
- 2026-09-26 · #51 · CLAUDE.md made usable for a cold start.
- 2026-10-01 · #55 · Data platform architecture spec and the v3 data model, for review.
- 2026-10-04 · #87 · UI roadmap after Phase 1.
- 2026-10-08 · #99, #102, #119 · Plans: funder consolidation, CSO consolidation, Import update-or-ask.
- 2026-10-14 · (unmerged) · `docs/ARCHITECTURE.md`, this changelog and nested `CLAUDE.md` pointers; then OpenWiki generates `openwiki/` (`make wiki-update`) and ARCHITECTURE.md keeps only the why.

---

## RFP Watch

- 2026-10-15 · #228 · M1: `make calls-pull` reads each funder's calls page (pinned six first) and writes open calls; dead ends print as "Needs a look". UNDP's notices feed is registered permission-only (robots.txt disallows it).
- 2026-10-16 · #231 · M2: open calls are matched to orgs with members by shared domain (`make calls-match`, also the end of every pull); `GET /rfps/feed?org=` returns an org's open and saved calls; PATCH accepts `saved`.
- 2026-10-16 · #232 · M3: the RFP Watch screen in Ask (For you · Closing soon · Saved, search, a theme filter, Save, Not for us, Ask about this call); no longer "Coming soon".
- 2026-10-19 · #246 · M4: Scout runs the pull: a staff-only "Check open calls" task and `run_import_now(sources="funder_calls")` with its own approval card. A re-run reuses only a page the pull itself read, not the report a research call names.

## Not finished

Plans that shipped in part, and what is left. Check here before assuming a plan doc describes the code.

| Plan | Shipped | Left |
|---|---|---|
| `2026-10-15-rfp-watch.md` | M1 (#228), M2 (#231), M3 (#232), M4 (#246) | The staging exit gates; the design-system sync of the Ask page. |
| `2026-10-11-drop-copilotkit.md` | M1 (#168), M2 (#169) | **#178 removed `emit_raw_events=False`, so raw events stream again** (`core/lifespan.py`). M3 (drop CopilotKit from the frontend) and M4 (from `pyproject.toml`) not started. |
| `2026-10-13-import-researcher-contract.md` | M1–M4 (#194–#197) | M5: backfill KABIL and Axis on staging. |
| `2026-10-13-programme-themes-required.md` | steps 1–4 (#192) | Step 5, `write_funder_tags_from_programs`: PR #172, unmerged. |
| `2026-10-10-list-pages-proposals-media.md` | PRs 1–3 (#151–#153) | PRs 4–5: proposal drafting, section editor, assemble/polish/.docx. No proposals backend. PR 6 superseded by #188. |
| `2026-10-10-page-load-performance.md` | PRs 1, 4, 7–11 | PR 2 closed (#149), PR 3 dropped, PRs 5–6 deferred. |
| `2026-10-09-import-guided.md` | #130 | Its "review follow-ups" list is still open. |
| `features-plans/access/auth-plan.md` | Phase 1 (#74, #92, #97) | Phase 2 (email-domain matching, join requests). Ask's SQL and Import still run on the owner pool (branch `fix/ask-sql-runs-as-caller`, unmerged). |
| `features-plans/roadmap/2026-10-04-ui-roadmap.md` | D1 (#98), B1 (#92) | A4–A10, R1–R6. |

Plan docs whose status line is out of date (the work did ship): `2026-09-30-supabase-storage.md` (#61),
`2026-10-10-import-for-every-role.md` (#136–#139), and the "Draft v1" docs for #120, #125, #127, #130.
Superseded: `2026-10-04-funder-eligibility.md` (table dropped by `0031`), `2026-10-08-import-storage-picker.md`
(replaced by `choose_sources`), `2026-10-07-funder-matching-in-code.md` (replaced by match-v1).

Unmerged branches with real work: `fix/ask-sql-runs-as-caller`, `fix/copilotkit-runtime-routes`,
`feat/access-check`, `fix/funder-tags-from-programmes` (#172), `docs/proposals-spec`, `docs/funder-match-spec`,
`docs/import-comprehensive-data`, and the graph branches `graphiti`, `graphiti-supabase`, `supabase-graphiti`,
`add-episode-ui`.
