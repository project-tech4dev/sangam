# RFP Watch M4: run the open-calls pull from Scout

## Context

Today, getting calls into RFP Watch means a terminal: `make calls-pull` reads funders' calls pages, writes the open
calls, closes expired ones and matches them to orgs. Staff want to start that from Scout (`/import`) instead.

Scout already has the exact shape for this. The **news pull** is a fixed pipeline, not research, and it runs through
the supervisor's existing `run_import_now(sources="tavily_news")`: no `choose_sources`, no researcher, one approval card
that shows the plan, then a report. The calls pull is the same kind of thing, so it becomes a second source key on the
same tool.

**What changes in the agent's architecture: almost nothing.**
- No new tool, no new subagent, no new interrupt. `TOOLS`, the subagent specs and `INTERRUPT_ON` stay as they are, so the
  tests that pin them (`test_ingest.py:249-362`, `test_harness.py:309`, `test_import_sources.py:33`,
  `test_import_roles.py:64`) keep passing untouched.
- `run_import_now` gains a third mode beside "adapter import" and "news pull": `sources="funder_calls"`.
- The supervisor never sees page text, only the report lines, so "delegate reading to subagents" still holds.
- The person still makes the choice: the approval card names the funders before anything is read.

### Agent architecture, before and after

```
                         Scout supervisor (Opus 5.5) ── instructions.md + 5 supervisor skills
                                         │
 ┌───────────────────────────────────────┼──────────────────────────────────────────────┐
 │ supervisor tools (TOOLS, unchanged)   │ subagents (task tool, unchanged)             │
 │                                       │                                              │
 │ choose_sources ⏸ (HITL: sources card) │ entity-researcher (Sonnet) ─ web, library,   │
 │ funder_dossier · compare_with_catalog │   pull skills, save_research                 │
 │ coverage_report · record_registry_chk │ catalog-writer (Haiku) ─ promote_research    │
 │ list_import_sources · plan_import     │ workbook-reader (Haiku) ─ read_workbook      │
 │ import_run_summary · pending_resol.   │ vault-reader (Sonnet) ─ Doc Vault only       │
 │ publish_brief                         │                                              │
 │ run_import_now ⏸ (HITL: approve card) │                                              │
 │   ├─ sources=<adapters>  → run_import (team spreadsheets → catalog)                  │
 │   ├─ sources=tavily_news → _news_pull → news pipeline                                │
 │   └─ sources=funder_calls → _calls_pull → calls.pull.run   ◀── NEW (M4)              │
 │                                │                                                     │
 └────────────────────────────────┼─────────────────────────────────────────────────────┘
                                  ▼
          for each funder: pinned page / last page / find.candidates (site + cited + Tavily)
             → Haiku pick_page → read_page (robots, guarded_client) → Haiku extract_calls
             → write open calls (rfps + places + themes, provenance)
          then: close_expired → rfps.flag_matches → rfp_matches → RFP Watch feed
```

Only the `funder_calls` branch is new. The pipeline under it is M1–M2's code, unchanged.

**Worked example.** Staff types "Check open calls for Tata Trusts and Axis Bank Foundation".
1. The supervisor calls `run_import_now(goal=…, funders="Tata Trusts, Axis Bank Foundation", sources="funder_calls")`.
2. The run pauses on the card: "Check open calls from 2 funders? Reads each funder's calls page; about 1 search and
   2 small model calls each." Approve.
3. The tool runs `calls.pull.run(pool, deps, ["tata-trusts", "axis-bank-foundation"])` and returns its report:
   "Tata Trusts: 1 open written … Axis Bank Foundation: NEEDS A LOOK … -- 2 funders read, 1 open call written …
   Matched: Diya Foundation +1".
4. The supervisor relays that in two or three lines. The call is now in Diya's RFP Watch feed.

## M4 — Scout runs the pull (one PR, stacked on #232)

Branch `feat/rfp-watch-m4` in a new worktree off `feat/rfp-watch-m3`. Plan committed first as
`docs/features/2026-10-19-rfp-watch-scout.md`.

