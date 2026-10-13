---
type: workflow
title: "One Import Turn: choose_sources to Undo"
description: End-to-end trace of a Sangam Import (Scout) turn. It runs from the choose_sources pause through research, save_research refusals, brief publish, the Review save transaction and promote, to staff undo. It lists the refusal points, the pauses, the fact end-states and the unfinished work.
tags: [import, scout, ingest, workflow, brief, promote, undo, human-in-the-loop]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-13T18:20:59.385Z
sources:
  - id: openwiki-source-813dbe9c3eeb378112388ccd
    resource: repo://backend/app/agent/middleware.py
  - id: openwiki-source-11c734346bddf773fd80ed0e
    resource: repo://backend/app/api/routes/ingest.py
  - id: openwiki-source-62958d5b14b0717233a7ec0b
    resource: repo://backend/app/ingest/agent.py
  - id: openwiki-source-7808196f4aecdc53b9018ae9
    resource: repo://backend/app/ingest/brief.py
  - id: openwiki-source-979b9329025accfea8018c8b
    resource: repo://backend/app/ingest/contract.py
  - id: openwiki-source-7d480e75db10aae51a0f227b
    resource: repo://backend/app/ingest/middleware.py
  - id: openwiki-source-b16585eb308b018d24ffae26
    resource: repo://backend/app/ingest/promote.py
  - id: openwiki-source-3dbb7a958f50a2650e081c34
    resource: repo://backend/app/ingest/run_sources.py
  - id: openwiki-source-5ca431fb0f110b9a36d2d445
    resource: repo://backend/app/ingest/tools/catalog_tools.py
  - id: openwiki-source-2df755596e53353deddeb8d3
    resource: repo://backend/app/ingest/tools/pipeline_tools.py
  - id: openwiki-source-51e6adf4243b3601b40e5803
    resource: repo://backend/app/ingest/tools/research_tools.py
  - id: openwiki-source-98ca8658ce31f093cdacdd76
    resource: repo://backend/app/ingest/undo.py
  - id: openwiki-source-5ff63cf3bcc0508701587aa2
    resource: repo://backend/tests/test_import_undo.py
  - id: openwiki-source-77a336ada304965e7aa89c22
    resource: repo://backend/tests/test_storage.py
  - id: openwiki-source-88fdf568b0f25b1d21f041da
    resource: repo://docs/CHANGELOG.md
  - id: openwiki-source-bf630aa6c5a52f454e55b12d
    resource: repo://frontend/features/ingest/components/ScreenReview.tsx
  - id: openwiki-source-816413157b8843ac76fe4f8f
    resource: repo://frontend/features/ingest/lib/saveActions.ts
  - id: openwiki-source-f664951b6aca64864b5843f3
    resource: repo://frontend/features/ingest/lib/staffActions.ts
generated: { by: "openwiki/0.7.2", at: "2026-10-13T18:20:59.385Z" }
---

# One Import Turn: choose_sources to Undo

Sangam Import (on screen: Scout) researches one funder or NGO per subagent, stores cited findings, merges them into a per-organisation **brief**, and only later moves the brief into catalog tables. This page follows one organisation through that path in order. It marks every place where the turn is refused or pauses for a person. For the agent roster, roles and RLS, see [Sangam Import / Scout](../architecture/sangam-import-scout.md), [Auth, roles and RLS](../architecture/auth-roles-rls.md) and [Frontend](../architecture/frontend.md). For the catalog tables that `promote()` writes, see [Data and migrations](../architecture/data-and-migrations.md).

The central idea is that **research and catalog are two separate steps**, and the **brief is the record that sits between them**. `save_research` writes findings (`entity_research` row plus the brief). Only `save_to_catalog` writes catalog rows, and it reads the brief, not one research run (`brief.promotable`).

## The turn at a glance

```mermaid
sequenceDiagram
    participant P as Person
    participant S as Supervisor
    participant R as entity-researcher
    participant SR as save_research
    participant B as Brief in source-archive
    participant RV as Review screen or catalog-writer
    participant SC as save_to_catalog
    participant DB as Postgres catalog

    P->>S: message plus ticked sources
    S->>P: choose_sources pause, only if nothing ticked
    P-->>S: answer is the run's sources
    S->>R: task per organisation
    R->>R: pulls only chosen sources
    R->>SR: save_research findings
    SR-->>R: REFUSED, fix and save again
    SR->>DB: upsert entity_research on slug and day
    SR->>B: merge and publish brief
    P->>RV: Review, answer questions, save
    RV->>SC: slug and decisions
    SC->>DB: undo.start opens promotion
    SC->>DB: promote reads brief.promotable
    SC->>DB: record_save on research row
    SC->>DB: undo.finish keeps or drops promotion
    SC->>B: write fact states back
    P->>DB: staff undo promotion
```

