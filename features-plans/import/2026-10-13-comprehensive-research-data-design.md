# Import: every finding in the catalog, every source in the document base

Status: **draft for discussion**. Proposal, not as-built. Updated as decisions land.

## Why

Import researches an organisation, saves typed findings to `entity_research.findings`, renders a
brief from them (`brief.py`) and writes the catalog from them (`promote.py`). Laying every staging
row and every finding for KABIL and Axis Bank Foundation side by side (the Registry mock, boards
"KABIL" and "Axis", origins marked) showed that a good deal of what the research found never
reaches the catalog, and some never reaches the brief:

- Mission 2 Million and Mission 4 Million were found, and neither became a programme.
- Nine SLP component spend lines were held: "no programme of that name".
- Seven Axis partners were held "waiting for a person"; "Axis Bank Foundation (ABF)" was held as
  "not a funder Sangam holds" although the funder exists with that alias.
- Axis's 23,686 villages and KABIL's registered address exist only inside quotes.
- KABIL has three research runs; its public brief is the oldest of them.
- The profile API serves none of: CSR years, spend / footprint / programme lines, funder
  programmes, metrics, documents, eligibility, RFPs, financials.

A better prompt alone does not fix this: the plumbing between research and the database drops,
overwrites and fails to link.

## What happens today (from a read of the code, 2026-10-13)

### Briefs and research rows are overwritten

- One brief per slug, `entities/<slug>.md`, uploaded with `replace=True` on every save
  (`brief.py:230-240`, called from `save_research`, `research_tools.py:373`). No history.
- `entity_research` is unique on `(slug, researched_on)` (`0016`). A same-day re-run replaces
  every column, findings included (`research_tools.py:337-354`); a smaller save is refused, a
  larger *different* one wins and whatever only the first run found is lost.
- A later day starts a new row with no carry-over, and everything downstream reads only the
  newest row per slug (`catalog_tools.py:462`, `research_tools.py:420`).
- The slug comes from the researcher's spelling of the name, so one entity can split across
  slugs and briefs. `resolved_org_id` / `resolved_funder_id` are set after promotion and never
  used to pick the target of the next run.

### Links and provenance

- Each finding prints its source name, URL and confidence; the brief lists `sources_read`.
- **No page or section is stored** (`FindingBase`, `research_records.py:140-154`); "pp.33-35"
  survives only by chance inside `evidence`.
- `confidence`, `basis` and the evidence quote never reach a catalog row; the quote survives
  only in the research JSON.
- One private finding replaces the whole public summary with a note (`brief.py:180`).

### The document base is half there

- `fetch_document` archives every PDF to storage (`research_tools.py:236-240`), but a
  `documents` row is made only when the researcher also saves a `document` finding.
- HTML pages read with `read_page` are neither archived nor catalogued.
- `doc_type` is free text; nothing links a document to the programme it describes; no finding
  points at an archived copy.
- Nothing asks the researcher for impact assessments, evaluations or programme reports.

### Tags

- Only `identity`, `org_identity` and `program` carry tags (`Tagged`, `research_records.py:217`).
- A tag without `tag_note` fails the **whole** save; an invented code is not checked at save and
  is dropped at write (`writer.py:946-955`).
- SDG is a seeded tag kind that nothing emits.
- csr_spend sectors map to Schedule VII `csr_sector` tags for funders only; nothing rolls
  programme tags up to an org.
- Profile serves tags without their note; programme tags are not served.

### Matching, aliases, duplicates

- `resolve_funder` / `resolve_org`: identifier → exact → single alias → boilerplate (trigram ≥
  0.35 and identical cores) → trigram candidates for a person (`matcher.py`).
- Parentheticals are kept as tokens ("Axis Bank Foundation (ABF)" ≠ core "axis bank"); a
  single-token core never matches; website domain is never a signal.
- A spelling that matched by CIN or boilerplate is not recorded as an alias.
- There is no merge tool. A miss is a new row, permanently.
- Funder partner lines link `partner_org_id` only on a confident match; trigram candidates are
  silently left unlinked and csr_spend partners are never linked.

### Silent drops and the close-match gate

- On the funder path, `Gate.on_new` holds any new row within ~0.35 trigram of an existing one in
  the same funder/kind/year (`writer.py:115-226`). "Mission 2 Million" is close to "Mission 1
  Million"; generic project titles trip it for partner lines (likely the seven Axis partners).
- While a programme is held, every spend / footprint / metric line naming it is **written with
  `program_id` NULL** (`promote.py:624`); after a person answers, the next promote inserts a
  second row and the NULL one is orphaned. Its tags are dropped with no reason
  (`promote.py:306`).
- Child programmes resolve `parent_name` only against the same payload (`promote.py:526`).
- `csr_years_from` errors are logged, not held (`promote.py:382`); identity errors surface as
  "no identity finding"; wrong-kind concepts are ignored with no report; held results from
  footprint / partner / programme_spend writes are discarded.
- Funder-side programmes, metrics and contacts lose `source_type` / `evidence_tier`
  (`writer.py:483` allowlist).

### Columns with no source, and fields with no column

