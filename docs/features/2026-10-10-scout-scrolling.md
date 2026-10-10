# Scout: smooth, single-layer scrolling on the Import thread page

## Context

The user asked for a review of scrolling on the Import thread page. Measured in the browser on `import-22c7db6e…` at 1483×828:

| What | Measured | Effect |
|---|---|---|
| The page itself scrolls | document 984px tall in an 828px window: the site footer (with its `mt-16`) sits under the 100dvh workspace | Scroll the thread to its end and the next wheel moves the **whole page** up 156px. The run strip slides under the navbar, the footer appears, and the composer moves. Wheeling in the chat list does the same. |
| Scroll chaining | Every inner scroller (thread, chat list, right rail, run drop-down) has `overscroll-behavior: auto` | Each one hands its leftover scroll to the page, which is the jump above. |
| Thread width jumps | `.chat-scroll` has no `scrollbar-gutter` | As a reply streams in and the scrollbar appears, the text reflows sideways. |
| Follow-to-bottom | Instant `scrollTop` jump on every update (fixed last turn: it only follows while you're at the bottom) | Fine while streaming. Sending a message jumps rather than glides. |

Ask Sangam has the same 156px page overflow (also 984 in 828), from the same footer.

## Changes (frontend, CSS mostly)

1. **No page scroll behind a full-height workspace.** In `globals.css`: `body:has(.import-shell) > footer { display: none; }`. The workspace already fills `100dvh − nav`, so the document becomes exactly one screen tall. The footer stays on every other page.
2. **Each scroller keeps its own scroll.** Add `overscroll-behavior: contain` to:
   - `.scout-thread`
   - `.import-threads` (the chat list)
   - `.scout-rail`
   - `.scout-run-body`
   - `.scout-run-full-body`
   - `.chat-pane.is-empty.scout-empty`
3. **Steady text width.** `scrollbar-gutter: stable` on `.scout-thread` and `.scout-rail`.
4. **Smooth where a person caused it.** In `ScoutChat.tsx`, sending a message scrolls to the bottom with `behavior: "smooth"`. Streaming updates keep the instant follow, because a smooth scroll fired every 80ms stutters. "Show above" on an older run marker already opens the panel and needs no scroll.

## Not doing

- Ask Sangam's identical footer overflow: one more selector (`body:has(.ask-sidebar) > footer`) would fix it. It's outside this page, so I'll ask before touching Ask.
- No backend change, and no new tests.

## Verification

Run in the browser with JS measurements, on `import-22c7db6e…`, a new chat, and the Show all list:
- `document.documentElement.scrollHeight === innerHeight`, and `scrollY` stays 0 after wheeling 15 ticks past the end of the thread, the chat list, the right rail, and the open run drop-down.
- The full-size run view scrolls inside itself, and the page behind it doesn't move.
- tsc, eslint, and `next build` in a throwaway worktree.