*Order of one turn: sources are chosen, the researcher saves findings (with refusals), the brief is published, the save transaction runs, and staff may undo.*

## 1. choose_sources: the first pause

- The supervisor must call `choose_sources` first and alone (`pipeline_tools.choose_sources`). It takes `web`, `library`, `vault_org`, `vault_docs` and `staff_paths`. The result is an artifact that `run_sources.Sources` turns into the run's allowed sources. The person's answer replaces the model's proposal.
- **When it pauses.** `INTERRUPT_ON["choose_sources"]` has a `when=ask_for_sources` condition. The sources ticked in the right rail go out as AG-UI context (`TICKED_SOURCES`). If any were ticked, `TickedSources` appends a note and rewrites the model's `choose_sources` arguments to exactly the ticks, so **no card shows**. With nothing ticked, the run pauses on `SourcesCard`, and the person can approve, edit or reject.
- **Refusals inside the tool:**
  - staff spreadsheets requested by a non-staff caller;
  - Doc Vault files the caller cannot read, or that are not in that org's vault;
  - nothing chosen at all.
  
  Each returns `REFUSED:` with no artifact, so the choice stays unanswered. Staff paths are validated and registered as `documents` rows.
- **Reject means web only.** `run_sources.chosen()` reads the latest `choose_sources` ToolMessage. An artifact gives that `Sources`. An error status (the person rejected the card) gives `WEB_ONLY`. No answer yet gives `None`. The answer exists only in the checkpoint's messages.
- **Enforcement is two-sided.** `ChosenSources` on the supervisor refuses every `task` call until the choice is answered, failing closed on unreadable state. It also sets the `CURRENT` context variable around each subagent. `RunSources` on each subagent then refuses any pulling tool outside the choice:
  - web tools when web is off;
  - library tools when library is off;
  - `read_source_rows` and `read_workbook` unless `documents=` is a subset of the picked spreadsheets;
  - vault tools outside the picked files.
  
  Only `PULLING` tools are ever refused. A subagent outside a `task` has `CURRENT = None` and reads nothing.

## 2. Research

The supervisor plans (`write_todos`), reads `funder_dossier` to see what the catalog already holds, and launches one isolated `entity-researcher` per organisation, in waves bounded by `MAX_PARALLEL_RESEARCH`. If vault files were chosen, a `vault-reader` runs first. If workbooks were picked, a `workbook-reader` returns the names so that one researcher per name can follow. See [Sangam Import / Scout](../architecture/sangam-import-scout.md) for the roster. The research-specific mechanics are:

- The researcher's tools are `research_goals`, `funder_dossier`, library, workbook-row, web and PDF readers, and `save_research` (`RESEARCHER_TOOLS`). It has no catalog-write tool.
- Every web read passes `check_url` (source registry plus robots) before the fetch and again on every redirect (`_client` hook). A `REFUSED:` there is final. `search_public_sources` marks hits `READABLE` or `HELD`, and a held hit is a dead end.
- `read_page` and `fetch_document` archive what they read to the `source-archive` bucket. Later, `promote()` turns each cited source into a `documents` row from that archive.
- The researcher's middleware stack adds `SaveRefusal`, `RunSources`, the staff-last lock, optional `ReadingLimit` and call limits, model fallback, an escalation to the strong model after a malformed save, and a rubric grader that allows one revision. Page and call limits are unset by default.

## 3. save_research: where saves are refused

`save_research` is the only tool on this path that writes, and it writes findings, not catalog rows. It should be called once, last. It returns `REFUSED:` text, rather than raising, in these cases, in this order:

1. **NGO by a non-steward.** `entity_kind == "org"` and the caller is neither staff nor a steward. The researcher is told to report in its summary instead.
2. **Unanswered fields.** `contract.unanswered()` finds a field of the kind's contract with neither a finding nor a gap. Yearly concepts need one answer per asked fiscal year (default: the recent years), and identity concepts also need `themes`. Statuses other than `complete` and `partial`, and kind `unknown`, are exempt. A gap must be `not_stated`, `blocked` or `not_reached`, with a reason.
3. **Another person's row.** A non-staff caller would overwrite a same-day row saved by someone else. The reply tells the researcher to report `saved=true` with the existing slug.
4. **A shorter save.** The stored row for that slug and day has more findings than the offer, and `replace=true` was not passed.

