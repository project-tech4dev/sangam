# Scout: give the conversation room

## Context

The user says everything looks cramped. Measured on their FRRH thread at 1483×812:

| Piece | Height / width | Problem |
|---|---|---|
| Step bar | ~50px | Says "Review", and the panel header under it says "Researched 8 organisations": two bars for one fact |
| Pinned run panel | ~320px (45% cap) | Always open, with a big "Review what Scout found" h1 inside, pushing the thread down |
| **Thread** | **~190px** | The conversation, the thing the page is for, gets the least space: about 4 lines |
| Composer | ~140px | A 72px textarea plus a hint row, even for a one-line follow-up |
| Right rail | 340px, 30+ rows | Staff admin lists (Sources to classify: theant.org, karrtax.in …; run history) next to a chat, plus a stale "No import has run yet" |

The fix makes the top one slim strip, opens the detail only when it's needed, trims the composer, and moves the admin lists off the chat.

## Changes (one PR, frontend only)

**1. One strip on top, not two bars plus a panel** (`ScoutChat.tsx`, `ScoutRunPanel.tsx`, `StepBar.tsx`)
- Merge the step bar into the panel header: one row of about 52px. Small steps on the left (Start ✓ Working ✓ **Review** Done), and on the right a short status plus one action:
  - Working: "3 of 8 ready" plus the mini segments.
  - Review: **"Review 2 →"**.
  - Done: "Saved 6".
- Add a `compact` StepBar variant: 20px dots and xs labels. The empty chat keeps the full-size bar above "What should Scout find out?".

**2. The detail opens only when it matters**
- Open by default only while **Working**, so you see the board move, with the cap lowered from 45% to 35%.
- Collapsed to the strip by default on Review and Done. "Review 2 →" opens it.
- Opening it slides the panel down over the thread (an overlay inside the chat column, with its own scroll and a close ✕), instead of pushing the thread off-screen.
- Inside the panel, drop DoneReport's big `h1` in favour of a one-line sub (the strip already carries the title). This is the same `compact` idea WorkingBoard got.

**3. A slimmer composer once the chat has started**
- Started chat: the textarea starts at one line (about 44px) and grows with the text up to 6 lines. The hint row goes, ⌘↵ stays as the placeholder hint, and the buttons sit inline on the right.
- The empty chat keeps the big composer.

**4. A right rail that belongs to the chat**
- After the first message, the rail keeps only **Reading from** and **Waiting for you** (the names that need a person).
- **Sources to classify**, **Run history** and **Proposals** move to the empty chat's "Details: every source Scout can read" disclosure, which already holds SourcePanel and SourceGroups. They are team admin, not part of a conversation.
- Drop the stale "No import has run yet" line from the rail.

**5. Breathing room in the thread**
- The gap between turns goes from 22px to 32px, and the "Researched 8 organisations" marker sits on its own line under the reply.
- A thin divider before each "You" makes turns readable at a glance.

## Expected result at 1483×812

The thread goes from about 190px to about 560px:
- 812 − 64 navbar − 52 strip − about 90 composer − padding.

While the board is open during Working, the thread still keeps about 280px.

## Not doing

- No backend change, and no change to the review/save flow, the interrupts or the thread list.
- No new tests (repo rule).

## Files

- `frontend/features/ingest/ScoutChat.tsx`
- `components/ScoutRunPanel.tsx`
- `components/StepBar.tsx`
- `components/DoneReport.tsx` (gets `compact`)
- `components/ScoutRail.tsx`
- `ImportView.tsx` (the admin panels move to `below`)
- `app/globals.css`: `.scout-run*` gets overlay positioning, plus `.import-steps[data-size="sm"]`, a started-composer variant and the turn spacing, all from existing tokens.

The design system's UI kit Import page gets updated in the same PR (needs V's access, otherwise flag it).

## Verification

- `npx tsc --noEmit`, eslint, and `next build` in a throwaway worktree.
- On the FRRH thread at 1483×812:
  - one strip reading "✓ ✓ **Review** · Review 2 →";
  - the thread shows about 12+ lines;
  - "Review 2 →" opens the panel over the thread, and ✕ closes it.
- On a new chat: the big step bar, the task cards and the big composer, unchanged. The Details disclosure now also holds Sources to classify, Run history and Proposals.
- Live run: the panel is open during Working, and collapses to "Review 2 →" when the review card appears.
- Phone width: no rail, and the strip wraps cleanly.
