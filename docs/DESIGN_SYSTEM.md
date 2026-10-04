# Design system: the Claude Design project leads, the repo follows

Sangam's design system lives in a Claude Design project, **"Sangam Design System"**:
https://claude.ai/design/p/aeaa7276-b5e7-41e1-b980-c5d8672c96ab

It is the **system of record for design**: colours, type, corners, spacing, component looks and
the written rules (voice, layout, iconography). A design change is made there first and then
synced into the repo. The repo never invents a token, size or colour the design system does not
have.

The project began as a snapshot of this repo's code, and Phase 1 (PR #86) changed the repo first.
So, once, the design system has to catch up with the repo; the list is in
[`features-plans/prototype-v1/2026-10-03-ask-entry-flow-design.md`](../features-plans/prototype-v1/2026-10-03-ask-entry-flow-design.md),
"After the PR merges". From then on, changes flow one way: design system → repo.

## What maps to what

**Tokens map one to one.** Both sides are CSS variables with the same names, so a token sync is
a mechanical copy of values.

| Design system | Repo |
|---|---|
| `tokens/colors.css` | `:root` colour ramps, semantic aliases and the shadcn variables in `frontend/app/globals.css` |
| `tokens/typography.css` | `--fs-*`, `--font-*` in `globals.css`; the font itself is loaded by `next/font` in `frontend/app/layout.tsx` |
| `tokens/spacing.css` | `--radius-*`, `--shadow-*`, `--page-max`, `--page-pad`, `--nav-h` in `globals.css` |
| `tokens/base.css` | The hand-written classes in `globals.css`: `.btn`, `.card`, `.tag`, `.pill`, `.seg`, `.input`, `.dialog`, `.eyebrow`, `.page`, `.measure`, `.reading` |
| `guidelines/*.html` | Nothing; they are the specimen pages to check the repo against |

The `@theme inline` block at the end of `globals.css` re-exposes the tokens as Tailwind utilities
(`bg-terracotta-750`, `text-sand-700`, …). It is derived, so it changes only when a token is added
or removed.

**Components are translated, not copied.** The design system's components are JSX reference
implementations. The repo's are TypeScript, built on Radix and Tailwind. A component sync means
making the repo's version look and behave like the reference.

| Design system | Repo |
|---|---|
| `components/core/Button` | `frontend/components/ui/button.tsx` and the `.btn` classes |
| `components/core/{Tag, StatusChip, EntityMark, ProgressBar, Breadcrumbs, StatRail}` | `frontend/components/ui/primitives.tsx` |
| `components/forms/{Input, Checkbox}` | `frontend/components/ui/{input,checkbox}.tsx` and `.input` |
| `components/forms/{SegmentedControl, Pill, PillTabs}` | `.seg`, `.pill`, `frontend/components/ui/PillTabs.tsx` |
| `components/surfaces/{Card, CardBody, Hero, Dialog}` | `frontend/components/ui/{card,Hero,dialog}.tsx` and `.card`, `.dialog` |
| `components/layout/{Nav, Footer}` | `frontend/components/layout/{Nav,NavBar,Footer}.tsx` |
| `components/agent/{QuestionRow, AnswerCard, TraceCard, CitationChip}` | `frontend/features/ask/components/` |
| `components/agent/RunStatus` | `frontend/features/ingest/components/RunStatus.tsx` |
| `components/agent/ScoreCard` | `frontend/features/registry/ScoreCard.tsx` |

Not in the design system yet: they arrive with the catch-up.

| Repo | What it is |
|---|---|
| `frontend/components/ui/avatar.tsx`, `dropdown-menu.tsx` | The signed-in user menu |
| `frontend/components/ui/SectionIndex.tsx` | The "sections" index on Resources and Terms |
| `frontend/features/ask/components/ComposerNotice.tsx` | The AI notice under the Ask composer |

## How to sync

There is no automatic sync. Ask an agent to "sync the design system", or do it by hand:

1. **Read the project.** In Claude Code, the `DesignSync` tool reads a Claude Design project
   (`list_files`, `get_file`); run `/design-login` once to authorise it.
2. **Diff tokens.** Compare `tokens/*.css` with `:root` in `globals.css`. Copy changed values;
   add new tokens, and their `@theme inline` entries if Tailwind should see them.
3. **Diff components.** For each changed component, compare its `.jsx` and `.prompt.md` with the
   repo file in the table above and update the repo's version to match.
4. **Check.** `npm run lint` and `npm run build` in `frontend/`, then `make smoke`. Compare the
   pages against the design system's `guidelines/` cards and `ui_kits/sangam-web/`.
5. **Raise one PR** that names the design-system change it follows.

Writing to the design system is a separate, deliberate step. Use `/design-sync`, and only with
the project owner's agreement.

## The rules in force

The design system's `readme.md` is the full statement. As of PR #86, the rules most often needed
when building:

- **Corners:** pill (`--radius-pill`) for every button, chip, filter, toggle and single-line
  input; 14px (`--radius-surface`) for cards, dialogs, menus, heroes and multi-line inputs; 8px
  (`--radius-row`) for rows inside a surface.
- **Type:** only 12 · 14 · 16 · 20 · 24 · 36 (`--fs-xs` … `--fs-2xl`). Page titles are 36,
  section headings 20, card titles 16, card body 14, labels 12. Reading pages use 16px body
  (`.reading`).
- **Colour:** text must clear WCAG AA (4.5:1). Terracotta text is `--color-accent-750`; an orange
  fill carries white text and is `accent-750`. Muted text is sand-700. Lighter tints are fills
  only.
- **Layout:** one `--page-max` (1160px) column on every page; long text caps itself with
  `.measure` (72ch) rather than narrowing the page.
- **Reduce before you diverge:** reuse an existing token, size or component before asking the
  design system for a new one.
