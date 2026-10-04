# Phase 1: Ask entry flow

Status: built locally on `feat/phase-1-ask-entry`, for review as one PR. It is the first of
three UI phases that align the app with `prototype-v1` and the Sangam Design System (Claude
Design project "Sangam Design System"). Phase 2 (Registry), Phase 3 (workspace shell) and the
auth-enforcement step B1 are scoped but deferred. They are listed at the end only so the
boundaries are clear.

## What this phase delivers

A visitor who is not signed in can open **Ask Sangam**, see what it does, and start asking. The
first real interaction asks them to sign in, and they come back to the same place with their
question waiting. The navbar and footer are on every page, and Ask Sangam has exactly one entry
point in them. Corners follow one rule everywhere.

| Part | Title |
|---|---|
| A1 | Design-system foundation |
| A2 | Global chrome |
| A3 | Login round-trip |
| A8 | Public Ask preview |

## Which source wins

There are three sources, and they disagree in places:
- **the code** on master;
- **`prototype-v1`**;
- **the design system**, which was lifted from the code, so it records the as-built look.

Where they disagree, this is the ruling:

| Topic | Winner | Ruling |
|---|---|---|
| Visual language: colours, weights, components | **Design system** | Headings stay at weight 600. Page titles are 36px. Dialog, button and composer follow the design system's components, not stock shadcn. No icon library. |
| Type sizes | **The six-step scale only** | The one-off sizes are retired for now, so the system starts small before it diverges. |
| Corners | **Role-based rule** (below) | It overrides both the prototype's "no pills" and the design system's three overlapping corner scales. |
| Ask page behaviour | **These decisions** | The design system says "full-screen, sign-in required, nav hidden". The design system is updated to match. |
| Navbar | **These decisions** | A single Ask link, no Import, and an avatar menu. The design system gets a revised `Nav` and a new user menu. |
| Wording | **Prototype** | "NGO" everywhere, overriding the design system's "CSO in registry UI". This applies in Phase 2. |
| Registry content | **Prototype** | Financials, Impact, map, "What they look for", giving charts. This applies in Phase 2. |

### The corner rule

There are two shapes, plus a small radius for rows inside a surface. The tokens are in
`app/globals.css`.

