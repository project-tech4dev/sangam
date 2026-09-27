# Sangam — prototype context

## What this is
A clickable prototype for FFRH's NGO–funder matchmaking platform ("Sangam"), covering an open public layer and a login-protected agentic layer. Built as Design Components on the Organic design system (cream/terracotta/sage, Caprasimo + Figtree).

## Files
- `Home.dc.html` — landing page: hero, three reader tabs (NGOs / Funders / Ecosystem players), how-the-base-is-built section, logo strip (drag-and-drop slots for Node/FFRH/Tech4Dev/Bridgespan).
- `Registry.dc.html` — open, filterable index of NGOs and funders in the base.
- `ProfileSeSTA.dc.html`, `ProfileANT.dc.html` — vetted NGO profiles (real Node/SeSTA cohort orgs).
- `ProfileAPF.dc.html` — funder profile, mirrors NGO profile shape (Azim Premji Foundation, the one real named funder).
- `Resources.dc.html`, `Methodology.dc.html`, `Taxonomy.dc.html` — Taxonomy now lives under Resources rather than top-level nav; Methodology modeled on Cravis's "About the Atlas" page.
- `AskSangam.dc.html` / `Sangam.dc.html` — Ask Sangam: public free-text Q&A up front; any query execution requires a mock Google sign-in; signed-in state opens the protected agentic shell.
- `styles.css` — shared overrides on top of the DS bundle (button hover states, nav/footer tint, etc).

## Key decisions from the conversation

**Scope cut:** Proposal Studio was removed as a standalone page and folded into Ask Sangam behind login — org vault (renamed **Doc Vault**), RFP matching, and draft-checking are all part of the signed-in Ask Sangam experience, not a separate nav item.

**Nav simplified:** Registry, Ask Sangam, Resources (Taxonomy + Methodology nested under it). Ask Sangam appears once — dropped the redundant nav-button duplication; the home page keeps its own "Ask Sangam" CTA button.

**Data / demo scope:**
- One real named funder: Azim Premji Foundation.
- Two real Node/SeSTA-cohort NGOs with full vetted profiles: SeSTA and The ANT (Action Northeast Trust). Diya Foundation flagged as a third org to potentially add, currently referenced as pending/placeholder.
- Registry scope = NGOs and funders in one filterable index, not split into separate directories.
- Everything else in the base (other funders, other NGOs) is explicitly shown as pending/placeholder — the demo is honest about sparse coverage rather than papering over it.
- Disclaimer/legal notice: off for this demo.
- No single guided path — the whole prototype is meant to be clickable in any order, equally weighted.

**Base composition (open, public):** four feed sources power the open Registry — funder priorities & CSR filings, NGO self-reported data, taxonomy/classification, and media (news + social signal, both positive and negative). Proposal/RFP archives were deliberately excluded from this list since they're org-specific and belong behind login, not in the open base.

**Ask Sangam — the core design problem:**
- Modeled conceptually on Cravis/Travis.ai's agentic answer format: a visible step trace (reading the question → retrieving → scoring → answering), inline clickable citations back into the Registry, a "why this match" expandable per result, confidence/gaps flagged explicitly, and suggested follow-up questions after each answer.
- Public (logged-out) Ask Sangam: free-form typing, best-guess reply — but executing a query prompts sign-in rather than answering.
- Login is a mocked Google auth modal (no real OAuth) — continuing signs the user in instantly. The modal should pop up immediately on any query attempt, not navigate away first.
- Originally the protected area had three fixed persona tabs (FFRH staff / Advisory / NGOs) with mostly separate UI per persona. Direction shifted: fewer hardcoded personas, more agent-driven — the agent should interpret intent from a single conversation rather than the UI pre-branching into rigid flows. Advisory-group-as-a-separate-reader was folded away; "Ecosystem players" replaces "Intermediaries" as the third external reader type on the marketing/home page (this describes intermediaries/advisory/national orgs collectively, not a fourth persona in the protected app).
- The intended shape for the protected shell: a left-rail sidebar (Claude-Projects-style) organizing conversations by use case — proposal writing, media/signals monitoring (positive and negative sentiment, to affirm or push back on), RFP watch (auto-pulled weekly batch of matching RFPs) — each use case holding multiple conversations, most-recent 5 showing with a "view all." Doc Vault sits as one more item in that rail, underneath the use-case items, not as a top-level separate page.
- Actions taken on media items or RFP-watch entries (write, push back, affirm, etc.) should hand off into an Ask Sangam conversation with that context (the proposal, the media item, the chosen action) already baked in — the agent does the work, not a bespoke UI per action type.
- File upload and voice input planned for the Ask Sangam composer; uploaded files land in the Doc Vault.
- Signed-in state should show a profile avatar/name in the top corner; clicking it shows profile info and a logout option (replacing a plain "log out" button).
- Org-data completeness (the vault gap indicators — missing board minutes, missing accounts, etc.) stays as currently designed; the plan is to surface a mini nudge/banner *within* a use-case conversation when org data is incomplete, asking the user to fill the gap, rather than a separate gate.
- Scoping by org: a user's visible RFPs/data should be scoped to the org(s) their role has access to (one org vs. multiple orgs), a permissions dimension not yet implemented in the prototype.
- Open question flagged but not yet resolved: how a free-flowing agentic conversation (plain chat) can still produce the structured, styled outputs (step trace, citation chips, scored criteria cards) the demo currently hand-builds per intent — since a real LLM conversation wouldn't naturally emit that exact styled UI. Needs a follow-up design pass (e.g. agent emits structured "cards" as message types, rendered by the shell) before building further.
- Conversations are not yet persisted in this prototype (no real storage) — flagged as a gap, not yet built.
- Mobile behavior for the sidebar-plus-conversation split view is an open question — not yet resolved or designed.