On success, one transaction upserts `entity_research` keyed on `(slug, researched_on)`, recording `researched_by`. The reply tells the researcher to report `slug` and `saved=true`. It also flags numbers that appear only inside quotes (`quoted_only`) so the researcher can add them as findings. Failures from a save that cited staff sources return the exception type only, so no confidential cell text reaches logs or the model.

## 4. Brief publish

Right after the upsert, `save_research` calls `brief.publish()`. It does not wait for `make client-docs`.

- **The brief is the record.** It is a markdown file at `source-archive/entities/<slug>.md`. There is no brief table. Each fact line carries its typed finding in a hidden `<!-- fact {json} -->` block, and facts no column can hold go in `<!-- unplaced {json} -->` blocks. Both are read back by `brief.record()`.
- **Merge rule.** `build()` reads the published brief and merges every `entity_research` row for the slug into it (`rows_for`). Findings are keyed by `fact_key`, which uses per-concept identity fields from `_SAME_FACT`. A later run replaces an earlier one unless the earlier source is stronger, compared by evidence tier and then confidence. `wrong_entity` rows add nothing. A fact the latest run did not find is not dropped. Private (staff and vault) findings never enter the public brief, and a summary written from them is replaced by `PRIVATE_NOTE`.
- **Fail-safe.** If Storage cannot be read, `build()` raises, `save_research` logs a warning, and the brief is left as it was. The findings are saved either way. With Storage unconfigured, the upload is a no-op and the reply says the brief appears in `docs/entities/<slug>.md` after `make client-docs`. The text `brief is published` appears only when it actually was, and the Import UI's milestone strip matches that phrase (`test_storage.py` pins it).
- **Re-publish.** `publish_brief` (staff only, on the supervisor) re-renders one slug or all of them, for research saved before publishing existed or after a renderer change.
- Research older than the typed finding shape (`TYPED_SINCE`) renders in the brief but carries a note that it cannot be promoted. It has to be re-run.

## 5. Review and save: the save_to_catalog transaction

Saving happens two ways. Both call the same function, so the same guards and the same undo apply:

- **Review screen:** `POST /api/ingest/research/{slug}/save`. `ScreenReview` posts the person's `decisions`, and `GET /api/ingest/research/{slug}/review` fills the card.
- **Chat:** the `catalog-writer` subagent calls `promote_research`. `SaveQuestions` pauses every call with the planned rows, coverage line and the funder's open questions. Only the person's `edit` can set `decisions`, and anything the model writes there is dropped. An empty slug is still approved, but its questions are held, not asked.

`save_to_catalog(slug, caller, decisions)` does the following:

1. **Role gate.** A non-staff caller must pass one slug. For a funder, `can_save_funder()` is required. For an NGO, the org must already be held (resolved, or matched by a mergeable method), and the caller must be able to research it. Otherwise it raises `SaveRefused`. That is HTTP 403, or a `REFUSED:` reply in chat. No research rows raises `LookupError`, which is 404.
2. **Read the record.** `_research_rows` takes the newest row per entity and swaps in the brief's facts via `brief.promotable()`. Non-staff callers do not get private findings, and vault findings are added only for a writer or person.
3. **One transaction per organisation**, with one retry if a concurrent save raises `UniqueViolation`:
   1. `undo.start` inserts a `promotions` row (research id, slug, `promoted_by`) and sets `sangam.promotion_id` locally, which turns on the write log for the rest of the transaction.
   2. `promote()` writes the catalog.
   3. `_record_save` stores what the save wrote on the research row (`saved`, `saved_at`) with before/after counts. Afterwards a plan reads every row as `same`, so this is the only record of what the profile held before.
   4. `undo.finish` clears the setting. If `catalog_writes` has no entry for the promotion, the promotion row is deleted and `promotion_id` is `None`. The route returns `promotion_id` to staff only.
4. After commit, `_publish_states` writes each fact's end-state back into the brief. A failure there is only logged, because the catalog is already committed.

### What promote() does

`promote()` runs the kind's branch (`_promote_funder` or `_promote_org`). The model never writes SQL. Fixed-SQL writers in `writer.py` do. A funder's `Gate` sorts each fact into five cases: same value, newer source (update), older or undated source (ask), close name (ask update, new or skip), and new (insert). An NGO fills blanks and reports conflicts, and asks only about a trigram-close name. `Gate(plan=True)` writes nothing, and that is what `compare_with_catalog`, coverage and the Review card use.

Before the branch, the guards hold findings:

- research saved under a pre-typed shape is turned away with "re-run the research";
- unmarked or cell-mismatched staff figures are held;
- vault findings and private sources are held at promotion.

