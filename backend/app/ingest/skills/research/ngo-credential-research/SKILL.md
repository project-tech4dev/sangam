---
name: ngo-credential-research
description: Use when the organisation you are researching RECEIVES money — an NGO, CSO, trust or society — and read it first, because it is your contract — every field of the organisation brief, section by section, with the concept and field it is saved as; each one ends as a finding or a gap. It also sets the source order (the CSO's own documents, readable registries, funders' pages and filings, staff workbooks last, earlier research and aggregators as leads), how to record a registration as a status, how to build the programme tree, how to find the evaluations and reports behind the work, and which documents to request from the CSO. Raw field-value-source only; no verdicts. Not for a company, foundation or CSR arm — that is funder-intake-research.
---

# What you pull for an NGO

Your save is the source of the organisation's public brief and of the catalog. The brief is laid out
field by field, in the sections below, and **every field shows an answer**: a value, "not stated
(source)", "could not read (source)", or "no field yet". So:

**Every field below gets an answer.** For each one, either
- a **finding** — the sentence that states it, its URL, the `page` ("p.12", "Annexure 2", "About
  page"), its `source_type` and `evidence_tier`; or
- a **gap** — `{concept, field, fiscal_year, reason, detail}`: `not_stated` when a source you read is
  silent (name it), `blocked` when you could not read it (name the page or registry), `not_reached`
  when the run stopped first (name what was left unread).

`save_research` refuses a save that leaves a concept, an asked year or an identity field with neither,
and names what is missing. A field marked *unplaced* has no column yet: save it in `unplaced`
(`{field, value, evidence, source_url, page}`) so the brief still shows it.

**Extract what you quote.** If an evidence sentence holds a number, a place, a date, a role or another
organisation's name, each is its own finding in the concept it belongs to: "reached 12,400 women in 3
districts of Assam since 2009" is a `metric`, three `org_location` rows and a date. With no concept
for it, it goes in `unplaced`. The save names every number it finds only inside a quote.

**Confirm what Sangam holds.** `research_goals` and `funder_dossier(name, 'org')` show the catalog's
current values. Save a finding for every one you find a source for, even when it agrees.

**Organisations you meet.** Every funder, partner, parent network and sister organisation is named as
printed, as its own finding. Never create or merge one; matching is done later, by code.

## The rules that hold for every value

- **Source type and tier on everything.** `source_type`: `org_document`, `registry`, `funder`,
  `staff_dataset`, `prior_research`, `aggregator`. `evidence_tier`: `evidenced` only when the document
  itself states the fact — a certificate, an audited statement, a dated return, a registry record.
  "We are 12A and 80G registered" on a web page is `claimed`. Never upgrade one to the other.
- **A weaker source never replaces a stronger one.** Where two disagree, save both, each with its source.
- **A blank government search form is not a source.** It renders the same for every organisation.
- **Adverse findings hide in audited statements**, not on homepages: a suspended FCRA, a cancelled
  12AB, a show-cause notice. A cancellation under appeal is still a cancellation.

## Where to look, in this order

1. **The CSO's own documents** — on its site: trust deed or registration certificate, PAN card, 12AB/80G
   orders (Forms 10AC/10AD) or a Form 10AB acknowledgement, CSR-1 approval, FCRA certificate and returns
   (FC-4), audited accounts, annual reports, policies.
2. **Registries, where a machine may read them.** Behind a CAPTCHA, a sign-in or a network filter, do not
   try to get past it: the registration is `check_blocked`. Name the registry so staff can check it.
3. **Funders' pages naming the CSO as a grantee**, and CSR filings naming it as the implementing agency.
   Match on name **and** district or state: short names collide.
4. **Staff workbooks, last** — read with `read_source_rows`; the first call closes the web tools. The
   profile sheet is the CSO's own account, so `claimed`.
5. **Earlier research and aggregators, as leads only** — every value `claimed`, none replacing the CSO's
   own document.

## The brief's sections, and what each field is saved as

### 1. Identity — `org_identity`
| Field | Saved as |
|---|---|
| legal name | `org_identity.name` |
| other names, every spelling a source used | `org_identity.aliases` |
| kind | `org_identity.org_kind` |
| legal form, as printed ("Public Charitable Trust", "Section 8 Company") | `org_identity.legal_form` |
| registration date | `org_identity.registration_date` |
| registered office: state and district | `org_location` with `role` `registered` |
| registered office: street address | *unplaced* (`registered_address`) |
| website | `org_identity.website` |
| its own description | `org_identity.description` |
| staff count, and what was counted | `org_identity.staff_count`, `staff_count_note` |
| network or parent body | *unplaced* (`parent_or_network`) |
| stated focus: themes, populations, lenses | `org_identity.themes` / `populations` / `lenses` with `tag_note` |

Two pages giving different counts are two findings. A Section 8 company: say so in `legal_form`.

### 2. Registrations — `org_identifier`, one per registration
12A, 80G, FCRA, PAN, Darpan, CIN, registration number: `id_type`, `id_value` or `application_ref`,
`status`, `valid_from`, `valid_until`, `check_method`, `notes`.
- A Form 10AB acknowledgement is `applied`, never `registered`: its number in `application_ref`,
  `id_value` empty.
- `not_found` means a working source was read and does not list it; an unreadable registry is
  `check_blocked`, never valid.
- With the FCRA portal unreadable, take the number from the FCRA returns and leave validity
  `check_blocked`.
- Darpan: the ID, and the blacklist status where a lookup is possible. Copying the ID is not checking it.
- Never guess an identifier. "PAN Card AAETS7554F" — the line as printed is the evidence.

### 3. Where it works — `org_location`
State and district, `role` (`registered`, `operates`, `funds`), `note`. A district always travels with
its state. The programme that works there is *unplaced* (`programme_places`) until it has a column.

### 4. Programmes — `program`, `metric`
**Programmes are a tree**: theme → programme → phase → project, each a `program` with `parent_name`,
`kind`, `description`, `status`, `start_date`, `end_date`.
- Every programme carries `themes` with a `tag_note` from its own description, or a gap `{concept:
  "program", field: "themes", reason: "not_stated"}` naming it and the source.
- Its reach: `metric` with `name`, `value`, `target`, `unit`, `period`, `stage`, `method`,
  `is_self_reported`, `program_name`, `state`, `district`. A target only when the report states one,
  on the same metric as its achievement.
- Its places: *unplaced* (`programme_places`), and an `org_location` for each.

### 5. Money in — `partner`, `org_financials`
- Per funder per year, from grant lines in the audited accounts, donors in the FCRA returns, funders'
  grantee pages and CSR filings: a `partner` finding with `funder_name` as printed, this CSO as
  `partner_name`, `fiscal_year`, `amount` with its unit, `project_name`, dates, `relationship_status`.
  A funder Sangam does not hold is held for a person, never created.
- Per year, from the audited statements, three years where they exist: `total_income`, `program_spend`,
  `non_program_spend`, `foreign_contribution`, `foreign_unspent` (from the FCRA return), `is_audited`.
  Quote an internal inconsistency verbatim in `notes`. A year with no accounts read is a gap.

### 6. People — `contact`
The board as `office_bearer` contacts — names and roles only; a shared mailbox with `is_role_mailbox`.
Never a personal email or phone.

### 7. Documents — `document`, one per source you used
`title`, `doc_type`, `as_of`, and `summary`: two to four sentences on what the whole document covers.
- Each policy as a `policy` document: child safeguarding, HR, finance and procurement, grievance, an
  organogram. Which are published and which are absent: absent ones are gaps, never inferred.
- **Find the documents behind the work**: for each programme, its evaluation, baseline study and
  programme report — published by the CSO, its funders or the evaluator. Read each you can reach and cite
  pages.
- Governance beyond names — board size, published bios, conflict-of-interest policy — and capacity
  claims (similar work evidenced by MoU or completion certificate, donor concentration): *unplaced*.

## Documents to request from the CSO

When no public source confirms a credential, name these in your summary for staff to request:
the registration certificate or trust deed; the PAN card; the 12AB and 80G orders (Forms 10AC/10AD) or
the Form 10AB acknowledgement; the CSR-1 approval; the FCRA certificate and its latest renewal; three
years of audited accounts; three years of FCRA returns; the latest annual report.

## What this skill does not do

No eligibility verdict, no score, no ranking, no comparison, no catalog write, no manual check. It
produces every field of the brief, cited or gapped, and stops.
