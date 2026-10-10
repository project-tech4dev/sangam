# Scout: bring back Start · Working · Review · Done

## Context

The Sangam Scout redesign (commit c5eeea4) deleted `StepBar.tsx` and its `.import-step*` styles: the earlier plan said "There is no step bar." Since then each turn has been a chat turn, and the latest change pinned the run panel on top. The user wants the four steps back, so a person always sees where the run is: Start → Working → Review → Done.

The work is uncommitted on `feat/staff-vault-pick` (the pinned run panel and the unbroken thread). This change goes on top of it, frontend only.

## Change

**Restore `frontend/features/ingest/components/StepBar.tsx`** exactly as it was in `c5eeea4^`: `STEPS = ["Start","Working","Review","Done"]` with `current: number`.

**Restore the `.import-step*` rules in `globals.css`** from `c5eeea4^` (lines 630–653). They are already in the design system, so no new tokens are needed. Swap the two `color: #fff` for `var(--color-bg)`, as `.scout-reply-mark` does.

**Place it at the top of the chat column, in both layouts** (`ScoutChat.tsx`):
- **Empty chat:** above "What should Scout find out?", on Start.
- **Started:** the first child of `.chat-pane`, above the pinned run panel, so the steps and the run sit together on top and the thread flows below.

**Drive it like the old `ImportWorkspace` did, with the same rule:**
```
current = atStart ? 0
        : reviewing || (finished && toReview > 0) ? 2
        : reviewed || (!isRunning && !paused) ? 3
        : 1
```
- Put back the `reviewing` / `reviewed` state and the `onReview` callback that sets `paused`, `reviewing` and `reviewed`, which I removed in the last change. `SaveQuestions` gets `onPaused={onReview}` again.
- `toReview`: pass `onPending={setToReview}` to the `DoneReport` in the run panel. `DoneReport` already reports how many organisations still wait for review.
- `finished = !isRunning && !paused && slugsOf(lastSteps).length > 0`.
- A thread with no research turn, such as one where Scout only asked "which NGOs?", stays on Working while running and shows Done after. That is the old behaviour.

**Styling:** a `.scout-steps` wrapper using the same 860px max-width and centring as the other centre-column pieces, so the steps line up with the panel and the composer.

## Not doing

- No backend change, and no change to the pinned panel or the reply bubbles.
- No new tests (repo rule).

## Verification

- `npx tsc --noEmit`, eslint, and `next build` in a throwaway worktree.
- In the browser:
  - **New chat:** the bar shows Start as current.
  - **Old FRRH thread** (2 organisations still to review): Start ✓ · Working ✓ · **Review**.
  - **Thread where everything is saved:** Done.
- Live check: send a funder request, and the bar moves Start → Working → Review (when the review card opens) → Done after saving.
- Update the design system's UI kit Import page in the same PR (needs V's access; otherwise flag it in the PR).
