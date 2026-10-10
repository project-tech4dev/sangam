# List pages, Funder Match v40, Proposals and the Media & Signals screen

## Context
The prototype (Funder Match Prototype v40, re-read 10 Oct) has moved on from v21, which we built from.
- **Funder Match:** the page now uses the same list pattern as the other screens.
  - lean cards: All fits / Strong / Medium, one always selected;
  - one row of dropdowns: Funder type and Proposal;
  - a search box;
  - a proposal button on each card.
- **Proposals:** a new screen.
  - a list page;
  - three steps: gates; template, documents and style; the section editor;
  - then Assemble, Polish, and a .docx saved to the Doc Vault.
- **Media & Signals:**
  - three bucket cards with dropdowns, search and an infinite list;
  - a public "In the news" tab on Registry profiles.

Two specs already exist on unmerged branches, and the prototype follows them:
- `origin/docs/proposals-spec`: `features-plans/proposals/2026-10-09-proposals-design.md`;
- `origin/spec/media-signals`: `features-plans/signals/2026-10-10-media-signals-design.md`. Its section 7, "one pattern for list pages", covers all three screens.

**Decided (10 Oct):**
- **Proposals:** built to its spec.
- **Media & Signals:** screen only, on today's GDELT `news_mentions`. The Tavily pipeline and classifier, and the new news tables, wait.
- **Order:** shared list components → Funder Match → Proposals → Media.

**Defaults taken (say if wrong):**
- **Score change:** Funder Match keeps "▲ 4 since the last run", which you chose earlier, though v40 no longer draws it.
- **Tests:** no new tests, per the no-tests rule; existing ones are fixed where a change breaks them.
- **Migration number:** 0043, since 0042 is taken.
- **Branches:** every PR stacks on `feat/funder-match-page`.

*Approved 2026-10-10.*

## Milestones (one PR each)

### PR 1: one list pattern (`feat/list-pattern`)
**Design system first:** two new looks, both from existing tokens (`--color-accent-2-700`, white).
- the selected bucket card: dark sage fill, white text;
- the changed dropdown: dark sage, white text and arrow.

These go into the design system's `tokens/base.css` and new component files (`.jsx`, `.d.ts`, `.prompt.md`) with your go-ahead, alongside the drafted Funder Match sync.

| File | Change |
|---|---|
| `frontend/components/ui/ListPage.tsx` (new) | `BucketCards` (2–4 cards, `data-active`, counts given by the page). `FilterRow` (equal columns of `<select className="input filter">`, `data-set` when off default, 2 columns on a phone). `SearchBox`. `InfiniteList` (shows N, an IntersectionObserver clicks "Show N more · M left", then "End of the list") |
| `frontend/components/ui/index.ts` | Export them |
| `globals.css` | `.bucket-cards`, `.bucket-card[data-active]`, `.filter-row`, `.filter[data-set]` with the arrow, `.search-box`, `.list-more` |
| `CLAUDE.md` | One rule: list pages use these components |

**Exit gate:** lint and build pass; design-system files are uploaded and named in the PR.

### PR 2: Funder Match v40 (`feat/funder-match-v40`)
| File | Change |
|---|---|
| `FunderMatchView.tsx` | Replace the stats, pills and Funders checked card with `BucketCards` (All fits "Ranked by fit score", Strong "Score 75 or more", Medium "Score 55–74"). Add `FilterRow` (Funder type) and `SearchBox` ("Search funders and reasons…", over name, type and reasons). Count line: "{shown} of {total} scored funders · ranked by fit score, highest first". The rank stays the full-list position. The weak fold shows only when everything is at its default. Changing the org resets the filters. The picker eyebrow reads "Organisation · all" for staff and "Organisation · N you steward" for a steward |
| `funder-match/funderType.ts` (new) | Spec D13 as a display mapping, with no migration: `corporate_csr` → "Corporate CSR · run by the company", `corporate_foundation` → "Corporate CSR · through its foundation", `private_foundation`/`family_trust*` → "Private or family foundation", others → "Other". The filter uses the part before " · " |
| `MatchCard.tsx` | Show the type label; leave room on the right for the proposal action (PR 3) |

All filtering is client-side: a run is about 43 rows, already loaded.

**Exit gate:** lint and build pass. By hand: every card and filter combination gives counts equal to the list.

### PR 3: Proposals, part 1: the record, the list, steps 1–2 (`feat/proposals-record`)
Spec "Order of work" 1–2, with no model calls yet.

| File | Change |
|---|---|
| `db/migrations/0043_proposal_work.sql` | `proposals.work jsonb`, `summary jsonb`, `rubric_version`. The insert and update policies become `app.my_org_ids() OR app.is_staff()`, and so does `documents_insert`, so stewards and staff can write |
| `backend/app/proposals/{rubric,readiness}.py` (new group) | Rubric v2 as data: A1–A16 with their questions, Strong elements and weak readings; F1/F4/F5; overlays; G1/G2. Display codes A/B/C/F. The ready rule. `summary` computed from `work` |
| `api/routes`, `repositories`, `schemas/proposals.py` + one line in `router.py` | `POST /api/proposals` (org, funder, title), `GET /api/proposals?org&funder`, `GET /{id}`, `PATCH /{id}` (rename), `PATCH /{id}/work` (path allowlist, `jsonb_set` under a row lock, per-section `rev` → 409) |
| `routes/documents.py` | Upload routes use `write=False`; the RLS policy decides |
| `funder_matches` list | Each match gains `proposals: [{id,title}]` (one LEFT JOIN), for the button and the Proposal filter |
| `frontend/features/ask/views/proposals/` (new) | `ProposalsView`: the list page via the PR 1 components (All / In progress / Ready; Funder; Organisation when more than one; Started; search). The proposal shell: header, rename, stepper, Step 1 gates and Step 2 template, documents and style. Saved as you go through `PATCH /work` |
| `Sidebar.tsx`, `AskWorkspace.tsx` | "Proposals" under Use Cases, with a count, and the view wired in |
| `MatchCard.tsx`, `FunderMatchView.tsx` | The action, by state: "Start a proposal", the name form, then "Continue proposal →" with "Start another", or "Proposals (N) →", which opens the list filtered to that funder. Plus the Proposal dropdown |

