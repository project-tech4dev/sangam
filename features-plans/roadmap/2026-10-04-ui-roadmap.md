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
- **"CSO" stays** in the UI. "Vetted", never "hand-vetted". No "North East India" framing in
  product copy; place names in records stay.
- **Auth enforcement waits for #74 phase 1** (real Supabase JWT); UI work does not wait for it.

## Order

| Step | What | Waits for |
|---|---|---|
| DS-0 | One-time catch-up of the design system with Phase 1 | #86 merged |
| A4 | Registry correctness | — |
| A5 → A7 | Registry index, CSO profile, funder profile on the design system | A4 |
| R1 → R6 | Prototype content, one tab per PR | A6 / A7; R3 and R6 need D1 |
| A9 | Workspace views as real URLs; Tools gated for staff in the UI | — |
| A10 | Ask workspace on the design system | A9 |
| B1 | Server-side enforcement | #74 phase 1 |
| D1 | Taxonomy as themes in Postgres, and content with no schema | — |
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
  - Drop the "North East India" framing from the product copy: the Registry heading ("…of North
    East India CSOs…") and the site description in `app/layout.tsx`. Place names inside records
    (Assam, Udalguri, Action Northeast Trust) stay; they are data, not framing.
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
- **R3 Programmes & themes** from `program_tags`: each programme's sub-themes and lenses, with
  the SDGs and Schedule VII sectors they imply. Needs D1's themes in Postgres.
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

> **Changed 2026-10-04: the taxonomy is themes first.** The earlier plan loaded the occupation
> trees (Livelihoods macro-sectors and tracks, Health care levels, Education areas) as the primary
> tags. Matching and planning happen in funders' terms, and an LLM supplies the fine nuance at
> query time, so the primary tags are now a short two-level list of **themes and sub-themes**,
> with the standards hung on each sub-theme. The trees are parked, not deleted.

**Taxonomy, themes first** — source `features-plans/data-model/seed/data/taxonomy/themes.json`
(already shown on `/resources/taxonomy` from PR #86):

| Domain | Themes | Status |
|---|---|---|
| Livelihoods | Skilling for jobs & employment · Economic empowerment of SHGs · Nano & micro entrepreneurship in farm & non-farm sectors (farm, FPO and natural-resource work folded in) | active |
| Health | Maternal, child & adolescent health and nutrition · Primary & community health systems · Disease prevention & control · Care for vulnerable groups | draft |
| Education | Early years & foundational learning · School quality · Access, inclusion & retention · Pathways beyond school | draft |

What happens to each part of the earlier taxonomy:

| Part | Fate |
|---|---|
| Themes and sub-themes | **New, primary.** `tags` of kind `theme`; a sub-theme's `parent_id` is its theme. No migration: `theme` is already an allowed kind |
| SDGs, Schedule VII (two-level MCA sectors), government schemes | **Kept, as crosswalks** in each sub-theme's `meta`, so tagging a sub-theme gives all three |
| Population groups, lenses (women & girls, tribal & remote, digital, climate-smart) | **Kept**, shared across domains; lenses add SDGs |
| The 24 Sangam sectors | **Retired**, `replaced_by` the matching theme |
| "Enabling work" kinds | **Absorbed** into sub-themes (institution building, financial inclusion, …) |
| Occupation tree, tracks, care levels, ISCED levels, NIC/CRS codes | **Parked** as an optional second layer, for matching at scale |
| Darpan → Sangam map | **Retargeted** from sectors to themes |

**How tags get assigned:** Sangam Import (an LLM) proposes sub-themes and lenses for each
programme and each CSR filing line, quoting its evidence (`is_inferred = true`); a person confirms
during vetting. Queries narrow with the tags in SQL, then the LLM judges and explains. Classified
CSR lines give spend per sub-theme — the evidence behind theme sizing.

**Schedule VII decision still open:** load the two-level MCA list (14 groups, 30 sectors) that the
crosswalks use, with today's 12 clauses pointing at it via `replaced_by` so imported spend keeps
resolving. Recommended; needs confirming, along with moving the taxonomy from `features-plans/`
into the live seed.

**Steps:**
1. One loader and one data folder: `seed/taxonomy_seed.py` loads Schedule VII, SDGs, population
   groups, lenses and themes from `seed/data/taxonomy/`; `make seed` runs it.
2. `GET /api/taxonomy`; `/resources/taxonomy` reads it and the frontend copy goes.
3. Import classifies programmes and CSR lines into sub-themes; vetting confirms.

**Registry content with no schema today** (unchanged): district coordinates or GeoJSON for the
map, certification, per-funder rubric weights, per-match narratives and caveats.

## P1: Phase 1 follow-ups

Small gaps the Phase 1 reviews left, none blocking:

- An unsent chat can't be reached from another workspace view (accepted for now).
- Signing in from the navbar doesn't keep a question typed in the preview.
- The Taxonomy page ships all four JSON files to the browser (~104 KB), untyped.
- Home's slide dots and logo placeholders still use Tailwind's stock radius steps.
- Scrolling past the end of a chat scrolls the page under the navbar.
- A question left from an abandoned sign-in wins over a later `?q=`.
