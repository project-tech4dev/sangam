# UI roadmap after Phase 1

Status: agreed scope, not yet built. This is the plan for what follows Phase 1 (PR #86: the
public Ask preview, one navbar, the tightened design system). The design and decisions behind
Phase 1 are in `features-plans/prototype-v1/2026-10-03-ask-entry-flow-design.md`; this file holds
only what comes next, one line per planned PR, so it can be picked up without re-deciding scope.

## Decisions that bind every phase

- **The Claude Design project "Sangam Design System" is the system of record for design.**
  Changes start there and flow into the repo (`docs/DESIGN_SYSTEM.md`, from PR #86).
- **Where they disagree, the design system wins on look; the prototype wins on Registry content.**
- **Reduce before you diverge:** reuse a token, size or component before adding one.
- **"CSO" stays** in the UI. "Vetted", never "hand-vetted".
- **Auth enforcement waits for #74 phase 1** (real Supabase JWT); UI work does not wait for it.

## Order

| Step | What | Waits for |
|---|---|---|
| DS-0 | One-time catch-up of the design system with Phase 1 | #86 merged |
| A4 | Registry correctness | — |
| A5 → A7 | Registry index, CSO profile, funder profile on the design system | A4 |
| R1 → R6 | Prototype content, one tab per PR | A6 / A7; R6 needs D1 |
| A9 | Workspace views as real URLs; Tools gated for staff in the UI | — |
| A10 | Ask workspace on the design system | A9 |
| B1 | Server-side enforcement | #74 phase 1 |
| D1 | Data-model spec for content with no schema | — |
| P1 | Phase 1 follow-ups | — |

## DS-0: design system catch-up (repo → design system, once)

After #86 merges, push its decisions into the Claude Design project, with the owner's agreement:
corner tokens and a radii guideline; the six-step type scale with the one-off size tokens
retired; `--color-accent-750` and the WCAG AA colour rules; `Button` without `shape`; `Input` as
a pill (single-line) or 14px (multi-line); `Nav` on every page with one Ask link and no Import;
a new user-menu component (avatar + dropdown); `Dialog` at 14px; `SectionIndex`; the readme's
Ask, wording and layout rules. From then on, design changes go design system → repo only.

## Phase 2: Registry

Data the API already returns first (A4–A7), then the prototype's content (R1–R6).

- **A4 Registry correctness**
  - Public org and funder endpoints drop `registry_status = 'hidden'` rows; a hidden profile
    returns 404.
  - Profiles show only `review_status = 'vetted'` news; the "Pending review" label goes.
  - The status badge reads `registry_status`; funders are no longer hard-coded "full".
  - To confirm: drop the "North East India" framing from the Registry heading and site
    description, as `prototype-v1/CONTEXT.md` asks.
- **A5 Registry index** on the design system's `Card`, `Tag`, `Input`, `SegmentedControl`/`Pill`
  - CSO blurb from the profile description (always empty today).
  - Pending entries read "Profile in vetting" and are not links.
  - Keep the data-driven place filters, the `?type=` deep link and the empty state.
- **A6 CSO profile**
  - Credentials show the real `verified` flag ("On file" otherwise) and link their source.
  - Contacts show whether they are verified; programmes show their `details`.
  - Geography: fix "States" only ever being 1; hide villages and families until there is data.
  - The hero shows a description instead of the registration date.
  - A provenance line per section (source name · fetched date).
- **A7 Funder profile**
  - Mandate as labelled fields, not the raw key/value dump.
  - One blurb field on both the index and the profile.
  - Each match links to its CSO; the hard-coded "of 10 in the cohort" becomes a real count.
  - `ScoreCard` uses the shared API client instead of its own `Bearer dev` fetch.
  - Identifiers and provenance shown.
- **R1 Financials tab** (CSO) from `org_financials`: income, growth, programme spend.
- **R2 Impact tab** (CSO) from `metrics`: values against targets; feeds villages and families.
- **R3 Programmes & taxonomy** from `tags.kind` and `program_tags`: sector footprint, SDGs, and
  each programme's taxonomy cell. Best after D1 loads the taxonomy into Postgres.
- **R4 Funder giving** from `funder_csr_years`, `funder_csr_spend`, `funder_footprints`,
  `funder_partners` and the 0019 grant-band fields: giving by year, sector split, grant shape.
- **R5 Signals** from the 0010 columns (`kind`, `platform`, `review_status`, `sentiment`): news
  and social, vetted only.
- **R6 "What they look for"** (funder): needs per-funder rubric weights from D1.

## Phase 3: Ask workspace

Phase 1 already moved Import into the workspace (sidebar → Tools → Import, `/ask?view=import`).

- **A9 Workspace views as real URLs**
  - Conversations, Doc vault, Media & signals and RFP watch each get a URL, as Import has.
  - Tools shows only when `GET /api/me` reports `is_staff`. Everyone is the staff dev user until
    B1, so nothing visible changes yet.
  - Before building, compare the design system's proposed Import elements (ten-field record,
    coverage bar, Gaps-only filter, "Write to catalog", merge actions) with the run screen #82
    shipped, and agree which one leads.
  - Settle the phone layout for sidebar plus conversation, which the prototype leaves open.
- **A10 Ask workspace on the design system:** `ChatPane`, `AnswerCard`, `TraceCard`,
  `EvidenceRail` and the Vault, Media and RFP views move from inline styles to the design
  system's tokens and components. The prototype marks Ask as draft, so this is directional.

## B1: auth enforcement (after #74 phase 1)

- Staff check on `/ingest` and `/api/ingest/*`.
- `/agent` requires a signed-in user; `/api/copilotkit` joins the protected prefixes.
- The six `Bearer dev` call sites send the Supabase token
  (`grep -rn "Bearer dev" frontend` to find them).

## D1: data-model spec

For Registry content with no schema today: district coordinates or GeoJSON for the map,
certification, per-funder rubric weights, and per-match narratives and caveats. Also: load the
taxonomy domains (Livelihoods, Education, Health) into Postgres as `tags` of kind `domain` and
`cell`, so `/resources/taxonomy` reads the API and the frontend's copied JSON goes.

## P1: Phase 1 follow-ups

Small gaps the Phase 1 reviews left, none blocking:

- An unsent chat can't be reached from another workspace view (accepted for now).
- Signing in from the navbar doesn't keep a question typed in the preview.
- The Taxonomy page ships all four JSON files to the browser (~104 KB), untyped.
- Home's slide dots and logo placeholders still use Tailwind's stock radius steps.
- Scrolling past the end of a chat scrolls the page under the navbar.
- A question left from an abandoned sign-in wins over a later `?q=`.
