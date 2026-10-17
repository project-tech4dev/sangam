# Design system: one Claude Design project, kept in step with the repo

Sangam's design system lives in a Claude Design project, **"Sangam Design System v2"**:
https://claude.ai/design/p/3b0e9aeb-8b17-4fa0-9194-2882f6b39edd

It holds the colours, type, corners, spacing, component looks and the written rules (voice,
layout, iconography), plus a click-through UI kit of the main screens. Two things are true of
it at once:

- **It is where design is decided.** A new token, size, colour or component look is agreed
  there first, then built here. The repo never invents a token, size or colour the design
  system lacks.
- **It never drifts from the repo.** Any pull request that changes a component in
  `frontend/components/` or a screen the UI kit recreates also updates the design system, in
  the same PR. "How to sync" below is the procedure.

v2 was built on 8 Oct 2026 from the repo as it stood after PR #97. The first project, "Sangam
Design System" (`aeaa7276…`, owned by Sid), predates Phase 1; v2 replaces it.

## What maps to what

**Tokens map one to one.** Both sides are CSS variables with the same names, so a token change
is a copy of values.

| Design system | Repo |
|---|---|
| `tokens/colors.css` | `:root` colour ramps, semantic aliases and the shadcn variables in `frontend/app/globals.css` |
| `tokens/typography.css` | `--fs-*`, `--font-*` in `globals.css`; the font itself is loaded by `next/font` in `frontend/app/layout.tsx` |
| `tokens/spacing.css` | `--radius`, `--radius-pill/surface/row`, `--shadow-*`, `--page-max`, `--page-pad`, `--nav-h` in `globals.css` |
| `tokens/base.css` | The hand-written classes in `globals.css`: `.btn`, `.card`, `.tag`, `.pill`, `.seg`, `.input`, `.dialog`, `.eyebrow`, `.page`, `.measure`, `.reading`, `.nav-link` |
| `tokens/scout.css` | Sangam Scout's classes in `globals.css`, from "Import workspace" through "Import: the Review step", imported by `styles.css` after `base.css` |
| `tokens/registry.css` | The Registry list's `.reg-*`, the CSO and funder profiles' `.profile-*` (hero, board tabs, SDG tiles, cards, tables) and the research brief's `.brief-*` classes in `globals.css`, plus the list-page classes (`.bucket-card`, `.filter-row`, `.filter`, `.search-box`, `.list-*`), `.pill-tabs` and `.btn-ondark`; imported by `styles.css` after `scout.css` |
| `tokens/registry-row.css` | The Registry row's population chips (`.reg-tag[data-tone="population"]`), `.reg-row-line`, `.reg-row-label`, `.reg-more` and the filtered tag's edge (`.reg-tag[data-active]`) in `globals.css`; imported by `styles.css` after `registry.css` |
| `tokens/site.css` | The Nav's `.nav-links` and phone menu (`.nav-menu-button`, `.nav-menu`, `.nav-menu-link`) and Home's `.home-step*` classes in `globals.css`; imported by `styles.css` after `registry.css` |
| `guidelines/*.html` | Nothing; they are the specimen pages to check the repo against |

The design system also carries tokens the repo does not use yet (`--surface-*`, `--text-*`,
`--space-*`, `--lh-*`, `--tracking-*`, `--sidebar-w`, `--chat-max`, motion). The `@theme inline`
block at the end of `globals.css` re-exposes the repo's tokens as Tailwind utilities
(`bg-terracotta-750`, `text-sand-700`, …); it changes only when a token is added or removed.

**Components are translated, not copied.** The design system's components are plain-JSX
reference implementations (inline styles over the tokens). The repo's are TypeScript on Radix
and Tailwind. A component change means making both look and behave the same.

| Design system | Repo |
|---|---|
| `components/core/Button` | `frontend/components/ui/button.tsx` and the `.btn` classes |
| `components/core/{Tag, StatusChip, EntityMark, ProgressBar, Breadcrumbs, StatRail}` | `frontend/components/ui/primitives.tsx` |
| `components/core/Avatar` | `frontend/components/ui/avatar.tsx` |
| `components/forms/{Input, Checkbox}` | `frontend/components/ui/{input,checkbox}.tsx` and `.input` |
| `components/forms/{SegmentedControl, Pill, PillTabs}` | `.seg`, `.pill`, `frontend/components/ui/PillTabs.tsx` |
| `components/surfaces/{Card, CardBody, Hero, Dialog}` | `frontend/components/ui/{card,Hero,dialog}.tsx` and `.card`, `.dialog`; `HeroFacets` = `features/registry/profile/ProfileHero.tsx` |
| `components/surfaces/DropdownMenu` | `frontend/components/ui/dropdown-menu.tsx` |
| `components/layout/{Nav, Footer}` | `frontend/components/layout/{Nav,NavBar,Footer}.tsx` |
| `components/layout/UserMenu` | `frontend/features/auth/sign-in-button.tsx` (`UserMenu`) |
| `components/layout/SectionIndex` | `frontend/components/ui/SectionIndex.tsx` |
| `components/agent/{QuestionRow, AnswerCard, TraceCard, CitationChip, ComposerNotice}` | `frontend/features/ask/components/` |

