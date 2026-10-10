# Import: guided flow for NGO staff

Status: Draft v1 · 2026-10-09

## Context

The design is "Import — guided" in Claude Design, project "Sangam Design System v2"
(`3b0e9aeb…`):
- `templates/import-wizard/ImportWizard.dc.html` is the screen.
- `templates/import-wizard/FLOW.md` is the audit and the today → guided map.

This plan turns that design into code.

`/import` today (after #127) is a chat:
- **Start.** A blank input and 5 suggestion buttons (`ImportWorkspace.tsx`).
- **Progress.** Shown by `Milestones`, `SubagentBoard`, `RunStatus` and the failure lines.
- **Pauses.** `PausedPick` (folder, then files) and `SaveQuestions` (every
  `promote_research`).
- **Coverage.** `CoverageChart` regex-parses the `coverage_report` text.
- **Around the chat.** `ImportView.tsx` shows ResearchShelf, RunHistory, ReviewQueue,
  ProposalList and the 79-card SourcePanel.

What breaks for a non-technical user:
- Starting needs a prompt, not a choice.
- Engine words show everywhere: bucket, catalog, promote, researcher, subagent, HTTP 403,
  steps.
- Progress is counted in tool calls.
- The two source pauses ask the same thing twice.
- Save questions show raw columns.
- Nothing says how much of the profile is now filled in.

Goal: a four-step flow, **Start → Working → Review → Done**, in plain words. Chat stays
reachable as "Advanced". The agent, its tools and its interrupts stay as they are. This is
a new client over the same run, plus one JSON endpoint.

**Scope:** research runs (`entity-researcher` → `save_research` → `promote_research`).
The adapter pipeline (`run_import_now`, `india_csr`, `gdelt`) keeps the chat for now. Its
"news" task card composes the same prompt the suggestion button sends today.

## Word list (applies to every milestone)

| Engine | Staff see |
|---|---|
| bucket | folder |
| catalog | Sangam / the profile |
| promote / write | save |
| research brief | research notes |
| researcher, writer, subagent | hidden |
| claimed | self-reported |
| evidenced | confirmed |
| refused / HTTP 4xx | couldn't open — the site said no |
| scanned PDF | scanned — no text to read |
| `not_found` status | couldn't find it |
| `wrong_entity` | found a different organisation |
| trigram queue item | "Is X the same as Y?" |

These live in one module, `frontend/features/ingest/lib/words.ts`. `toolLabels.ts` and
`failures.ts` read from it, so no component hard-codes engine terms.

## Milestones (each is one PR)

- **M1: coverage as JSON.**
  - **Why a migration.** A dry-run compare after the save reads every row as `same`, and
    `promote_research` kept no record of what it wrote. So the "before" for the Done step
    has to be stored at save time.
  - **Code**
    - Migration `0038_research_saved.sql` adds `entity_research.saved` (jsonb) and
      `saved_at`. It is 0038 because `fix/pr100-port` already has 0036 and 0037.
    - `promote_research` stores, per research row, what the save wrote:
      - rows added and updated per concept (`coverage.changes_by_concept`);
      - the entity's rows per concept after the save;
      - held, skipped, reasons and conflicts.
    - Per-concept counts come from the labels promotion already counts under
      (`funder_activity (spend)` → `csr_spend`, and so on), plus the entity and its CSR
      years. A unit test fails if a new `_count` label has no concept.
    - `GET /ingest/research/{slug}/coverage` (`catalog_tools.coverage_view`) returns
      `coverage.compute()` as JSON, with per concept `added`, `updated`, `before` and
      `after`. Its `stage` is one of:
      - `saved`: from the stored save.
      - `planned`: a funder not yet saved, from a dry run. Documents read 0, because a
        dry run does not archive them.
      - `unsaved`: an NGO not yet saved. No before/after, since its write cannot be
        dry-run.
    - It returns 404 when there is no research for the slug.
    - The agent's text tools (`coverage_report`, `compare_with_catalog`) are unchanged.
    - `CoverageOut` in `schemas/ingest.py`; `ResearchCoverage` in `types.ts`.
  - **Exit gate:**
    - `pytest -m "not integration"` is green.
    - `ruff check .` shows nothing beyond the B008/RUF012 pattern master already has.
    - Local `sbi-foundation` returns 15/23 concepts.
    - A real save of `infosys-foundation`, rolled back, records 0 → 17 facts.
  - **The per-answer findings M5 needs** (basis, quote, page) are added to this response
    in M5, not here.

- **M2: Start step.**
  - **Code**
    - `ImportWorkspace` gets a `step` state (`start | working | review | done`) derived
      from the turn and interrupt state, not stored separately.
    - Start shows 3 task cards (funding profile · NGO profile · news), name chips
      (Enter adds one), and for news "Where from?" and "How many articles?".
    - A `composePrompt(task, names, opts)` helper produces the same text staff type today,
      so the agent sees no change. Chat moves behind an "Advanced" link.
    - `ImportView` start screen:
      - **"Waiting for you":** ReviewQueue as one yes / no / not sure per name, with no
        scores.
      - **"Researched recently":** ResearchShelf as name, kind, answers/confirmed,
        Saved / Not saved / Not found, and Research notes.
      - **Sources:** a collapsed "Which websites is Sangam allowed to read?" with 3
        groups: reads, allowed but not set up, not allowed.
    - RunHistory, ProposalList and the full SourcePanel move into one collapsed "Details"
      section. Decided 2026-10-09: no new permission; Import is already staff-only, and the
      org member role is about NGOs, not Sangam staff.
    - **Answering a name** (decided 2026-10-09): `POST /ingest/queue/{id}` with
      `{answer: same | different, candidate_id}`.
      - Same: the name becomes an alias of the top candidate (funders, orgs, locations), and the
        item is `accepted`. The matcher reads aliases, so the next run resolves the name itself.
      - Different: `rejected`; nothing is created or joined.
      - Not sure: no call; the item stays pending.
    - "Researched recently" shows answers (fact count), not "confirmed" counts: which findings
      count as confirmed is defined in M5. Saved rows link to their profile by id.
  - **Exit gate:**
    - Each task card starts a run whose first message matches today's suggestion text.
    - Advanced chat still works.
    - Both groups render on desktop and at 375px.

- **M3: Working step.**
  - **Code**
    - Replace `Milestones`, `SubagentBoard` and `RunStatus` with `WorkingBoard`:
      - a totals line ("3 of 8 ready · N pages read · N answers found") and one overall
        bar;
      - one 48px row per organisation in a fixed order (name · mini bar · now reading ·
        "4 of 10 found" / ✓ Ready / Paused);
      - a "Just now" list of the last 4 events.
    - Data comes from the steps we already stream:
      - The researcher `task` step per organisation gives the row and its status.
      - `read_page` and `fetch_document` args and results give "now reading" and
        ok/refused.
      - `save_research` findings give answers found.
      - The step for each row comes from the tool kind:
        `research_goals` → `read_*` → `save_research` → `promote_research`.
    - Move the row/step derivation into `lib/board.ts`, out of `lib/milestones.ts`, which
      is deleted once nothing imports it.
    - Each row expands to "What Sangam read": one line per page, labelled Read /
      Couldn't open / Scanned through `stepNote()` in `words.ts`.
    - A finished researcher whose writer is waiting shows "Done — waiting for the others
      before you can review".
    - **Telling researchers apart** (decided 2026-10-09): the Import agent streams with
      `emit_subagent_events=True` (AG-UI "attributed"), so each subagent step carries
      `subagentRunId`. `useAgentChat` puts it on `TraceStep.lane` and maps a lane to its
      `task` call from `SUBAGENT_STARTED.parentToolCallId`; failing that, `board.ts` matches
      the lane's `research_goals` / `save_research` name to the row.
      - A reloaded thread has no lanes: rows show status only, and "now reading" moves to
        the totals line.
      - The board reads two tool replies as prose (`concept -> table` lines and "most likely
        scanned"); `TestTheWorkingBoardReadsThesePhrases` pins both.
  - **Exit gate:**
    - One live local run with 3 funders shows 3 stable rows, at least one Couldn't open
      line, and no tool name or HTTP code anywhere on screen.

- **M4: the source pause as one card.**
  - **Code**
    - `PausedPick` becomes `SpreadsheetsCard`: "Should Sangam also look at your team's
      spreadsheets?", then folder, then files (suggested ones pre-ticked), then "Use
      these files" / "No, only public websites".
    - It answers both interrupts from one card:
      - approve, or edit-approve, `list_bucket_files` with the chosen folder;
      - then answer `select_source_files` automatically with the ticked files.
    - "No" rejects the first. #127 M3-B already makes that read nothing.
    - The `sourcePick.ts` logic stays.
    - At a pause the run is not running, so the board's status line says "Finished". The card
      owns that moment: the line should read "Paused — waiting for you" while it is open.
    - **As built:** the first pause comes before any listing, so the card fetches the
      bucket's workbooks from a new staff-only `GET /ingest/workbooks?bucket=`. Files in the
      agent's proposed folder are pre-ticked. "Use these files" approves the listing (narrowed
      to the folder when every tick is in one) and the ticks answer `select_source_files` as
      an edit. If the listing fails, "Let Sangam list them" falls back to the old two-step
      path. Cards signal an open pause through `PauseSignal`.
    - "No" is remembered too: a later `select_source_files` is rejected unasked.
    - Dropped: choosing another bucket. The card lists the proposed bucket only, which is
      always `staff-sources` today; folders are grouped by full path.
  - **Exit gate:**
    - Choosing files reads only those files.
    - "No" reads none, and coverage shows `blocked: staff declined` for staff-sourced
      cells.

- **M5: Review step.**
  - **Code**
    - `SaveQuestions` becomes `ReviewCard`, one per paused organisation. It shows:
      - up to 10 answers, each tagged Confirmed / Self-reported / Not mentioned /
        Couldn't read, with "See proof" opening the quote, page and link from the
        finding's evidence;
      - then "Before saving, one question" for each open question, with keep / update /
        new / skip relabelled: Keep what Sangam has / Use the new one / Add it
        separately / Skip.
    - Answers come from the `promote_research` interrupt payload plus the M1 endpoint.
    - An existing NGO shows "Saving only fills in answers that are empty".
    - Grant and amount values render as ₹ crore / lakh through a shared `formatInr()`,
      never as JSON.
    - **Verdict line:** see Open questions. It ships hidden unless decided.
    - **As built:** answers come from `GET /ingest/research/{slug}/review`
      (`app/ingest/review.py`), not the M1 coverage endpoint. It returns labelled facts,
      not raw findings, so no column name or enum code reaches the screen. A funder's
      questions and "What saving adds" come from a dry-run promote. The pause's own
      questions are still the ones answered: the review only supplies their wording, and
      question ids are content hashes, so the two match. Confirmed means a registry, a
      government site, a PDF, or your team's spreadsheet; anything else is
      self-reported.
  - **Exit gate:**
    - SBI review shows tagged answers with working proof links.
    - Approve writes; Skip on every question writes none of those rows.
    - No column names are visible.

- **M6: Done step.**
  - **Code**
    - `CoverageChart` (recharts, regex) is replaced by `DoneReport`, fed by the M1
      endpoint, with no text parsing. `lib/coverage.ts` is deleted.
    - Each saved organisation shows:
      - "16 → 41 facts" and one summary line;
      - one bar per topic (Already in Sangam · Updated · New);
      - for an empty topic, its reason instead of a bar: `not_stated` → "Not on their
        website", `blocked` → "Couldn't read", `not_written` → "Found, nowhere to save
        it", `not_attempted` → "Not looked for".
    - More than 3 organisations get a run total ("142 → 236 facts") and a matrix: one row
      per organisation, one square per topic from `concepts_for(kind)`, filter All /
      Saved / Not saved, a row expands to its bars, and not-saved rows are dimmed.
    - The page ends with Saved / Not saved, Open profile, Research notes, any queued
      name ("Is X the same as Y?"), and "Research something else", which reuses Start
      over.
    - **As built:**
      - Which organisations a run covered comes from the researchers' summaries
        (`slug`) and `promote_research` arguments (`lib/done.ts`). Saved means the
        coverage endpoint's `stage` is `saved` with an entity.
      - A bar is `before − updated` (already in Sangam), then updated, then added.
      - "Research notes" was dropped: no endpoint serves a brief to the browser.
      - Queued names are listed but answered on the Import page under Waiting for you,
        not inline.
      - The step bar reads Review while the review card is open, and Done once the run
        stops without a question open.
      - `recharts` is no longer imported anywhere, but is still in `package.json`.
  - **Exit gate:**
    - Done for a 1-organisation and a 4-organisation run matches the endpoint numbers.
    - The `coverage_report` text in Advanced chat is unchanged.

Order: M1 first, because M5 and M6 depend on it. M2–M4 can follow in any order. M5 then
M6.

## Verification

- Every milestone runs locally against the local stack (`make up`):
  - one 1-funder run and one 3-funder run;
  - screenshots at 1280px and 375px;
  - a check that the Advanced chat still produces today's output.
- Backend: `pytest -m "not integration"`, `ruff check .`.
- Frontend: `npm run lint` and `npm run build` (type errors fail the build).
- No new test files unless a milestone adds a pure helper (`composePrompt`, `board.ts`,
  `formatInr`), which gets a unit test.
- Design parity: compare each step against `ImportWizard.dc.html` in the project. Copy is
  taken from the template verbatim.

## Open questions

1. **Verdict line ("Can we approach them?").** It needs either a backend field, derived
   from eligibility / RFP / contact coverage, or a one-line summary prompt.
   Recommendation: derive it from coverage. It is deterministic and needs no model call.
2. **"Queued" rows** for more than `MAX_PARALLEL_RESEARCH` (8) organisations are not
   designed yet. M3 caps the start screen at 8 names until they are.
3. ~~Admin check~~: decided, a collapsed "Details" section for all staff (see M2).

## Review follow-ups (not done on this branch)

A whole-branch review found these, and they were left open on purpose:

- **No frontend tests.** The frontend has no test runner, so `board.ts`, `done.ts`,
  `sourcePick.ts` and `formatInr` were checked with one-off scripts, not unit tests.
- **The Start step has no 8-name cap.**
- **The review and coverage routes call `get_pool()`** through the agent-tools module
  instead of taking `pool: PoolDep`. `/workbooks` calls storage directly.
- **Done sends one coverage request per organisation at once.** Each unsaved funder is
  a dry-run promote on the shared pool.
- **`_record_save` runs inside the promote transaction,** so a failure while counting
  rolls the save back.
- **Name-based lane matching uses substrings.** It is used only when `laneOwners` has
  no entry for the lane.
- **Queued names on Done come from the queue,** filtered by when the run started.
  Research runs do not queue names today, so the list is usually empty.

## Matching the Import Wizard template

The reference is `templates/import-wizard/ImportWizard.dc.html` in the design project,
with the `board` working view. The UI kit's `Import.jsx` copied the app, so it is not the
reference. It needs a resync after this pass.

- **Working:** a title ("Sangam is researching N organisations", then "Research
  finished"), the totals line and a 20-block overall bar. Each row has 20 blocks, or a
  solid sage bar when ready. The status column reads "Paused" and the now column reads
  "Waiting for your answer" while a question is open. The live status line shows only when
  there are no rows (a news import) or no step could be tied to a row. The prompt the
  task cards wrote is no longer echoed.
- **Review:** the record row from the template. It has a save tick, the kind, "N of M
  confirmed" and "See answers". Each answer's tag opens its proof. Questions sit in an
  inset card under the row. The button reads "Save 1 organisation", or "Continue without
  saving" when unticked. The Working board is hidden while Review is open.
  - **Not done:** the template reviews every organisation at once and ends with "Save N
    organisations". The app still pauses once per catalog-writer. A batch review should
    wait until a live run shows how several writers' pauses arrive through
    CopilotKit: as one event, or one after another.
  - **Also not done:** the verdict line ("Can we approach them?"). FLOW.md lists it as
    needing a backend field.
- **Done:** "Saved N organisations" and the average profile completeness before and after.
  A topic counts towards completeness when it has any row.
  - One row per saved organisation: a 20-block bar, "62% → 77%", "+N facts" and "Show ▾".
    Show opens per-topic blocks with "+N added" or the empty reason, plus "Open profile →".
  - Every organisation in the run gets the same row, 1 or 8, saved or not. An unsaved row
    shows today's completeness and a "Not saved" tag, never a dry run's "would add".
  - Show ▾ holds that organisation's whole report:
    - the per-topic blocks;
    - "What Sangam found", from the review endpoint, with proof;
    - "Not found, and why", using the coverage cell's own reason;
    - held-back counts per topic;
    - "Open profile →", or "Save to Sangam", which asks the agent to save and leads to
      Review.
  - The agent's written report renders as markdown in a "Sangam's full notes" box. It is
    closed once Done shows.
  - `instructions.md` no longer tells the agent to *offer* `promote_research`. In a live
    run it ended with "Promote this now?" instead of pausing for Review.
  - The matrix, squares and filter are gone, because the template uses rows even for 6
    or more organisations.
  - "Research notes" still points nowhere, so the line names Researched recently instead.

## Import gets its own page, with its own threads

- `/import` is a page of its own now, no longer a view inside Ask.
  - A left rail lists the staff member's past imports, newest first and grouped by month, with "+ New import" at the top.
  - The open thread is in the address (`?thread=import-<uuid>`), so a reload or a shared link reopens it.
  - Ask's Tools → Import links to `/import`, and `/ask?view=import` redirects there.
- **Backend:**
  - `GET /api/ingest/threads` lists the caller's `import-%` threads.
  - `GET /api/ingest/threads/{id}/messages` rebuilds one from the ingest graph, which is now kept as `app.state.ingest_graph`.
  - Both are staff-only and owner-checked the same way as Ask chats (`saved_messages` in `routes/threads.py`).
  - No migration: Import threads were already claimed with their first request as the title.
- **A reopened thread** rebuilds its turns, board, Done rows and notes from the saved messages.
  - What it doesn't keep, because those were live-only: which researcher ran which row (`laneOwners`), and the start time used to pick this run's queued names.
  - A thread that stopped at a pause (Review, or choosing files) says so instead of showing a question it can no longer answer.
- **Not done:** the design system's UI kit Import page doesn't have the rail yet. Writing it to the Claude Design project needs approval.


## The person chooses the sources, before anything is read

- **One pause, `choose_sources`, replaces the two spreadsheet pauses.** Working opens on "Where should Sangam read from?":
  - Public websites (on/off) and Sangam's library (public documents it already archived) for everyone.
  - The person's Doc Vault files, one organisation per run.
  - Team spreadsheets, for staff only.
- **No table.** The answer is the tool call's arguments, kept in the thread's checkpoint. "Only public websites" is the same edit with only websites on.
- **Enforced, not advised.** `ChosenSources` launches no subagent before the answer; `RunSources` refuses every read outside it (`app/ingest/run_sources.py`).
- **The vault picker leaves Start**, and Sangam's notes hold only the end-of-run summary: no question about sources comes as prose.
- The board says what the run reads from: "Reading from: Public websites · Your Doc Vault (2)".
