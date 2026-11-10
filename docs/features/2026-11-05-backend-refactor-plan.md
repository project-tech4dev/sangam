# Backend refactor: clear boundaries, no new layers

v3, approved 2026-11-06: v2 after a critical review of v1 (section 7), plus phase 0 and R6 (dead code).
Each phase is one PR that moves code without changing behaviour. **Each PR also adds the `CLAUDE.md` rule it makes
true, and the test that keeps it true.**

## 1. Goal

**Anyone opening `backend/app/` can find an agent, its tools, the routes, the services and the shared code from the
folder names alone. A test fails when a change crosses a boundary.**

Success, checked on every phase:
- only import lines and file paths change in `tests/`;
- `git diff -M --stat` shows the moved files as renames;
- the existing tests pass and `make smoke` is green;
- no new layer, base class, framework or dependency is added.

## 2. What is wrong today (measured 2026-11-05, master `01abd73`)

The REST side (routes, then repositories, then schemas) already follows its rules: no route holds SQL. Every problem
is in how the three agents share code.

| # | Problem | Evidence |
|---|---|---|
| 1 | Shared agent code lives in Ask's package, and some of it in Import's | `ingest/` and `proposals/` import `resolve_model`, `harness` and `tool_errors` from `agent/` (Ask). Ask imports `fallback` from `ingest/middleware.py` |
| 2 | Five circular imports, hidden by imports placed inside functions | `agent/middleware.py` ↔ `ingest/tools/catalog_tools.py`; `research_records` ↔ `source_guards`; in `proposals/`: `readiness` ↔ `steps`, `records` ↔ `tools/record_tools`, `reading_tools` ↔ `readers` |
| 3 | Code outside a `tools/` package imports plain functions from one | the `/api/ingest` routes call `save_to_catalog`, `review_view` and `coverage_view` from `catalog_tools.py`; `documents.py` calls `agent/tools/files.extract_pdf_text`; `proposals/records.py` calls `record_tools.match_text` |
| 4 | `ingest/` has 28 modules at one level, which is half the backend | `records.py` (what the writer accepts) sits next to `research_records.py` (what a researcher saves) |
| 5 | Five files are over 800 lines | `promote.py` 1,625 · `writer.py` 1,395 · `sql/catalog.py` 1,124 (data) · `research_records.py` 1,105 · `catalog_tools.py` 904 |
| 6 | Entry points are named differently | Import's builder is `ingest/agent.py` and Pitch's is `proposals/agent.py`, but Ask's is `agent/build.py` |
| 7 | Pitch imports Import's private names | `_AgUiState`, `library_tools._archived` |

Not a problem, so not touched: the ~45 lazy imports that remain are inside routes, `core/lifespan.py` and the news
pipeline. They are there so a cold start doesn't load the agent stack (`CLAUDE.md`, "built on the first chat turn").

## 3. Final recommended structure

Only what changes is shown. `api/`, `repositories/`, `schemas/`, `db/`, `integrations/` and `matching/` stay
exactly as they are.

```
backend/app/
  agentkit/                 NEW  shared by every deep agent, owned by none
    models.py                    ← agent/models.py        model tiers, resolve_model
    harness.py                   ← agent/harness.py       install(), filesystem(keep=…)
    middleware.py                ← agent/middleware.py    tool_errors, clear_old_tool_results, model_call_cap
                                 ← ingest/middleware.py   fallback, cheap_summarizer, AgUiState (made public)
  core/
    extract.py              NEW  ← agent/tools/files.extract_pdf_text + ingest/office.py   bytes in, text out

  ask/                      ← agent/   (phase 6, if you approve the rename; see section 5)
    agent.py                     ← build.py               entry point, the same name in all three agents
    audit.py · prompt.py · instructions.md · middleware.py (SQL retry, CompareFitBudget) · tools/ · skills/

  ingest/                   Sangam Import (Scout)
    agent.py · middleware.py (+ StaffLastLock, SaveQuestions) · instructions.md · caller.py · live_status.py
    brief.py · runner.py · geography.py · taxonomy.py · render_docs.py · reshelve.py     stay at the top
    research/               NEW  what a researcher must find, and the shape it saves
      findings.py                ← research_records.py: EntityResearch, Gap, Unplaced, ResearchSummary, VaultResearch
      finding_types.py           ← research_records.py: the per-concept finding models and FINDING_MODELS
      contract.py · expectations.py · coverage.py · source_guards.py
    reading/                NEW  where a run may read
      access.py · registry.py ← sources.py · run_sources.py · staff_sources.py · vault.py
    catalog/                NEW  from the brief to Sangam's tables
      save.py                    ← catalog_tools.py: save_to_catalog, review_view, coverage_view, write_preview …
      rows.py ← records.py · matcher.py · undo.py · review.py · manual_checks.py
      promote.py · promote_records.py · promote_documents.py · promote_facts.py
                                 ← promote.py, split at its records/documents/facts lines (both entities share them)
      writer.py · writer_funder.py · writer_org.py         ← writer.py, split at its funder/org line
    tools/ · news/ · calls/ · adapters/ · prompts/ · skills/     unchanged

  proposals/                Sangam Pitch: stays flat (29 files, none over 430 lines)
    records.py                   + match_text, org_text  ← tools/record_tools.py
```

