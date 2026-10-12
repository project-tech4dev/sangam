# Media & Signals — Plan 2: screens, agent and clean-up

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (native) or superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Finish the service end to end in the same PR as Plan 1: a news pull starts from Scout, stories show
on Media & Signals and on Registry profiles, Ask Sangam can cite them, and nothing reads `news_mentions` any more.

**Architecture:** No new screen patterns. Import keeps Scout's task card → composer → approval card. Media &
Signals is Funder Match's list screen (`.view`, `fm-head`, `BucketCards`, `FilterRow`, `SearchBox`) with
Proposals' "load more" (`ListMore`) fed from the server. Registry profiles keep their tabs and `SectionCard`.

**Spec:** `features-plans/signals/2026-10-10-media-signals-design.md` (2b, 3, 4, 5, 6, 7, 11).
**Prototypes:** v40 (Media & Signals, "In the news") and v41 (https://claude.ai/artifact/PiiVTnYXsDfAYYsk4b9sSM).

## Global Constraints

- Reuse before adding: `@/components/ui` list pieces, `call()` from `features/ask/lib/rest.ts`, `apiGet()` on the server.
- No new token, colour or size in `globals.css`; new looks reuse existing classes (`fm-*`, `import-pick`, `card`, `tag`).
- Styles in classes, not `style={{…}}`; icons from `lucide-react`.
- Scores show as High / Medium / Low only (D6). Signed out sees public links only, on a profile only (D5, §4).
- Comments one or two lines. Backend tests as in Plan 1; frontend is checked by `npm run lint`, `next build` and a
  click-through against the prototypes (there is no frontend test runner).
- Any UI change syncs "Sangam Design System v2" in the same PR (CLAUDE.md).

## Review Focus

1. A member who belongs to one organisation sees only that organisation in "My organisations", never every org.
2. Names typed into Scout that match nothing show "no Registry record" on the approval card, not "everyone".
3. A profile page shows only public stories, signed in or out (ruled 12 Oct; it first added "Below the public bar").
4. Scrolling Media & Signals while a pull adds stories neither repeats nor skips a card (keyset cursor).
5. After `news_mentions` is dropped, the app boots: the SQL catalog, stats and every page read the new tables.

---

### Task 1: Scout starts a news pull (backend)

**Files:** `backend/app/api/routes/news_runs.py`, `schemas/news_runs.py`, `ingest/news/pipeline.py`,
`ingest/tools/pipeline_tools.py`, `ingest/instructions.md`; tests `test_news_runs_routes.py`, `test_news_chat_pull.py`.

- **Plan by names.** `GET /api/ingest/news-runs/plan?names=KABIL,SBI%20Foundation` (staff). Move
  `_news_selection` from `pipeline_tools.py` to `pipeline.select(pool, names) -> (org_ids, funder_ids, feeds)` and use
  it in both places. Response adds `matched: list[str]` and `unmatched: list[str]`, so the card can say what it found.
- **Drop the form routes.** Remove `POST /api/ingest/news-runs` and `/{id}/execute`, `NewsRunIn`, `NewsRunCreated`
  and their tests. `create_run`/`execute_run` stay (Scout's `run_import_now` and `make news-pull` use them).
- **Supervisor.** In `instructions.md`, a request for news ("Get the latest news for everyone in Sangam", "…for KABIL")
  calls `run_import_now(goal, funders=<the names, or empty for everyone>, sources="tavily_news")` straight away;
  the approval card is the person's check. Remove "India CSR" from what the supervisor offers.

- [ ] Tests first: plan with `names` → matched/unmatched and searches; unknown names → `unmatched` filled and
  `subjects == 0`; the removed routes 404; `run_import_now` with `tavily_news` and names reaches `pipeline.select`.
- [ ] Implement; run `tests/test_news_*.py`; full suite.

### Task 2: Scout's news card and approval card (frontend)

**Files:** `frontend/features/ingest/ScoutChat.tsx` (TASKS), `lib/composePrompt.ts`, `components/ImportApproval.tsx`,
`lib/api` for the plan call.

- News card: title "Get the latest news", desc "News about the organisations and funders in Sangam, FCRA, and the
  CSR sector in the North East." `leadIn("news")` → `"Get the latest news for everyone in Sangam"`.
- `ImportApproval`: when `plan.sources` includes `tavily_news`, the same card says "Pull the latest news?", buttons
  "Pull the news" / "Don't pull", and one `import-pick-text` line from
  `call<NewsPlan>("/api/ingest/news-runs/plan?names=" + funders)`:
  "News for everyone in Sangam (17 organisations and funders), plus FCRA and North East sector news · about 116
  searches · about $6.50", or "News for KABIL, SBI Foundation (their own news) · …", or "No Registry record for:
  X" when `unmatched` is not empty. Other imports keep today's card unchanged.
- [ ] Lint + build; click through v41's three steps against the scratch API.

### Task 3: Fill Plan 1's backend gaps for the v40 screens

Nothing new here: spec §4 and D8, already shown in v40, which Plan 1's read API does not yet do.

**Files:** `repositories/news_stories.py`, `routes/news_stories.py`, `schemas/news_stories.py`; test `test_news_stories_sql.py`.

- "My organisations" is the caller's own organisations (`org_members`; a steward's stewarded ones); staff see all.
- General's Area filter (D8): `mine` / `north_east` / `all`, and each story's reason for being in the area.
- The "Last pull" date the v40 header shows: the latest finished `tavily_news` run.
- [ ] Tests first for each; implement; suite.

### Task 4: Build the Media & Signals page as in v40

v40 is the reference; where this plan and v40 differ, v40 wins.

**Files:** replace `frontend/features/ask/views/MediaView.tsx` with `views/media/` (page, story card, api);
`components/ui/ListPage.tsx` gains `useCursorList` (the server-side "load more" v40 needs).

- Build on Funder Match's shell and the shared list pieces (`BucketCards`, `FilterRow`, `SearchBox`, `ListMore`).
- [ ] Lint + build; click through v40's Media & Signals against the scratch API as member, steward and staff.

### Task 5: Build Registry "In the news" as in v40

v40 is the reference. **Files:** the two Registry profile pages and `features/registry/ProfileTabs.tsx`.

- The org profile's Signals tab becomes v40's "In the news"; the funder profile gets the same tab.
- [ ] Lint + build; open a profile signed out and signed in.

### Task 6: Drop `news_mentions`, and let Ask Sangam cite stories

**Files:** `db/migrations/0044_news.sql` (append the drop), `api/routes/news.py`, `schemas/news.py`,
`repositories/news.py`, `ingest/writer.py`, `ingest/runner.py`, `ingest/records.py`, `seed/seed.py`,
`seed/data/gdelt/`, `agent/tools/sql/catalog.py`, `sql/validator.py`, `sql/render.py`, `agent/instructions.md`,
`frontend/features/ask/lib/citations.ts`, `EvidenceRail.tsx`, tests and `tests/evals/cases/golden.jsonl`.

- `DROP TABLE news_mentions` at the end of 0044 (0 rows on staging). Remove `/api/news` (old list), `NewsOut`,
  `list_news`, `write_news_mention`, `_ingest_gdelt`, `seed_news` and the GDELT CSVs. Keep the parked adapter files.
- Stats: `news_mentions` → `news_stories` (count of stories); EvidenceRail "News signals" reads it.
- Catalog: add `news_stories`, `news_links`, `news_story_entities` (their ids cite `news`), take them and
  `news_story_locations`/`news_story_tags` out of `KNOWN_EXCLUDED`; keep `news_link_scores` and `news_watch`
  excluded. Defect line on `news_stories`: "A topic story names no organisation; zero stories for an org does not
  mean nothing was said about its area." Add `news` to the citation kinds (catalog check, render, `citations.ts`
  label → the story headline), and `[news:N]` to the rule in `instructions.md`.
