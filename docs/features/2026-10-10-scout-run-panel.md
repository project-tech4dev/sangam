# Scout: an unbroken conversation, with the research pinned on top

## Context

In a Scout thread today each turn renders: You → **WorkingBoard** (big, 7 rows + "Just now" feed) → "Sangam's full notes" (a collapsible box). Two problems the user hit:

1. **The conversation breaks.** The board sits between your message and Scout's reply, and the reply is a "full notes ▴ Hide" box rather than a chat message. Reading the thread you get: You → board → notes box → You → board → notes box.
2. **The research should be on top.** While Scout researches, the progress belongs pinned at the top of the chat; the thread (You / Scout / You / Scout) should flow below it.

Branch `feat/staff-vault-pick` (uncommitted: the `.scout-empty` fix). Frontend only; no backend change.

## Milestone 1 (one PR): pinned run panel + plain chat turns

**`frontend/features/ingest/ScoutChat.tsx`** (started layout):
- New layout inside `.chat-pane`: `<ScoutRunPanel>` first, then `.chat-scroll` (the thread), then the composer.
- The panel shows the **latest turn that has research** (`slugsOf(turn.steps).length > 0` or a running board). Running/paused → `WorkingBoard`; finished → `DoneReport` (moved out of the turn). No research yet in the thread → no panel.
- Each turn in the thread becomes only:
  - `.chat-question` (You), unchanged;
  - **Scout's reply**: the turn's `answer` as a normal chat message — an "S" avatar plus markdown (reuse `AgentNotes`' ReactMarkdown setup, rendered open, no "full notes" toggle);
  - a one-line marker where the research happened: "Researching 7 organisations — progress above" (live) or "Researched 7 organisations" (earlier turns; clicking it shows that turn's run in the panel);
  - failure rows (small, as now).
- `SourcesCard` / `SaveQuestions` (Scout's questions) stay at the end of the thread: they are Scout asking you something, so they belong in the conversation.

**New `frontend/features/ingest/components/ScoutRunPanel.tsx`**:
- A header row always visible: title ("Scout is researching 7 organisations" / "Research finished"), stats, overall segments, and a Hide/Show toggle.
- Body: the existing `WorkingBoard` rows and "Just now" feed, or the `DoneReport`. Open while running, and the person can collapse it to the header.
- `max-height` (about 45% of the pane) with its own scroll, so the thread stays visible below it.

**`AgentNotes.tsx`** becomes `ScoutReply` (or gets a `chat` variant): avatar + markdown, no toggle. Its "Sangam's full notes" wording goes.

**`WorkingBoard.tsx`**: titles say "Scout" instead of "Sangam"; add a `compact` prop that drops the big `h1`/sub when it's inside the panel (the panel header carries the title).

**Styles (`globals.css`)**: new `.scout-run`, `.scout-run-head`, `.scout-run-body`, `.scout-reply`, `.scout-run-marker`, all from existing tokens. Remove `.import-notes*` if nothing else uses them. Mirror the classes in the design system's `tokens/base.css` and the UI kit's Import page (the CLAUDE.md rule; needs V's edit access, otherwise flag it in the PR).

## Not doing

- No change to `useAgentChat`'s turn model, the backend, the interrupts or the thread API.
- No new tests (repo rule); fix any that break.

## Verification

- `npm run lint`, `npx tsc --noEmit`, and `next build` in a throwaway worktree.
- At localhost:3000/import, signed in, reopen the thread from the paste ("Legal and operational standing of the NGOs", then "lets pull it from frrh sheet"):
  1. The thread reads You → Scout → You → Scout, with no board between them.
  2. The 7-organisation board is pinned at the top, and the thread scrolls under it.
  3. Hide collapses the panel to one line; Show reopens it.
  4. A finished run shows the Done cards in the panel, and the review card appears at the end of the thread.
  5. An older turn's "Researched N organisations" marker switches the panel to that run.
- After implementing: explain the agent architecture to the user (supervisor → choose_sources HITL → workbook-reader / entity-researcher / vault-reader / catalog-writer subagents, the middleware, the skills and the model tiers).