- No home: registered address text, a funder's founding year and legal form, programme places
  (`program_locations` was dropped in `0033`).
- Never filled by research: `programs.details`, `rfps.details`, `contacts.phone`,
  `*_locations.valid_from/to`, `archive_url` on every table.

## Decisions taken so far

1. **Fold "serve what's stored" into the profile build** (`feat/registry-drop-scores`).
2. **Spend components become programmes.** A `programme_spend` naming a component that does not
   exist creates it under its parent and attaches the amount.
3. **No stubs for funders or orgs named in documents. Match later.** Names in source documents
   are unreliable ("NABARD NE Region", "Axis Securities", "Keystone"). Partner lines are written
   by name with `partner_org_id` NULL; an NGO's funder lines that name an unknown funder stay held
   in the findings. When a funder or org is added, a no-model pass links held names: a clear match
   links, a "resembles" goes to the resolution queue.
4. **Build phase: every import confirms or contradicts what the catalog holds.** No hashing or
   staleness stops yet.

## Design

### 1. A findings store instead of a snapshot per run

New table `research_findings`: one row per finding, accumulating across runs.

- Keyed on the **entity id** (not a spelling), concept, the fact's natural key (e.g. funder +
  fiscal year + project) and source document.
- Carries the typed finding, quote, source document and page, confidence, basis, run id.
- Ends in exactly one state: `written` (with the catalog table and row id), `confirmed`,
  `contradicted` (in the resolution queue), `held` (with the reason), or `superseded` (a stronger
  source won).
- `entity_research` stays as the run log; its `findings` JSON stays as the raw record.

This removes overwrites, lost runs and silent drops, and lets every catalog cell show the
sentence behind it.

### 2. Versioned briefs from the store and the catalog

- Each save writes `entities/<entity-id>/<date>.md`; `entities/<slug>.md` is the latest.
- Rendered by code from the store plus the catalog. Every fact line shows value, quote, source
  (archived copy and page) and state. Private sources stay out, per fact, not per summary.

### 3. A brief laid out field by field

Each section lists **every** field, with a value, "not stated (source)", "could not read
(source)" or "no field yet". ★ marks fields needing a column.

| Org section | Fields |
|---|---|
| Identity | legal name, other names, kind, legal form, registration date, registered office (state, district, address★), website, own description, staff count and what was counted, network or parent★ |
| Registrations | 12A, 80G, FCRA, PAN, Darpan, CIN, registration no.: number or application ref, status, valid from/until, how checked, evidence tier |
| Where it works | state → districts, role (registered / operates / funds), note, programme★, source |
| Programmes | theme → programme → phase → project: kind, description, status, start/end, places★, metrics (value, target, unit, period, stage, method, place), tags with their note, documents |
| Money in | per funder per FY: amount, project, dates, status, evidence tier, link to funder; per FY: income, programme / other spend, foreign contribution and unspent, audited |
| People | public contacts and role mailboxes; count of non-public ones |
| Documents | title, type, period, original link, archived copy, pages used, facts drawn |
| Themes | themes / sub-themes, populations, lenses, SDGs (derived), each with its note |

| Funder section | Fields |
|---|---|
| Identity | name, other names, type, parent and its CIN, CIN, Section 135, website, founded and legal form★, registered office★, intake posture (intake mode, funds external, duration, grant band) |
| CSR by year | the 11 statutory figures, impact assessment done |
| Spend lines | per FY per project: name, filed sector → Schedule VII clause, domain / theme, state / district, partner and CSR-1, implementation mode, outlay, amount, project count, ongoing |
| Programme tree | theme → programme → component → phase, with its own figure per component per FY, documents |
| Footprint and priorities | per FY states → districts as printed, by programme; stated priority places with notes |
| Partners | per FY: name as printed, kind, CSR-1, programme, project, amount, dates, status, Sangam link |
| Reach | metrics: value, target, unit, period, stage, method, place, programme |
| Eligibility and open calls | statutory restatement, own bar, disqualifiers verbatim; each open call's band, deadline, places, rules |
| People, documents, themes | as for an org |

Every brief ends with: **Stated, but Sangam has no field for it** (the input to the next schema
change) · **Held, contradicted or waiting for a person** · **Looked for, not found** · **Document
base** (below).

The profile page uses the same sections, so brief, page and catalog read alike.

### 4. The document base

- **Every source read is a `documents` row, made by code**, not left to a `document` finding:
  `fetch_document` and `read_page` create or update it (title, publisher, period, original URL,
  archived object, content hash, owner). Pages are archived as text. Private sources stay
  private.
- **A fixed `doc_type` list**:
  - statutory: annual_report, csr_annexure, brsr, csr_policy, annual_action_plan, fcra_return,
    audited_accounts, registration_certificate;
  - programme: **impact_assessment**, evaluation, baseline_study, programme_report, case_study,
    mou;
  - other: web_page, news, research_paper.
- **A link table** `document_links (document_id, org_id | funder_id, program_id, fiscal_year)`,
  so a programme lists its impact assessments and reports.