- Eval case `kabil-news-declines-when-unlinked` becomes a case that answers from `news_story_entities`.
- [ ] Tests first: catalog has the three tables and no `news_mentions`; a query projecting `news_stories.id` renders
  `[news:N]`; stats returns `news_stories`. Implement; suite; `verify_against_db` passes at boot on the scratch DB.

### Task 7: Design system, and the whole thing locally

- Sync "Sangam Design System v2" by hand (docs/DESIGN_SYSTEM.md): the Ask UI kit page's Media & Signals view, the
  Import approval card's news text, the profile "In the news" tab. No component in `components/ui` changes look.
- Run the stack locally against the scratch DB (backend :8011, frontend dev pointed at it), pull for two orgs, then
  walk: Scout → approve → Media & Signals (member, steward, staff) → a profile signed out and in → Ask "news about
  KABIL" cites `[news:N]`.
- Final review (fresh reviewer), fix Critical/Important test-first, then the full diff for approval before one commit.

## Self-review

Spec coverage: 2b (Tasks 1–2), §4 roles (3, 4, 5), §5 API (3), §6 screens (4, 5), §7 list pattern (4), §11 rows
Data/Import/Media/Registry/Agent/Design system (1–7). Deferred by decision: none. Review Focus lines map to Task 3
(1), Task 1 (2), Task 5 (3), Task 4 (4), Task 6 (5).