**Visual/style decisions:**
- Adopted the Organic design system as bound (cream/sand ground, terracotta primary accent, sage secondary accent, Caprasimo headings + Figtree body).
- Terracotta accent shade for buttons/highlights settled on `#E0A177` (lighter than the DS default) after reviewing swatch options.
- Switched away from Familjen Grotesk to a cleaner, less distinctive pairing consistent with the DS type choices.
- Nav bar: a lighter tint of the sage green (not a separate new color), pushed toward a "liquid glass" translucent treatment; footer shares the same green treatment, darkened somewhat on request; page background carries a faint green tint in the same liquid-glass style, darkened ~20% from the first pass per feedback.
- Button hover/active states use `--color-accent-900` (deep terracotta) for text rather than plain black, matching the Registry's own hover treatment, for contrast without breaking the palette.
- Footer condensed to: General Terms of Use, AI Privacy Policy, © 2026 — with "AI Terms of Use" removed per feedback, and no repeated links.
- Page-title headings (`Registry`, `Ask Sangam`, `Resources`, `Methodology`, `Taxonomy`, home hero) reduced from responsive clamps up to 52–68px down to a fixed 40px; mid-level section headers (e.g. home section intros, profile org-name headings) scaled down in step from ~30–34px to ~24–28px, leaving smaller body/card text untouched.
- Home page stat cards (12 NGOs / 8 funders / 26 districts) were tried in two treatments (a single wide banner, then a 3-card grid with icon badges) and ultimately removed entirely — decided they weren't earning their place, in favor of a cleaner, more Cravis-like open hero.
- Logos (Node, FFRH, Tech4Dev, Bridgespan; SeSTA removed from the strip) use drop-in `<image-slot>` placeholders — Claude cannot generate or fetch real logo art, so these are user-fillable drag targets, not final art.

**Geographic framing:** the North East India focus was removed from the product framing (hero, about copy, feed sources, funder notes). Org names and record-level geography (e.g. Action Northeast Trust, Assam districts) are kept as factual data.

**Type system:** one family (Public Sans via `--font-heading` / `--font-body`), two weights (400, 700), and a six-step size scale tokenized in `styles.css` — `--fs-xs` 12, `--fs-sm` 14, `--fs-md` 16, `--fs-lg` 20, `--fs-xl` 24, `--fs-2xl` 36 (all Tailwind stock sizes). Every inline font-size references a token; no raw px sizes.

**Build phasing:** first build is the Home page and the Registry (incl. profiles). Ask Sangam and Resources (Methodology, Taxonomy) carry a large DRAFT watermark: they are directional, not ready to develop.

**Terms & Privacy:** `Terms.dc.html` (routes `#terms` and `#privacy`) merges general terms, AI terms and privacy into one page, written for Sangam. It covers public vs private vault documents, role-scoped visibility, OpenAI and Anthropic as API vendors for embeddings and agent answers (no training opt-in), retention and deletion windows, and India's DPDP Act. It is draft text that needs counsel review, and the contact email is a placeholder.

**Dev handoff:** `styles.css` also exposes the tokens under shadcn/ui variable names (`--background`, `--primary`, `--card`, `--sidebar-*`, …). `HANDOFF-shadcn.md` maps each prototype class to its shadcn component and each type token to a Tailwind size.

**Stock shadcn first:** corners and type follow shadcn/Tailwind defaults (radius 10px; buttons, inputs and badges `rounded-md`; cards `rounded-xl`; no pills). Brand tweaks come later.

**Export package (`export/`):** `Sangam Prototype.html` (all pages, offline), `sangam-theme.css` (React/Tailwind v4/shadcn theme import), `sangam-prototype.css` (prototype stylesheet, reference only), `HANDOFF-shadcn.md`, and this file.

## Current page state
- **Home** (build phase 1): eyebrow line "Surfacing · Assessment · Narrative · Grantmaker Access · Matching" full-width; 60:40 hero with a merged intro paragraph and a text-only slideshow (NGOs / Funders / Ecosystem players, three concrete outputs each, 8s crossfade); feeds-the-base cards (funder filings, NGO profiles, taxonomy, media); logo slots (Node, FFRH, Tech4Dev, Bridgespan); newsletter with consent checkbox above the email field. No stat cards, no Explore section, no cohort or hand-vetted wording, no North East India framing.
- **Registry + profiles** (build phase 1): SeSTA, The ANT, Azim Premji Foundation. Geography tabs use a real OSM/Leaflet map (`DistrictMap.html?org=…`) with animated district pins.
- **Ask Sangam, Resources/Methodology/Taxonomy**: DRAFT watermark; directional only.
- **Terms & Privacy** (`#terms`, `#privacy`): one merged policy, jointly operated by FFRH (incubated within Node/SeSTA) and Project Tech4Dev; Google sign-in collects name and email only. Needs counsel review; contact email and retention windows are placeholders.
- **Naming**: "NGO" everywhere (not CSO); "vetted" (not hand-vetted), and on Home no vetting language at all.

## Known gaps / not yet built
- Real conversation persistence in Ask Sangam.
- The left-rail use-case/conversation-list redesign of the protected area (currently still the three-persona-tab version) — agreed in principle, not yet implemented.
- Org/role-based scoping of visible RFPs and data.
- Mobile layout for the eventual split (rail + conversation) view.
- Reconciling free-form agent chat with the current hand-authored structured answer cards.
- Real logo assets, real OAuth, and the disclaimer/legal copy (deliberately off for this demo).
