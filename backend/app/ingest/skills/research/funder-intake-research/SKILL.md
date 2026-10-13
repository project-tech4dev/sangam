---
name: funder-intake-research
description: Use when the organisation you are researching GIVES money — a company, corporate foundation, trust or grantmaker — and read it first, because it is your contract — every field of the funder brief, section by section, with the concept and field it is saved as; each one ends as a finding or a gap. It also sets the source order (statutory filings, the funder's own publications, recipients' records, staff workbooks last), how to build the programme tree with its money, how to find the impact assessments and reports behind the work, and how to classify spend lines. Raw field-value-source only; no verdicts. Not for an NGO that receives money — that is ngo-credential-research.
---

# What you pull for a funder

Your save is the source of the funder's public brief and of the catalog. The brief is laid out
field by field, in the sections below, and **every field shows an answer**: a value, "not stated
(source)", "could not read (source)", or "no field yet". So:

**Every field below gets an answer.** For each one, either
- a **finding** — the sentence that states it, its URL, and the `page` ("p.33", "pp.33-35",
  "Annexure 4", "CSR page, Programmes tab"); or
- a **gap** — `{concept, field, fiscal_year, reason, detail}`: `not_stated` when a source you read is
  silent (name it), `blocked` when you could not read it (name the page or registry), `not_reached`
  when the run stopped first (name what was left unread).

`save_research` refuses a save that leaves a concept, an asked year or an identity field with neither,
and names what is missing. A field marked *unplaced* has no column yet: save it in `unplaced`
(`{field, value, evidence, source_url, page}`) so the brief still shows it.

**Extract what you quote.** If an evidence sentence holds a number, a place, a date, a role or another
organisation's name, each is its own finding in the concept it belongs to: "23,686 villages across 15
states" is a `metric` (value 23686, unit villages) **and** the states are `footprint` rows. With no
concept for it, it goes in `unplaced`. The save names every number it finds only inside a quote.

**Confirm what Sangam holds.** `research_goals` and `funder_dossier` show the catalog's current values.
Save a finding for every one you find a source for, even when it agrees: a second source is
corroboration, and a disagreement is how a wrong value gets caught.

**Organisations you meet.** Every partner, parent, sister company and co-funder is named as printed,
as its own finding (`partner`, `identity.parent_name`). Never create or merge one; matching is done
later, by code.

## Where to look, in this order

The order is strength of evidence for money. Your STEP 1 confirmation search always comes first, and
**`read_source_rows` is called after every web read** — its first call closes the web tools.

1. **Statutory CSR filings for the corporate entity.** The filer carries the Section 135 obligation —
   often the parent company, not the foundation that runs the programmes. Record the filer as the parent
   (`identity.parent_name`), never merge them, never put the parent's CIN on the foundation.
2. **The funder's own publications** — annual reports and the CSR annexure, CSR policy, annual action
   plan, impact-assessment reports, BRSR, the foundation's programme pages.
3. **Recipient-side records** — partners' annual reports and grantee pages — for amounts per partner,
   which funders rarely publish.
4. **Staff workbooks, last** — the files picked on the sources card, read with `read_source_rows`.
   Their layouts and units are in your prompt ("The staff sheets").

## The brief's sections, and what each field is saved as

### 1. Identity — `identity`, one finding per source
| Field | Saved as |
|---|---|
| name, as the strongest source writes it | `identity.name` |
| other names it files or trades under | `identity.aliases` |
| type | `identity.funder_type` |
| parent company, and the parent's CIN | `identity.parent_name`; the CIN in the evidence |
| its own CIN (a company; a trust has none) | `identity.cin` |
| bound by Section 135 | `identity.section_135_bound` |
| website | `identity.website` |
| founded, legal form, registered office | *unplaced* (`founded`, `legal_form`, `registered_office`) |
| intake route — portal, email, RFP — and whether it is live when you check | `identity.intake_mode`; the route and the check date in *unplaced* (`intake_route`) |
| funds external NGOs, or implements itself | `identity.funds_external` — quote what decided it |
| typical duration, grant band | `identity.typical_duration_months`, `grant_size_min`, `grant_size_max` |
| co-funding share ("up to 90% of project cost") | *unplaced* (`co_funding_share`) |
| stated focus: themes, populations, lenses | `identity.themes` / `populations` / `lenses` with `tag_note` |

### 2. CSR by year — `csr_year`, one per fiscal year asked
Every statutory figure, each year: `section_135_applicable`, `average_net_profit`, `prescribed_csr`,
`spent_on_projects`, `admin_overheads`, `impact_assessment_cost`, `total_spent`, `unspent_transferred`,
`excess_spent`, `local_area_spent`, `impact_assessment_done`. Obligation, budget, spend, overhead and
unspent are not interchangeable. A year with no filing read is a gap with that `fiscal_year`.