For a funder the order is:

1. Resolve the entity, preferring the one an earlier save linked.
2. Write the funder and its tags.
3. Write a `documents` row for every public source a fact cites.
4. Write CSR years.
5. Write programmes parents-first, with spend lines as `kind='component'` programmes.
6. Write the remaining facts in `WRITE_ORDER`.
7. Write `document_links` and link the research row to the entity.

### Fact end-states

Every fact ends in exactly one state. `_unsettled` guarantees this: a fact no writer reached becomes `held` with the reason, or `no column` when Sangam has no table for its concept.

| State | Meaning in the brief |
|---|---|
| `written` | Saved in Sangam (covers writer statuses added, updated and planned) |
| `confirms` | Sangam already holds this value (matched) |
| `waiting` | A question is open for a person |
| `conflicts` | Sangam holds another value and a person decides |
| `kept` | A person kept Sangam's value |
| `skipped` | A person skipped it |
| `held` | Not saved, with a reason (guard, unmatched name, unanswered question) |
| `no column` | Sangam has no field for it yet |

`waiting`, `conflicts`, `held` and `no column` are listed under "Not in Sangam yet" in the brief. A fact keeps its last state until it is promoted again.

## 6. Undo (staff)

- `POST /api/ingest/promotions/{id}/undo` (staff only) calls `undo.undo()`. It locks the promotion and refuses if it is already undone. It then replays `catalog_writes` newest-first in one transaction, deleting what the save inserted and restoring `old_row` for what it updated. Table names are checked against `LOGGED`, which holds 19 tables.
- **All or nothing.** Each reversal requires that the row still equals the logged `new_row`. Otherwise `UndoRefused` rolls everything back ("a row has changed since this save"), and a row now referenced elsewhere is refused too. The route maps this to 409. `test_a_row_changed_since_refuses_the_whole_undo` pins it.
- After success, the promotion is stamped `undone_at`/`undone_by`. A reversed funder or org insert first unlinks `resolved_funder_id`/`resolved_org_id` on the research. The research reads as unsaved again (`saved = NULL`) once no live save of it remains.
- `DELETE /api/ingest/research/{slug}` (`undo.delete_research`) removes research that was never saved, or whose saves were all undone. It returns 409 while any save stands. The UI offers undo and delete in `ResearchedRecently`.
- Undo reverses catalog rows only. It does not rewrite the brief's fact states.

## Pause points

| Pause | Where | Condition |
|---|---|---|
| `choose_sources` card | `INTERRUPT_ON` | Only when nothing was ticked before sending |
| `run_import_now` approval | `INTERRUPT_ON` | Bulk adapter writes; not part of the per-organisation research path |
| `promote_research` approval | `SaveQuestions` on the catalog-writer | Every call, carrying open questions |
| Review card | `/import` screen | Saving straight from the screen with `POST .../save` |

On the frontend, `useRunPause` records the tool a run stopped on from the interrupt event, and `StepBar` shows Start, Working, Review and Done.

## Unfinished and caveats

Per the "Not finished" table in `docs/CHANGELOG.md`:

- **Researcher contract M5.** Backfilling KABIL and Axis on staging is not done. M1 to M4 (#194 to #197: contract refusal, brief as the record, promotion reads the brief, cited sources become `documents`) have shipped.
- **Programme themes, step 5.** `write_funder_tags_from_programs` (PR #172) is unmerged.
- **Guided import.** The "review follow-ups" list from `2026-10-09-import-guided.md` is still open.
- **Owner pool.** Ask's SQL and Import still run on the owner pool. Each Import tool therefore checks the caller scope itself, rather than relying on RLS. The fix branch is unmerged.
- `docs/INGEST.md` predates the brief-as-record work. Where it disagrees with `docs/ARCHITECTURE.md` section 4, section 4 is right.

## Where to change things

- The sources contract lives in `run_sources.py`. A new pulling tool must be added to one of its `*_TOOLS` sets, or it is never refused.
- A new fact concept needs entries in the finding model, `brief.headline`, `_SAME_FACT` and `ORDER`, and a writer branch in `promote.py`. Without a writer branch it is reported as `no column`.
- A new catalog table that `promote()` writes must be logged by a trigger and added to `undo.LOGGED`, or undo refuses it as "not a catalog table".
- Tests to read: `test_import_sources.py` (pauses and source enforcement), `test_import_undo.py` (start, finish and undo, including no-op saves and the screen path), `test_import_roles.py` (role gates on save), and `test_storage.py` (the published-brief message).