- **Findings cite `document_id` + page**, so a fact outlives its URL.
- **A research goal to look for programme documents.** For a funder, the CSR Rules require an
  impact assessment from a company with an average CSR obligation of ₹10 crore or more, for each
  project of ₹1 crore or more, annexed to its annual CSR report. The researcher looks for each,
  in the CSR annexure, on the foundation's site and on the implementing partner's site.
  `funder_csr_years.impact_assessment_done = true` with no report found is a visible gap. For a
  CSO: evaluations, baseline studies and programme reports, often published by the funder or the
  evaluator.
- Briefs and the profile's Documents tab list the base grouped by programme and type: original
  link, archived copy, pages used, facts drawn.
- Optional: chunk and embed for Ask (`chunks` exists).

### 5. Tags by code where possible

- Validate codes at save and return a bad one to the researcher; a missing note refuses that tag,
  not the save.
- Derive SDGs from the theme tree's existing cross-references.
- Roll programme tags up to the org, and spend domains to the funder.
- Serve the note with each tag; serve programme tags.

### 6. Matching, aliases, the gate

- Parenthetical short forms become aliases; website domain is a match signal; a single-token core
  matches when an identifier or the domain agrees.
- Every spelling a source uses is recorded as an alias on **any** match.
- A re-run targets the row its earlier runs became (`resolved_*_id`), not a fresh name match.
- The close-match gate never treats names differing only in a number as the same, and compares
  partner lines by partner name, not loose similarity.
- Findings that depend on a held programme are held with it, never written with a NULL link.
- Near-match partner orgs go to the resolution queue; csr_spend partners are linked too.
- `parent_name` and `program_name` resolve against the catalog, not only the same payload.
- Later: a staff merge ("these two are the same").

### 7. The researcher's contract

Code enforces coverage and the quote scan; the rubric checks the rest.

```markdown
## What you hand back is a brief, not a summary

Your save is the source of a public brief and of the catalog. Code renders the brief from it,
so anything you know but do not save does not exist.

**Every field in `research_goals` gets an answer.** For each concept and each of its fields:
- a finding, quoted, sourced, with the page or section; or
- a gap: `not_stated` (a working source you read is silent; name it) or `blocked`
  (you could not read it; name the registry or page).
The save is refused if any field has neither.

**Extract what you quote.** If your evidence sentence contains a number, a place, a date,
a person's role or another organisation's name, each is its own finding in the concept it
belongs to: a reach figure is a `metric` (value, unit, period, stage); a place is an
`org_location` / `footprint` / `stated_geography` with its state; a founding or registration
year belongs on `identity` / `org_identity`; a funder or partner is a `partner`; a parent
company is `identity.parent_name`. With no concept for it, put it in `unplaced` with the
quote. Code checks your quotes for this.

**Programmes are a tree, and money hangs on the tree.** Every component a funder reports a
figure for is a `program` with `parent_name`, and its figure a `programme_spend` naming that
exact component. Every phase you name is a `program` of kind `phase`. A target is
`metric.target` on the same metric as its achievement.

**Find the documents behind the work.** For each programme, look for its impact assessment,
evaluation, baseline and programme reports, from the organisation, its funders and its
evaluators. A funder whose CSR obligation is ₹10 crore or more must assess each project of
₹1 crore or more: look for every one. Read each you can reach; cite pages.

**Confirm what Sangam already holds.** `research_goals` shows the catalog's current values.
Save a finding for every one you find a source for, even if it agrees.

**Write the account, section by section.** In `sections`, 3 to 6 plain sentences per
section that has findings: what it does there, where, at what scale, for whom, since when.
Cite each claim as [f:<index>]. Only your findings; no adjectives the source did not use.

**Organisations you meet.** Name every funder, partner, parent and sister company as printed,
as its own finding. Never create or merge one; matching is done later, by code.
```

Schema version 3 adds `page` on `FindingBase`, `sections`, `unplaced`, and `document_id` once
the document base exists.

## Migration 0046 (sketch)

- `research_findings` (the store).
- `document_links`; `documents.doc_type` check on the fixed list; `documents.publisher`,
  `period_from/to`, `archive_key`.
- ★ columns wait for the "no field yet" list from real runs.

`0045_drop_news_mentions` is still unapplied on staging; 0046 is independent, but staging must
run both in order after deploy.

## Order

1. Findings store, versioned briefs, an end state for every finding, the silent-drop fixes.
2. Document base: rows by code, type list, links, finding → document + page.
3. Matching, aliases, the gate, partner linking, the programme-component tree.
4. Researcher contract (schema v3), tag checks, SDG and roll-ups.
5. Backfill: load every `entity_research` row into the store (KABIL's three runs merge),
   re-promote and re-render with no model calls; a cheap model over stored quotes only.
   KABIL and Axis become eval cases, each with the fields the catalog should end up holding.
6. Profile build (`feat/registry-drop-scores`) serves everything above.

## Open questions

- **Archived copies in public?** Proposal: link the original publicly; the archived copy is
  Sangam's record for staff and Ask, shown publicly only when the original is dead.
- Is a findings table the right home, or merged JSON on `entity_research`? (Proposal: table; it
  is queryable and carries the row link.)
- Which ★ columns to add first.
- Scope of the build-phase "confirm" pass once the catalog is large.