**Backend**
- `backend/app/ingest/tools/pipeline_tools.py`
  - Add `_calls_pull(names)` beside `_news_pull` (`:190-208`), the same shape:
    - resolve `names` to funder slugs with one SQL lookup (name or slug, case-insensitive); unknown names become report
      lines, not errors; empty means every funder;
    - `await pull.run(get_pool(), pull.Deps.from_settings(get_settings()), slugs or None)`;
    - return `"\n".join(lines)`.
  - In `run_import_now` (`:238-260`), after the `tavily_news` branch: `if keys and "funder_calls" in keys: return await
    _calls_pull(names)`. `staff_only` already runs first; the try/except already turns failures into a string.
  - Update `run_import_now`'s `@tool` docstring with the new source key.
- `backend/app/ingest/calls/pull.py`: lower `PARALLEL` from 4 to 3 only if a run shows pool waits; the app pool (10) is
  shared with researchers and the checkpointer. Otherwise unchanged. No `--yes` equivalent needed: the card is the
  confirmation.
- `backend/app/ingest/instructions.md`: under "The adapter path" (`:335-344`), add the calls pull next to the news pull:
  a request for open calls / RFPs calls `run_import_now(goal, funders=<names, or empty for every funder>,
  sources="funder_calls")` straight away, with no `choose_sources` and no researcher; relay the report's "NEEDS A LOOK"
  lines; never research a call by hand when the pull is what was asked. Fix the "`tavily_news` is the only source"
  line. Exempt the calls pull in "Every run" (`:23-24`) as the news pull is.

**Frontend** (`frontend/features/ingest/`)
- `components/ImportApproval.tsx`: a calls branch beside the news branch (`:37`, `:63-108`) when
  `sources.includes("funder_calls")`: title "Check open calls?", the funders named or "every funder in Sangam", and the
  cost line computed from the count (no new endpoint).
- `components/ScoutChat.tsx`: a staff-only task card in `TASKS` (`:45-53`), "Check open calls" — "Read funders' own
  pages for open calls for proposals, and add them to RFP Watch." `WAITING.run_import_now` stays.
- `lib/composePrompt.ts`: `ImportTask` gains `"calls"`; `leadIn("calls")` = "Check open calls for ".
- `lib/access.ts`: `tasksFor` keeps calls staff only, like news.
- `lib/toolLabels.ts`: `run_import_now`'s detail says "Open calls · <funders>" when the source is `funder_calls`.
- Styles in existing classes; no new tokens. The approval card change is a component change, so the design system sync
  applies (needs V's agreement, as before).

**Docs**: `docs/ARCHITECTURE.md` RFP Watch section (Scout is now the button; the CLI stays for staging and scripts),
`docs/CHANGELOG.md` M4 line, `make wiki-update` left to the user.

**Tests**: none new (standing rule). Run the existing suite; the tool-set tests should stay green untouched.

## Out of scope (a later milestone if wanted)

Scout's *research* path also finds calls (field 8 of `funder-intake-research`) and writes them through
`promote.py:1101`, but those never reach RFP Watch: they're tagged with a Schedule VII clause (none of the 12 rolls up to
a domain), matching doesn't run after a promote, expired calls are written open, and only one place is kept. Fixing that
is separate work; until then the pull is how calls reach the feed.

## Verification

1. `cd backend && pytest -m "not integration"` and `ruff check .`; `cd frontend && npm run lint && npm run build`.
2. Locally as staff in Chrome at `/import`:
   - the "Check open calls" card fills the composer; send it for "Tata Trusts and Axis Bank Foundation";
   - the approval card names the 2 funders and the cost; Reject → nothing written; ask again, Approve → the report
     appears in the reply;
   - `make psql`: new `rfps` rows have `extractor_version LIKE 'calls-%'` and provenance; `rfp_matches` has rows for
     Diya when a call shares its domain;
   - RFP Watch for Diya shows the new call.
3. As a steward and a member: no "Check open calls" card; typing the request gets the `staff_only` refusal.
4. "Check open calls for everyone" shows "every funder in Sangam" on the card before anything runs.
5. Phone width: the new card and approval card fit with no sideways scroll.