| Token | Value | Used by |
|---|---|---|
| `--radius-pill` | 999px | every button (icon buttons become circles), tags, chips, filters, segmented toggles, citation chips, single-line inputs |
| `--radius-surface` | 14px (`--radius + 4px`, shadcn's `rounded-xl`) | cards, dialogs, dropdown menus, profile heroes, the trace panel, the multi-line composer |
| `--radius-row` | 8px (`--radius - 2px`) | rows inside a surface: Ask sidebar items, menu items |

- The old `--radius-sm/md/lg` (8/12/18px) are gone. Nothing references them.
- `.btn-square` is gone. Its only user was the navbar's Sign in.
- shadcn's `button.tsx` and `input.tsx` use `rounded-full`.
- `features/ingest/*` keeps its inline 8/10px corners, because PR #82 rewrites those files.

## A1: Design-system foundation

- **`@source`:** add `../features/ask`. Registry and ingest join in their own phases.
- **The corner rule** above.
- **`--nav-h: 64px`:** the navbar's height. The Ask workspace fills the viewport below it.
- **New primitives in `components/ui/`.** These are thin Radix wrappers (the `radix-ui` package is
  already a dependency), styled to the design system:
  - `dialog.tsx`: the design system's Dialog look. Sand surface, 14px corners, 28px padding,
    420px wide, 18px semibold title.
  - `dropdown-menu.tsx`: the menu is a surface, and its items are rows.
  - `avatar.tsx`: an initials disc.

  No `textarea` or `collapsible` component is added. The composer is the design system's
  multi-line `Input`, the existing `.input`, and the preview's expander is a `<details>`.
- **Layering caveat:** the hand-written classes (`.card`, `.input`, `.btn`, …) are not in a CSS
  layer, so they override Tailwind utilities. Where a screen needs to adjust one of them, it uses
  an inline style, as ChatPane already does.

## A2: Global chrome

- **Navbar and footer on every route**, `/ask` included. `NavBar` and `Footer` no longer return
  `null` there.
- **The navbar holds:** wordmark · Registry · Ask Sangam · Resources · Sign in or avatar.
  - The duplicate "Ask Sangam" button is gone.
  - Import is gone from the navbar. It now lives **inside the Ask workspace**: the sidebar ends
    with a collapsible **Tools ⟩** section whose **Import** item opens the import agent and its
    panels beside the sidebar (`features/ask/views/ImportView.tsx`, panels fetched when the view
    opens). Its URL is `/ask?view=import`, and `/import` redirects there. This does not make it
    staff-only; that arrives with B1.
- **`Nav` is on Tailwind utilities and tokens.** The sage glass is unchanged; the wordmark is
  24px/700 and the links 13.5px/600.
- **On a phone** the navbar keeps its fixed height. The links scroll sideways, and the user's name
  hides below `sm` (only the avatar shows). Proper mobile design is still open in the prototype.
- **User menu:** `Avatar` + `DropdownMenu`, showing the user's name, email and "Log out". Logging
  out calls `router.refresh()`, so `/ask` falls back to the preview.
- **The Ask workspace** is `calc(100dvh - var(--nav-h))` tall, and the chat scrolls inside it.
- **Its sidebar drops the chrome the navbar now carries:** the wordmark, the Registry and Resources
  links, and the hard-coded "DV · Signed in — dev workspace" footer. A "Workspace" eyebrow and
  the collapse control head it instead.

## A3: Login round-trip

```
proxy ──► /auth/login?next=/import ──► Google ──► /auth/callback?code=…&next=/import
                                                        │ safeNextPath(next, '/', origin)
                                                        ▼
                                                     /import
```

- **Middleware.**
  - `PROTECTED_PREFIXES` is now just `['/import']`.
  - Matching is exact or `prefix/`, so `/imports` doesn't match.
  - A turned-away request carries `next=<path+query>`.
- **`/auth/login`** reads `searchParams.next` and passes it to `LoginForm`.
- **`LoginForm`** is now a controlled dialog (`open`, `onOpenChange`). It also takes:
  - `next`, which goes on the callback URL;
  - `onBeforeRedirect`, which runs just before the browser leaves for Google.

  Without Supabase keys it says sign-in is unavailable here, instead of offering a button that
  throws.
- **The callback** validates with `safeNextPath(next, '/', origin)`. `//evil.com`,
  `https://evil.com` and `/\evil.com` all fall back to `/`.
- **The navbar's Sign in** always uses `next=/ask`.
- **`/protected`**, the leftover Supabase template page, is deleted.
- **Without Supabase keys** the proxy gates nothing, rather than throwing on every request. A
  bare local run therefore renders public pages and the `/ask` preview, and nobody can sign in.
- **Supabase's Redirect URLs allowlist** must accept the callback with a query string, e.g.
  `http://localhost:3000/**` and the deployed domain. Otherwise Supabase drops `redirectTo` and
  sends the user to the Site URL.

## A8: Public Ask preview

### Routing

- `/ask` checks the Supabase claims on the server.
  - **Signed out:** it renders `<AskPreview/>`. A missing Supabase configuration also counts as
    signed out.
  - **`?q=`** carries a question in from elsewhere. Signed out it prefills the preview's
    composer; signed in, the workspace's. The Registry profiles' "Ask Sangam about …" buttons
    use it.
  - **Signed in:** it fetches the index payload and renders the workspace.
- **The CopilotKit runtime must not load for the preview.** Two changes do this:
  - The `(agent)` group layout no longer wraps everything in a provider. The provider moved out
    of `app/`, which holds routes only, to `lib/AgentProviders.tsx`. Import gets it through the
    workspace (`/import` now only redirects to `/ask?view=import`).
  - The workspace sits behind a client-side `next/dynamic` boundary
    (`features/ask/WorkspaceLoader.tsx` → `SignedInWorkspace.tsx`).

  A static import, or a server-side `await import()`, still put five CopilotKit chunks into the
  preview's page. Behind the boundary there are none.

### What the preview shows (`features/ask/preview/`)

- **Hero:** the "Ask Sangam" eyebrow, a 36px title, and one line on what it answers and how it
  cites.
- **Composer:** the workspace's composer, with "Sign in to ask · ⌘↵" as its hint.
- **Example questions:** four `pill` chips.
- **One sample answer** (`sample.ts`). It is static, so it costs no model call, but it is not
  invented. It is *not* a recording of a live agent run: the prose is written for the preview
  and the trace is representative. Every figure comes from the base's real rows for KABIL × Axis Bank Foundation
  (rubric v1: `fit_scores`, `fit_score_items`, `score_adjustments`). Specifically:
  - 93/100;
  - eligibility 16/20, for the CSR-1 gap;
  - relationship 7/10, after a vetting adjustment;
  - the 24,765-family figure;
  - the ₹91 cr → ₹427 cr CSR trend.

  The trace lists the tools the agent uses for this question. The sample renders through the
  real `TraceCard` and `AnswerCard`, so it can't drift from the workspace. Citation ids are local
  to the fixture and resolve to slugs, so the chips link correctly whichever database the
  preview runs against. Below the answer are:
  - "Why this match — 7 criteria", in a `<details>`;
  - follow-up chips.
- **"Signing in also opens":** Doc vault, Media & signals, RFP watch.

### The hand-off

| Visitor action | Result |
|---|---|
| Presses Ask Sangam or ⌘↵ with text | The sign-in dialog opens on the same page |
| Clicks an example or a follow-up | Its text goes into the composer, then the dialog opens |
| Clicks a citation chip | Goes to the Registry (public, no sign-in) |
| Cancels the dialog | The dialog closes and the question stays in the composer |

- **Saving the question.** `onBeforeRedirect` saves it to `sessionStorage['sangam:pendingQuestion']`.
  Opening the dialog alone does not, so a cancelled sign-in leaves nothing behind.
- **Restoring it.** On mount, the workspace takes the key: it reads it once and deletes it. It
  then opens a fresh chat with the question **prefilled, not sent**.
- **Storage failures.** Storage errors are swallowed. Sign-in still works, and only the question
  is lost.

## Added during review

- **Resources is one page with tabs**, each its own URL: `/resources/methodology` and
  `/resources/taxonomy`. `/resources`, `/methodology` and `/taxonomy?domain=…` redirect there; the
  old domain tabs become `#livelihoods`, `#education`, `#health` and `#shared-vocabulary`.
- **Each tab has an "In this article" index** (`components/ui/SectionIndex.tsx`), sticky, which
  highlights the section in view. The Terms page now uses the same component.
- **Methodology sections:** what the base is · where the data comes from · from source to
  Registry · how an answer is made · how a fit score is made · what confidence means · known limits.
- **Taxonomy sections:** how the taxonomy works · one per domain (drafts labelled) · shared
  vocabulary. Domains are sections, not nested tabs.

## Verification

The frontend has no unit-test runner, and this phase adds none.

- **`npx tsc --noEmit`:** clean.
- **`npm run lint`:** 0 errors. The 19 warnings were already there.
- **`scripts/smoke.sh`:** 16 of 17 pass. The failure is the known `documents: 96+` gap on a
  fresh seed. New checks:
  - `ask preview (signed out)`: signed-out `/ask` carries the preview marker.
  - `import keeps its destination`: a signed-out `/import` redirects with `next=%2Fimport`.
- **`next build`:** passes.
- **Signed-out `/ask`:** no CopilotKit `<script>` or `<link>` tags, on `next dev` and on
  `next start`.
- **`?q=`:** prefills the preview's composer.
- **`safeNextPath`:** checked against `/ask`, `/import?x=1`, `//evil.com`, `https://evil.com`,
  `/\evil.com` and `null`.

**Before merging (merging to master deploys):**
- Supabase → Authentication → URL Configuration → Redirect URLs includes the deployed domain
  with a wildcard (e.g. `https://sangam.projecttech4dev.org/**`), so `?next=` survives sign-in.
- The Vercel frontend build has `NEXT_PUBLIC_API_URL`, and the backend's allowed origins include
  the frontend domain: the Import panels are now fetched from the browser.

**Still to check by hand in a browser:**
- first, that the signed-in workspace loads at all (`/ask` through `WorkspaceLoader`, and
  `/import` with its provider), since neither signed-in path has rendered since this change;
- the Google round-trip itself, landing on `/ask` with the question prefilled;
- a Registry profile's "Ask Sangam about …", signed out and signed in;
- the navbar at phone width;
- the avatar menu;
- logging out on `/ask`;
- the workspace's height with the navbar and footer around it.

## After the PR merges: one design-system update

Changes to push to the design system in a single sync, with the owner's agreement:
- **Corners:** the three tokens above, plus a guideline in `guidelines/radii.html`.
- **Type:** the six-step scale only (12 · 14 · 16 · 20 · 24 · 36). Retire the one-off tokens
  (`--fs-kicker` 10.5, `--fs-eyebrow` 11, `--fs-meta` 11.5, `--fs-ui` 13, `--fs-card-body` 13.5,
  `--fs-card-title` 17). Page titles are 36, section headings 20, card titles 16, card body 14,
  labels and kickers 12, and reading pages set body at 16 (`.reading`). The wordmark is 24.
- **`Button`:** drop the `shape` option. Every button is a pill.
- **`Input`:** a pill when single-line, 14px when multi-line.
- **`Nav`:** no Import link, no duplicate Ask button, an avatar menu; shown on every page.
- **A new user-menu component:** `Avatar` + `DropdownMenu`.
- **`Dialog`:** 14px corners.
- **Readme and UI kit:** Ask is public with a preview and keeps the navbar; "NGO" everywhere.

## Out of scope (deferred, scope agreed)

- **Phase 2, Registry (A4–A7):**
  - "NGO" wording;
  - hidden rows and unvetted news;
  - the index, NGO and funder profiles on the design system;
  - then the prototype's content, one tab per PR.
- **Phase 3, workspace (A9–A10):**
  - a sidebar with real URLs;
  - **Admin Tools → Import**, gated on `GET /api/me`.is_staff. This has no design reference
    anywhere; check the design system's proposed Import elements against #82 first.
  - the Ask workspace on the design system.

  This phase waits for #61 and #82.
- **B1, after #74 phase 1:**
  - server-side staff checks on `/ingest` and `/api/ingest/*`;
  - `/agent` requires a signed-in user;
  - `/api/copilotkit` is protected;
  - `Bearer dev` is removed.
- **A data-model spec** for Registry content with no schema: map coordinates, certification,
  per-funder rubric weights, match narratives.