How someone finds things afterwards:

| Looking for | Go to |
|---|---|
| An agent's entry point | `<agent>/agent.py`, in all three agents |
| An agent's tools | `<agent>/tools/`, which holds tools and the helpers only they use |
| A function a route calls | a module outside `tools/`, e.g. `ingest/catalog/save.py` |
| Something every agent uses | `agentkit/` |
| Why an Import save was refused / a page wasn't read / a fact didn't reach the profile | `ingest/research/` / `ingest/reading/` / `ingest/catalog/` |

## 4. The rules, and the one test that enforces them

These go into a `CLAUDE.md` section called "Code boundaries", **one rule per phase, in the PR that makes it true**.
`CLAUDE.md` has said things that were false before ("That sentence was false for a while"), so a rule never goes in
ahead of its code.

One new file, `tests/test_architecture.py`, uses `ast` (no new dependency) and makes five checks. Each starts with an
allowlist of today's exceptions that a later phase may shrink but never grow.

| Rule | Check | Example of a failure |
|---|---|---|
| R1. Only an agent's builder imports from a `tools/` module; nothing else imports a non-tool from one | phase 1 | `routes/ingest.py` importing `save_to_catalog` from `catalog_tools` |
| R2. An import inside a function needs a reason: a cold start (routes, lifespan, news) or a heavy optional package. Never a circular import | phase 1 | `from app.ingest.tools.catalog_tools import write_preview` inside a middleware |
| R3. The agents (`ask`, `ingest`, `proposals`) import shared code from `agentkit/` and `core/`, not from each other. Allowed: Pitch uses Import's public brief, vault, geography, source rules (`access`, `run_sources`, `source_guards`) and reading tools | phase 2 | `proposals/middleware.py` importing `_AgUiState` |
| R4. No file over 800 lines; a new file aims for 300–500. Split at a line the file already draws, never into layers. Data files are exempt (`sql/catalog.py`) | phase 5 | a new 900-line `writer_funder.py` |
| R6. No dead code: a top-level function or class in `app/` has a caller in `app/`, `seed/` or `scripts/`. A test is not a caller. Decorated definitions (routes, `@tool`) and scripts' `main()` are exempt | phase 0 | `class SourceOutcome` in `runner.py`, referenced nowhere |

R5, about how a PR is made, goes in the same section: **a move is its own PR.** It contains `git mv` and import
edits, no behaviour change and no re-export shim, followed by `make wiki-update`. OpenWiki pins its claims to paths,
so expect one model call per page whose paths changed.

## 5. Implementation sequence

Every phase has the same acceptance gate, **G**:
- `cd backend && pytest -m "not integration" && ruff check .`;
- CI green, including the integration tier;
- `make smoke`;
- `git diff -M --stat master` shows renames where files moved;
- `git diff master -- backend/tests` changes only `import` lines and `monkeypatch` path strings.

