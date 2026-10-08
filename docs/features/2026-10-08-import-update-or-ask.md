# Import: update what is clearly the same, ask about the rest

Status: Draft v1 · 2026-10-08 · funders only

## Context

Promoting funder research writes straight into the catalog, and the supervisor launches `catalog-writer` "as soon as the researchers report, without being asked" (`app/ingest/instructions.md`). Three problems follow:
- A newer research run overwrites stored values even when its source is older. Example: `grant_size_max` ₹50L (2024) → ₹25L (a 2021 page).
- The old value is thrown away, because `_promote_funder` discards the `changes` dict.
- A near-duplicate gets a second row instead of a question. Example: "Nanhi Kali" next to a stored "Project Nanhi Kali".

Agreed with the user: no new table. Read tools pull what is already stored. A person is asked, in the chat, through LangChain's `HumanInTheLoopMiddleware`, only when the answer is not obvious, and answers by clicking a button per question.

## The rule: five cases per finding

| # | Case | Example | Action |
|---|---|---|---|
| 1 | Same key, same value | FY24 spend ₹945 Cr = ₹945 Cr | nothing (matched) |
| 2 | Same key, new value, source as recent or newer | intake_mode open_call (2023) → invite_only (2025) | update automatically, list it in the report |
| 3 | Same key, new value, source older or either side undated | grant_size_max ₹50L (2024) → ₹25L (2021) | **ask**: update / keep stored |
| 4 | No exact key, a close match | "Nanhi Kali" vs stored "Project Nanhi Kali" | **ask**: update that row / add new row / skip |
| 5 | Nothing close | FY25 CSR year, only FY24 stored | add automatically |

These stay held as today: a different CIN, a classification a person confirmed (`classification_confirmed`), and a funder-name trigram match.

Defaults chosen for the three open questions:
- Undated on either side → ask.
- "Close" is decided in code with the matcher's existing similarity (`matcher.py` `TRIGRAM_FLOOR` / `core_similarity`), not judged by the model.
- NGOs keep `write_org`'s fill-blanks rule. This plan covers funders only.

## Approach

**1. Classify before writing** (`app/ingest/promote.py`)
- Add `classify(conn, row) -> list[Decision]`. It only reads.
  - It reuses promote's mapping: `funder_from`, `csr_years_from`, `_row_identity`, `resolve_funder`, `_place`, `resolve_classification`.
  - It SELECTs each stored row by the writer's natural key (`FUNDER_ACTIVITY_KEY`, `fiscal_year`, `PROGRAM_KEY`, `METRIC_KEY`, `CONTACT_KEY`).
  - It compares values with `writer._diff`.
- Close matches for case 4 are a trigram query on the name column of the same funder's rows:
  - `funder_activity.project_name` / `partner_name`
  - `programs.name`
  - `contacts.name`
- Recency for cases 2 and 3 compares the stored `as_of` against the finding's `as_of`, falling back to `fiscal_year`.
- `funder_from` currently hard-codes `as_of=None`. Carry the identity finding's `as_of` through instead, so funder fields have a date to compare.
- `Decision` is `{id, case, table, key, label, changes: {col: {old, new}}, stored_as_of, new_as_of, candidate_row_id}`, and every stored row is cited `[funder:N]` / `[activity:N]`.

**2. Read-only supervisor tool `compare_with_catalog(slug)`** (`app/ingest/tools/catalog_tools.py`)
- Calls `classify` and returns JSON grouped by case.
- The UI renders it, and the model summarises cases 3 and 4 in one line each.
- `try/except` returns `"compare_with_catalog failed: …"`.
- Register it in `TOOLS` (`app/ingest/agent.py`), name it in `instructions.md`, and label it in `frontend/features/ingest/lib/toolLabels.ts` as "Comparing research with the catalog".

**3. Promote applies decisions** (`promote.py`, `writer.py`)
- `promote(conn, row, decisions: dict[str, str] | None = None)`. `decisions` maps decision id → `update | keep | new | skip`.
- Cases 1, 2 and 5 are written as today.
- Case 3 is written only on `update`.
- Case 4:
  - `update` rewrites that row's key column to the researched name. Before the UPDATE, check the target key is free; if it is taken, hold the item with a reason rather than letting the unique constraint abort the funder.
  - `new` inserts a new row.
  - `skip` does nothing.
- An undecided case 3 or 4 item is held with "waiting for a person", never written.
- Keep the changes: add `report["changes"]` from every writer's returned `changes`, which `_promote_funder` currently discards.

