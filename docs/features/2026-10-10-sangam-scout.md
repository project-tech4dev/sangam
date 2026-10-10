# Sangam Scout: Import rebuilt as one chat thread, like Ask Sangam

## Context

Import today is a stepper: Start → Working → Review → Done, with task cards, a name-chip form and panels. The user wants it to feel like Ask Sangam, under a new name, **Sangam Scout**. The URL stays `/import`, and the `import-` thread ids and backend names don't change, so past threads keep opening.

The target experience:
- **Layout like Ask:** thread list on the left, chat in the centre, a side rail on the right.
- **Empty chat:** the three task cards (Research a funder · Check an NGO · Latest CSR news) sit **on top of the composer**. Clicking one writes a default prompt into the composer, for example "Funding profile for ", and the person types the names.
- **Sources in the side rail:** once a funder or NGO card is chosen, the rail shows where Scout may read from: public websites, Sangam's library, the person's own orgs' Doc Vault files to tick, and for staff the team spreadsheets. Nothing is ticked, and Send is disabled until at least one source is.
- **One thread shows everything, start to working:** your message, the working board, the agent's notes, then the review and done cards, all inline as chat turns. There is no step bar. Follow-ups are typed in the same composer.

Builds on `feat/staff-vault-pick`, whose Start-step picks and auto-answered `choose_sources` this reuses unchanged.

## Milestone 1: the chat shell (one PR)

**New `frontend/features/ingest/ScoutChat.tsx`** replaces `ImportWorkspace.tsx` and reuses Ask's DOM and classes (`.chat-pane`, `.is-empty`, `.chat-scroll`, `.chat-turns`, `.chat-turn`, `.chat-question`, `.chat-you`, `.composer`, `.composer-input`, `.composer-row`, `.composer-actions`).
- It keeps `useAgentChat(threadId, "sangam_ingest", "sangam-import", load)` and all of ImportWorkspace's logic: `paused`, `reviewing`, `toReview`, `since`, `preset`, `stop` and start-over.
- **Empty state:** `h2.chat-empty-title` "What should Scout find out?", then the task cards (the existing `.import-tasks` / `.import-task`, filtered by `tasksFor(access)`), then the composer.
  - A card sets `task` and writes `composePrompt`'s lead-in into the composer. Add a small `leadIn(task)` in `lib/composePrompt.ts` alongside the existing strings, so the agent sees the same wording as today.
  - The news card puts "Run an import from India CSR, 10 articles" in the composer and needs no sources.
- **Each turn:** `.chat-question` (You), then `WorkingBoard` → `DoneReport`, the failure rows and `AgentNotes`, exactly as ImportWorkspace renders them today.
- **Interrupts render at the end of the last turn**, not below the page: the `SourcesCard` fallback and `SaveQuestions` / `ReviewCard`.
- **Composer:** ⌘↵ sends, the button flips to Stop while running, and a "New chat" link starts over. Remove the stepper's "Advanced: type your own request" form; the composer is the typed request now.
- `StepBar` and `StartStep` are deleted. The name-chip entry goes with StartStep, since names are typed in the prompt.

**New `frontend/features/ingest/components/ScoutRail.tsx`**, in Ask's rail slot (`.evidence-rail-slot`):
- **Before the first send, with a funder or NGO card chosen:** "Where should Scout read from?" with `<SourcePicker>` (unchanged) holding `sources` state that is lifted into ScoutChat. Send passes it as `preset`, so `choose_sources` is answered automatically, as on this branch now.
- **During and after a run:** "Reading from" (`readingFrom(steps)` from `lib/sourcePick.ts`), then the staff panels that fit a rail: `WaitingForYou`, `RunHistory` and `ProposalList`.
- Below 900px the rail is hidden, as Ask's is, and the source picker moves above the composer.

**Shell (`ImportPage.tsx`, `ImportView.tsx`):**
- `ImportView` keeps `loadPanels` but drops the `.import-intro` header and the Start-only panel block.
- `ResearchedRecently` and the "Details" disclosure (`SourcePanel`, `SourceGroups`) move under the empty-state composer, the way Ask shows its suggestions. They are too wide for the rail.
- `ImportThreads` stays as the left list.

**Name (display only):**
- Use "Scout" / "Sangam Scout" in `app/(agent)/import/page.tsx` (`title`), `ImportLoader` ("Opening Scout…"), `ImportThreads` ("Scout chats", "+ New chat", "Past chats"), `lib/threads.ts` ("Untitled chat"), `DoneReport` ("on the Scout page"), the Ask sidebar's Tools link, and `MethodologyArticle`.
- Update CLAUDE.md and `docs/INGEST.md` with one line: "Sangam Scout (the Import agent, route `/import`)".
- The backend prompt name is not touched.

**Styles:**
- The only new classes are `.scout-rail`, `.scout-rail-section` and `.scout-task-row` (cards over the composer), built from existing tokens.
- Delete the step bar and intro rules (`.import-step*`, `.import-intro`, `.import-start`).
- The Import screen is recreated in the design system, so the same PR updates `ui_kits/sangam-web/Import.jsx` and the components' `.prompt.md` (CLAUDE.md rule). That needs V's edit access on "Sangam Design System v2"; if it isn't granted, flag it in the PR.

## Not doing

- No backend change: `/ingest`, `sangam_ingest`, `choose_sources`, the interrupts and the thread API stay as they are.
- No change to the `/import` route or the `import-` thread ids.
- Ask's `ChatPane` is not refactored into a generic component now. Scout reuses its classes and markup, not its component, to keep Ask's risk at zero.
- No new tests (repo rule); fix any that break.

## Verification

- `cd backend && pytest -m "not integration"`, which should be unaffected.
- `cd frontend && npm run lint && npx tsc --noEmit`, then `next build` in a throwaway worktree (the dev container shares `.next`).
- At localhost:3000/import, signed in:
  1. Empty chat: three cards above the composer. Click "Research a funder": the composer reads "Funding profile for ", and the rail shows sources with none ticked and Send disabled. Type "Tata Trusts", tick Public websites, send.
  2. The same thread shows: your message → the working board streaming → notes → review card inline → done card. No sources card appears mid-run.
  3. Type a follow-up in the composer: it runs in the same thread.
  4. As a member of an org with private files, the rail lists its Doc Vault files; tick one, and the trace reads only that file.
  5. Reload a finished thread from the left list: everything renders from history.
  6. At phone width: no rail, and the sources sit above the composer.