### 3. Spend lines — `csr_spend`, per year per project
`project_name`, `sector` (as filed), `domain`, `theme`, `classified_by`, `classification_note`, `state`,
`district`, `partner_name`, `partner_csr1`, `implementation_mode`, `outlay`, `amount`, `project_count`,
`is_ongoing`, `program_name` when the line belongs to a programme. An aggregate line has no
`project_name` and a `project_count`; never divide it.

### 4. Programme tree — `program` and `programme_spend`
**Programmes are a tree, and money hangs on the tree.**
- Each level is a `program`: a theme, a programme, its components, phases and projects, with
  `parent_name` pointing one level up, plus `description`, `status`, `start_date`, `end_date`.
- A component the funder reports a figure for is a `program` (kind `programme`, `parent_name` its
  programme) **and** a `programme_spend` naming that exact component: "SLP – Rural Livelihoods ₹198.29
  crore, FY2024-25" is `program` "Rural Livelihoods" under "Sustainable Livelihood Programme", and its
  `programme_spend`.
- Numbered missions are separate programmes: Mission 1 Million, Mission 2 Million and Mission 4 Million
  are three, each with its own dates.
- Every programme carries `themes` with a `tag_note` from its own description, or a gap `{concept:
  "program", field: "themes", reason: "not_stated"}` naming it and the source.
- Its places are `footprint` rows with its `program_name`; its documents are in section 9.

### 5. Footprint and priorities — `footprint`, `stated_geography`
- Where the work ran, per year, by programme: `footprint` with `state`, `district`, `program_name`,
  `name_as_printed`. "Barpeta and Kamrup districts of Assam" is two rows. Never a district from a city.
- Where it says it prioritises: `stated_geography` with `note`. A priority is not a footprint.

### 6. Partners — `partner`, per year
`partner_name` as printed, `partner_canonical`, `partner_kind`, `partner_csr1`, `program_name`,
`project_name`, `amount`, `start_date`, `end_date`, `relationship_status`. `amount` null means not public,
never zero. A multi-year grant is ONE finding in the year it started, with both dates. A range of years
from a staff sheet: one finding on its first year, dates set, no amount.

### 7. Reach — `metric`
`name`, `value`, `target`, `unit`, `period`, `stage`, `method`, `is_self_reported`, `program_name`,
`state`, `district`. A target sits on the same metric as its achievement.

### 8. Eligibility and open calls — `eligibility_guideline`, `rfp`
- Standing eligibility, verbatim, one finding per page: `statutory_restatement` (Rule 4 copied into the
  policy), `own_bar` (anything beyond it), `disqualifiers` (thresholds that reject outright). A page
  that states none: `not_stated` with its URL.
- The document checklist, item by item: *unplaced* (`document_checklist`). "Lists 32 items" is the
  right precision; list them.
- An open call — only one with a title and a deadline; a programme page is not a call: `rfp` with
  `title`, `url`, `status`, `deadline`, `amount_min`, `amount_max`, `eligibility` (each rule on its own
  line), `state`, `district`. A closed call is still recorded, marked closed.

### 9. Documents — `document`, one per source you used
`title`, `doc_type`, `as_of` (the period it describes), and `summary`: two to four sentences on what
the whole document covers — its programmes, years, figures and places — not only the line you quoted.
**Find the documents behind the work.**
- A company whose average CSR obligation is ₹10 crore or more must commission an impact assessment for
  each project of ₹1 crore or more, annexed to its annual CSR report. Look for every one: in the CSR
  annexure, on the foundation's site, on the implementing partner's site. `impact_assessment_done` true
  with no report found is a gap naming the project.
- For each programme, look for its evaluation, baseline study and programme report.
- Read each one you can reach and cite pages.

### 10. People — `contact`
Publicly disclosed CSR roles: `name`, `role`, `kind`; a shared mailbox (`csr@`, `grants@`) with
`is_role_mailbox`. Never an individual's address or a phone number.

## Access state

A source that will not open is a gap, and its kind matters, because only one licenses an absence:
- **readable** — real text;
- **scanned** — a PDF with no text layer: the content is unread, never report an absence from it;
- **soft-404** — HTTP 200 but boilerplate: treat as not found;
- **archived** — read from web.archive.org because the live site refused: say so, it may be stale.

Say which in the gap's `detail`.

## Classifying a spend line: domain and theme

Every domain and theme on a line is an **inference**.
- Classify by the project name and the named partner, not the Schedule VII sector filed; filings
  misfile often. The filed sector is saved as filed in `sector` either way.
- A **domain**, always: livelihoods, health, education, environment, others (relief, sports,
  administration, unlabelled and multi-sector lines).
- A **theme** only as far as the evidence goes: a sub-theme when the project or partner points to one, a
  theme when only the broad area is clear, none otherwise.
- `classified_by` (`filed_sector` only where unambiguous, `project_name`, `partner`, `report`) and a
  one-line `classification_note` quoting the evidence. A `programme_spend` is `classified_by = 'report'`.

## What this skill does not do

No fit, no score, no ranking, no comparison, no catalog write. It produces every field of the brief,
cited or gapped, and stops.
