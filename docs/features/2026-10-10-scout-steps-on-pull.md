# Scout: steps only once data is pulled; a quiet new chat

## Context

Two problems the user hit on the Scout page:

1. **The step strip appears too early and says Done too easily.** After any reply, even "which NGOs do you mean?", the strip shows Start ✓ Working ✓ … **Done**. The rule says `!isRunning && !paused → Done`, so a conversation with nothing pulled counts as done. The user wants Start · Working · Review · Done to appear **only once the agent starts pulling data**, and Done only after something was actually pulled and saved.
2. **The new chat page shows too much.** Under the composer it has the full Researched recently list (dozens of rows), SourceGroups, and a Details disclosure. By default it should show **5 researched items**, then a "Show all (N)" link. The staff tools go behind **one closed "Team tools" link** (the user's choices).

Frontend only, on top of the uncommitted Scout layout work on `feat/staff-vault-pick`.

## 1. The step strip appears when pulling starts

**"Pulling" means a research run exists in the thread.** That is the `runs` map in `ScoutChat.tsx`: turns whose `boardOf(...).rows.length > 0`. Add the steps that pull data without board rows:
- a `task` to `workbook-reader` / `vault-reader`;
- `run_import_now` (the news import).

Name the result `pulling`. `lib/board.ts` already tells these apart; reuse its `HELPERS` / subagent_type check.

- **No pulling yet** (Scout is only talking or asking): no strip at all. The thread is plain chat, as in Ask.
- **Pulling started:** the strip appears with this rule:
  ```
  isRunning        → reviewed-in-this-run ? Review : Working
  reviewing        → Review               (review card open)
  toReview > 0     → Review
  saved > 0        → Done                 (something was pulled and kept)
  otherwise        → Review               (finished but nothing saved yet)
  ```
  Start is ✓ by definition once the strip shows.
- **`saved`:** `DoneReport` already counts `saved = all.filter(isSaved)`. Extend `onPending` into `onCounts({ pending, saved })` so ScoutChat gets both.
- **`reviewed` resets on each new message** in `submit()`, so a second research run starts at Working again, not Review.
- **The new chat page loses its big step bar** (it showed Start before anything was pulled). The strip's `status` "Done"/"Waiting for you" no-run branches go away with it.

## 2. A quiet new chat page

- **`components/ResearchedRecently.tsx`:** a `limit` prop (default 5) shows the 5 most recent. Below them sits a "Show all (N)" link that expands the list in place, and "Show fewer" collapses it again.
- **`ImportView.tsx`:** for staff, `SourceGroups` and the Details content (SourcePanel, RunHistory, ProposalList) move into one closed `<details>` with the summary "Team tools". Nothing in it renders until opened. Non-staff never see it.

## Files

- `features/ingest/ScoutChat.tsx`: `pulling`, the step rule, no strip and no big bar before pulling, and `reviewed` reset.
- `components/DoneReport.tsx`: `onCounts`.
- `components/ResearchedRecently.tsx`: limit plus Show all.
- `ImportView.tsx`: the Team tools disclosure.
- `app/globals.css`: only if the Show all link needs a class; reuse `.import-link`.

## Not doing

- No backend change.
- No new tests (repo rule).

## Verification

- tsc, eslint, and `next build` in a throwaway worktree.
- **New chat:** title, task cards, composer, 5 researched rows with "Show all (N)", and for staff a closed "Team tools" link. No step bar.
- **Thread where Scout only asked "which NGOs?"** (the first in the list, before the FRRH follow-up): no strip after that reply.
- **FRRH thread:** the strip shows Review with "Review 2 →".
- **A thread whose research was all saved:** Done.
- **Live:** send "Funding profile for Tata Trusts" with Public websites ticked. No strip until the researcher starts, then Working → Review → Done after saving.