**The UI kit recreates screens.** `ui_kits/sangam-web/` is a click-through of the app built
from the components above, with sample data.

| UI kit file | Repo |
|---|---|
| `Home.jsx` | `features/home/HomePage.tsx`, `HeroSlides.tsx` |
| `Registry.jsx` | `features/registry/RegistryClient.tsx` |
| `Profile.jsx` | `app/registry/[slug]/page.tsx`, `app/registry/funders/[slug]/page.tsx`, `features/registry/profile/*` (CSO and funder) |
| `AskWorkspace.jsx` | `features/ask/preview/AskPreview.tsx`, `features/ask/components/*`, `features/ask/views/*` |
| `Import.jsx`, `importData.js`, `import.html` | Sangam Scout at `/import`: `features/ingest/ImportPage.tsx`, `ScoutChat.tsx`, `components/*` (thread, run strip, rail and step bar use the `.scout-*` and `.import-*` classes; the Review and Done cards are still recreated inline) |
| `index.html`, `import.html` | the routing and navbar behaviour in `app/` and `components/layout/` |

## How to sync

There is no automatic sync, and `/design-sync`'s converter does **not** fit this repo: it
rebuilds a design system from a compiled component package, and Sangam has none (most of its
look is the classes in `globals.css`). Do it by hand, with an agent if you like — "sync the
design system for this PR" is enough of a prompt, given this file and `.design-sync/NOTES.md`.

**Repo → design system** (the same PR as the code change):

1. **Find what changed.** `git diff master --stat -- frontend/app/globals.css frontend/components frontend/features`,
   then use the tables above to name the design-system files it touches.
2. **Read those files from the project.** The `DesignSync` tool's `get_file` (run `/design-login`
   once). Save them under a scratch folder, keeping their paths.
3. **Edit them to match.** Tokens: copy values. Components: change the `.jsx`, and its `.d.ts`
   and `.prompt.md` when the props or the guidance change. Screens: the matching UI-kit file.
   Use tokens (`var(--fs-sm)`, `var(--radius-surface)`, `var(--color-accent-750)`), never
   literal sizes, radii or colours. A new component needs all three files plus a place in a
   group card (`components/<group>/<group>.card.html`) and a line in `readme.md`.
4. **Upload.** `DesignSync` `finalize_plan` (one approval), then `write_files`: first
   `_ds_needs_recompile` (`{"by":"design-sync-cli"}`), then the changed files, then
   `_ds_needs_recompile` again, each as its own call (one batch can't hold the same path
   twice). Don't write `_ds_bundle.js`, `_ds_manifest.json` or
   `_adherence.oxlintrc.json`; Claude Design rebuilds them the next time the project is opened.
5. **Check.** Open the project, look at the cards you touched and at
   `ui_kits/sangam-web/index.html`, and say in the PR which design-system files changed.

**Design system → repo** (a design decision made there first):

1. Read the changed tokens or components from the project, as above.
2. Copy token values into `:root` in `globals.css`; add `@theme inline` entries if Tailwind
   should see a new one.
3. Make the repo's components look like the reference.
4. `npm run lint` and `npm run build` in `frontend/`, then `make smoke`.

Writing to a design-system project needs its owner's agreement.

## The rules in force

The design system's `readme.md` is the full statement. The ones most often needed when building:

- **Corners:** pill (`--radius-pill`) for every button, chip, filter, toggle and single-line
  input; 14px (`--radius-surface`) for cards, dialogs, menus, heroes and multi-line inputs; 8px
  (`--radius-row`) for rows inside a surface.
- **Type:** only 12 · 14 · 16 · 20 · 24 · 36 (`--fs-xs` … `--fs-2xl`). Page titles are 36,
  section headings 20, card titles 16, card body 14, labels 12. Reading pages use 16px body
  (`.reading`).
- **Colour:** text must clear WCAG AA (4.5:1). Terracotta text is `--color-accent-750`; an orange
  fill carries white text and is `accent-750`. Muted text is sand-700. Lighter tints are fills
  only.
- **Icons:** Lucide (`lucide-react`), sized, stroked and coloured by the `.icon` classes, never by
  props. Text-like marks (⟨ ⟩ ✓ → ⌘↵) stay glyphs.
- **Layout:** one `--page-max` (1160px) column on every page; long text caps itself with
  `.measure` (72ch) rather than narrowing the page.
- **Wording:** "CSO" in data and registry UI, "NGO" in marketing copy, "vetted" (never
  "hand-vetted"), no "North East India" framing in product copy.
- **Reduce before you diverge:** reuse an existing token, size or component before asking the
  design system for a new one.