| # | PR | What moves | Rule + test | Size | Extra acceptance |
|---|---|---|---|---|---|
| 0 | **Delete before moving** | delete `SourceOutcome`, `GrantSummary`, `Executor`, `sql_max_attempts`, `agent/tools/mcp.py`, its five settings and `langchain-mcp-adapters`, and five functions only tests call (`in_category`, `rule_for_host`, `list_buckets`, `topic_of`, `get_json` with the rest of `_http`'s unused client) with their tests; one `_filled` (coverage = contract). `object_key` stays: `scripts/upload_staff_source.py` calls it | R6 | ~15 files | `grep -rw <name>` over `backend/` and `frontend/` finds nothing for each deleted name |
| 1 | **Tools are tools** | `catalog_tools`' 5 service functions → `ingest/catalog_save.py`; `StaffLastLock`, `SaveQuestions` → `ingest/middleware.py`; `match_text`, `org_text` → `proposals/records.py`; `extract_pdf_text` + `office.py` → `core/extract.py`; `readiness`↔`steps`: the shared constant moves to `steps.py` | R1, R2 | ~15 files | the circular imports in `agent/middleware.py`, `proposals/records.py` and `readiness.py` are gone |
| 2 | **agentkit/ and one entry-point name** | `models.py`, `harness.py` and the shared middleware → `agentkit/`; `agent/build.py` → `agent/agent.py`; `AgUiState` and `archived` made public | R3 | ~45 import lines | `import app.main` still does not import `deepagents` (add this test) |
| 3 | **ingest/research/** | `research_records.py` splits into `findings.py` and `finding_types.py`; `contract`, `expectations`, `coverage` and `source_guards` move in | none (G only) | ~40 import lines | the `research_records` ↔ `source_guards` cycle is gone; R2's allowlist shrinks |
| 4 | **ingest/reading/** | `access`, `sources` → `registry`, `run_sources`, `staff_sources`, `vault` | none | ~45 import lines | one real Import run on the local DB |
| 5 | **ingest/catalog/** + the two splits | `catalog_save` → `catalog/save.py`; `records` → `rows`; `matcher`, `undo`, `review`, `manual_checks`; `promote` splits into entry, records, documents and facts (its funder and org paths share every step); `writer` into shared, funder and org | R4 | ~60 import lines | one funder and one NGO Import, saved on the local DB, with the same catalog rows as before (compare `catalog_writes`) |
| 6 | **Rename `agent/` → `ask/`** (decide after phase 5) | the folder; `CLAUDE.md`, `ARCHITECTURE.md` and the nested `CLAUDE.md`; dated plans stay as written | none | 82 files, mechanical | G |

Phases 3 to 5 touch the files that open Import PRs touch (#367 edits `research_records.py` and `middleware.py`).
Start phase 3 after those merge. Phases 0, 1 and 2 can go now.

## 6. What this plan deliberately does not do

| Idea | Why not |
|---|---|
| A service layer between routes and repositories | Routes hold no SQL already; it would be a pass-through |
| Base classes for tools or agents | `create_deep_agent` plus `agentkit/` is the shared base; three agents differ on purpose |
| Splitting every 500–800 line file | Nine files are in that band (`validator.py` 664, `records.py` 608, `news/pipeline.py` 578 …). Each is one job read top to bottom; splitting them adds files without adding clarity. They are split if they cross 800 |
| Restructuring `proposals/` | 29 small files, none over 430 lines; only its three circular imports are fixed (phase 1) |
| A `brief/` folder | It would hold `brief.py` plus two unrelated host scripts; one file needs no folder |
| `import-linter` | Declarative and good, but a new dependency for four checks; `ast` in one test does the same in this repo's style |
| Moving the SQL catalog to `db/` | It is Ask's allowlist first; Import reads it through one public name (`CATALOG`), which R3 allows |
| Hunting near-duplicate logic | Only exact or near-exact copies are merged (phase 0). The two ₹ crore formatters (`brief.py`, `proposals/tools/record_tools.py`) print differently on purpose until someone decides one format |
| Frontend | Out of scope. Worth a later look: Pitch's 1,079-line `ProposalShell.tsx` under `features/ask/views/` |

## 7. Changes from v1

| v1 | v2 | Why |
|---|---|---|
| Phase 0 put all the rules into `CLAUDE.md` first | Each rule lands in the PR that makes it true | A rule describing code that doesn't exist yet is the kind of false sentence `CLAUDE.md` already had to retract |
| Rules were prose only | One `test_architecture.py`, four checks, allowlists that only shrink | "Enforceable" means a failing test, not a paragraph |
| "A `tools/` module holds `@tool` functions only" | "Only the builder imports from `tools/`" | The strict version would refuse legitimate helpers such as `make_web_search` and `page_name`; the real boundary is who imports |
| One phase for all of `ingest/` (~160 lines) | Three PRs, one per folder | Smaller diffs, and each can be checked with a real Import run |
| A `brief/` folder | `brief.py` stays at the top | A folder for one file adds a level and no clarity |
| `writer` and `promote` split "optional" | Required, in phase 5 | They are the two largest files, and the 300–500 target makes the split required rather than optional |
| `research_records.py` not split | Split into `findings.py` and `finding_types.py` | 1,105 lines, and the split also breaks the `source_guards` circular import |
| Circular imports: one noticed | Five listed, three fixed in phase 1, one in phase 3, one kept on R2's allowlist (`reading_tools` → `readers`, a tool that starts the subagent built from it) | Counted with a search for imports inside functions |
| `agent/build.py` kept | Renamed to `agent.py` | The same entry-point name in all three agents |
| `agent/` → `ask/` rejected | Phase 6, decided after phase 5 | `agentkit/` next to `agent/` reads as a pair, which hurts finding things; it is still the largest move, so it is decided last |
| `proposals/` not mentioned | Stays flat; its three circular imports are fixed | Small files, and flat is easy to scan at that size |

## 8. Open questions

1. ~~Rename `agent/` → `ask/` in phase 6?~~ Done in phase 6 (2026-11-06), as recommended. 82 files, mechanical, and it is the only way the folder
   names alone say which agent is which.
2. ~~`agent/tools/mcp.py`~~: deleted in phase 0 (2026-11-06).
3. ~~The name `agentkit/`~~: used, as recommended. I recommend it over `deep/` or `agents_common/`: short, and it says it is a kit, not an
   agent.