**Exit gate:**
- Migrated on a DB copy.
- As a steward: start KABIL → Axis from Funder Match, tick the gates, upload a document, reload, and everything is still there.
- A member of another org gets 404.

### PR 4: Proposals, part 2: drafting and the section editor (`feat/proposals-draft`)
Spec "Order of work" 2–4.

**Backend:**
- `proposals/sources.py`: the source pack, read as the caller. It covers the org, the funder, partner lines, Doc Vault chunks, reference figures, and the graph when it's enabled. The markers are `[org:N]`, `[funder:N]`, `[activity:N]`, `[doc:N]`, `[ref:N]` and `[graph:x]`.
- `proposals/draft.py`:
  - one `Settings.model` call per section, returning `{text, sources, missing}`; each missing element becomes an `[Add: …]`;
  - the check on Done or Assemble runs on `utility_model`, and is skipped when the text's hash hasn't changed;
  - the funder brief and the template reading also run on `utility_model`.
- `.docx` and `.xlsx` upload extraction is added to `documents._extract`.
- Routes: `POST /{id}/draft` (one section per request, 4 at a time from the browser) and `POST /{id}/check`. The prompts are `.md` files next to the code.

**Frontend: Step 3:**
- group tabs with `sum/max`, and a left nav with codes and score dots;
- "Drafted from" chips; a textarea with hint pills and a character counter;
- "{n} to add", Done / reopen, and next;
- the readiness strip with "Assemble document".

**Exit gate:**
- Draft one real proposal.
- Every chip cites a marker from its source pack, and gaps show `[Add: …]`.
- Note the cost of one draft.

### PR 5: Proposals, part 3: Assemble, Polish, versions (`feat/proposals-assemble`)
**Backend:**
- `proposals/polish.py`: one `Settings.model` call, in the style and the template's order, adding no facts.
- `proposals/assemble.py`: a plain `.docx` built with `python-docx`, added to `requirements`.
- `POST /{id}/polish` and `POST /{id}/versions`, which write `org-vault/<org_id>/proposals/<id>/v<N>.docx` and a `documents` row with `is_ai_generated` set.

**Frontend:**
- the assemble pane with the "As entered" / "Polished" toggle;
- the stale banner;
- "Save to Doc Vault";
- "Saved versions".

**Exit gate:** polish, then save v1; edit a section and the stale banner shows; polish again and save v2; both appear in the Doc Vault.

### PR 6: Media & Signals screen, on GDELT news (`feat/media-screen`)
| File | Change |
|---|---|
| `schemas/news.py`, `repositories/news.py`, `routes/news.py` | Expose `kind`, `summary` and `sentiment`. Add `bucket=org|funder|general`: org means `org_id` in the caller's orgs (staff: any org); funder means `funder_id` is set; general means neither. Filters: entity, topic, sentiment, source (`kind`), when (30 days or any), and `q` (title, domain). Add `GET /api/news/counts` returning the three bucket counts under the same filters. Paging stays offset, 10 at a time |
| `MediaView.tsx` | Rewritten on the PR 1 components. Cards: entity chip, sentiment tag, headline link, "domain · date", summary. The "Pending review" tag goes. "Discuss in chat →" stays |
| `registry/ProfileTabs.tsx` | The org "Signals" tab becomes "In the news", grouped by month; the funder profile gets the same tab |

Not built: Area, Match/Confidence, "Also reported in", Sangam-written headlines and Hide. They need the classifier pipeline, which comes later.

**Exit gate:** each bucket's count equals its list under every filter; scrolling loads 10 more; the public profile tab works signed out.

## Reused
- `Tag`, `EntityMark` and `ProgressBar` (`components/ui/primitives.tsx`).
- `.import-disclosure`, `.input`, `.card`, `.view`.
- `authHeaders()` and the `call<T>` helper in `funder-match/api.ts`.
- `org_id_for_member` and the Doc Vault upload flow (`routes/documents.py`, `integrations/storage.py`).
- `app.my_org_ids()` and `app.is_staff()`.
- `rubric.tier`.

## Verification
- **Each PR:** `pytest -m "not integration"`, ruff on the changed files, `npm run lint` and `npm run build`.
- **Migrations:** on the throwaway DB copy (the recipe is in `.memory/STATE.md`).
- **By hand on `make up`:** the prototype's click-through as member, steward, staff and no-org, plus phone width.
- **Staging:** `make migrate ENV=staging` only after a backup and your go-ahead.

**Asked before doing:**
- every design-system upload, since V owns that project;
- every push or PR;
- PR 4's first real model calls, which cost money.