**4. One pause, a button per answer: `SaveQuestions(HumanInTheLoopMiddleware)`** (`app/agent/middleware.py`, on the `catalog-writer` spec)
- `aafter_model` computes the open case 3 and 4 questions for a `promote_research(slug)` call (`open_questions`, a plan-mode read). Its `when` predicate pauses only if there are any.
- The pause is LangChain's own `HITLRequest`. Its action request carries `questions`, each with an `id`, a `case` and its `choices`. The frontend reads the same shape every other Import pause uses.
- The person resumes with an `edit` whose args hold `decisions: {question_id: choice}`, which the tool applies. A `reject` saves nothing. An `approve` saves the clear cases and holds the questions.
- `awrap_tool_call` drops any `decisions` the model wrote itself; only a person's edit sets them.
- An empty-slug sweep is never paused, and its questions are held.
- The tool itself never interrupts and never raises.

**5. Prompts**
- `instructions.md`: replace "without being asked" with this sequence:
  - research
  - `compare_with_catalog`
  - summarise
  - launch `catalog-writer`
- The pause, not the prompt, is what stops an unsafe write.
- `prompts/catalog_writer.md`: report held items verbatim, including "waiting for a person".
- `skills/catalog-mapping/SKILL.md`: build the comparison on `compare_with_catalog`.

**6. Frontend** (`frontend/features/ingest/`)
- `components/ChangePreview.tsx`: renders the `compare_with_catalog` result from `ImportWorkspace.tsx`, next to `SubagentBoard`, parsed the same way `SubagentBoard.tsx` does.
  - Five groups, showing `column: old → new` with dates.
  - Marked "older source" when the new value's date is older.
  - New and same rows are shown as counts.
- `components/SaveQuestions.tsx`: renders the `promote_research` pause via CopilotKit `useInterrupt` (`@copilotkit/react-core/v2`), the same way the other Import pauses do.
  - One row per question, with a clickable button per choice: *Update / Keep* for case 3, *Update that row / New row / Skip* for case 4.
  - **Save** resumes with `{decisions: [{type: "edit", edited_action: {name: "promote_research", args: {slug, decisions}}}]}`. It is enabled once every question has an answer.
  - **Don't save** resumes with a `reject`.
- Use only existing tokens and `components/ui/` primitives. Per CLAUDE.md, an Import screen change updates the "Sangam Design System v2" UI kit in the same PR.

## Milestones (one PR each, branch from latest `origin/master` in a worktree)

| # | PR | Exit gate |
|---|---|---|
| M0 | This document, committed before code | doc on branch, PR open |
| M1 | Backend: steps 1–5, starting with the interrupt spike | `pytest -m "not integration"` and `ruff check .` pass. Locally: case 2 updates silently, case 3 pauses, case 5 adds without pausing. |
| M2 | Frontend: step 6, plus the design-system sync | `npm run lint` and `npm run build` pass. The preview and the question card resume the run with per-item choices. |

No new tests (repo rule). Fix only the existing tests these changes break: tools named in prompts, spec-vs-prompt, and the registry walk.

Master has moved since this was read (#113, 0034 folds grants into `funder_activity`), so re-read `promote.py` and `writer.py` on the new base before M1.

## Critical files

- `backend/app/ingest/promote.py`: `classify`, `decisions`, `report["changes"]`, `as_of` in `funder_from`
- `backend/app/ingest/writer.py`: reused (`_diff`, keys); the case-4 key rename with its collision check
- `backend/app/ingest/tools/catalog_tools.py`: `compare_with_catalog`, and `promote_research` with the interrupt
- `backend/app/ingest/agent.py`, `instructions.md`, `prompts/catalog_writer.md`, `skills/catalog-mapping/SKILL.md`
- `frontend/features/ingest/ImportWorkspace.tsx`, `components/ChangePreview.tsx`, `components/SaveQuestions.tsx`, `lib/toolLabels.ts`

## Verification

1. `make up && make seed`, sign in as staff, then open `/ask?view=import`, and research a funder already in the catalog.
2. Through `make psql`, set up one stored row for each case:
   - case 2: an older `as_of` on `intake_mode`
   - case 3: a newer `as_of` on `grant_size_max`
   - case 4: rename a stored project to a close variant
3. Re-research the funder:
   - The preview shows each item in the right group.
   - Cases 2 and 5 are written. Confirm with `make psql`.
   - The run pauses with questions for cases 3 and 4 only.
4. Choose "Keep" on case 3 and "New row" on case 4:
   - the case 3 value is unchanged
   - a second row exists for case 4
   - the report lists every change old → new
5. Re-run with nothing changed: no pause, and everything reports `matched`.
