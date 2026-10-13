---
name: ngo-credential-research
description: Use when the organisation you are researching RECEIVES money — an NGO, CSO, trust or society — and read it first, because it is your contract — every field of the organisation brief, section by section, with the concept and field it is saved as; each one ends as a finding or a gap. It also sets the source order (the CSO's own documents, readable registries, funders' pages and filings, staff workbooks last, earlier research and aggregators as leads), how to record a registration as a status, how to build the programme tree, how to find the evaluations and reports behind the work, and which documents to request from the CSO. Raw field-value-source only; no verdicts. Not for a company, foundation or CSR arm — that is funder-intake-research.
---

# What you pull for an NGO

Your save is the source of the organisation's public brief and of the catalog. **Every field in the
tables below ends as one of two things:**
- a **finding** — the sentence that states it, its URL, the `page` ("p.12", "Annexure 2", "About page"),
  its `source_type` and `evidence_tier`; or
- a **gap** — `{concept, field, fiscal_year, reason, detail}`: `not_stated` when a source you read is
  silent (name it), `blocked` when you could not read it (name the page or registry), `not_reached` when
  the run stopped first (name what was left unread).

`save_research` refuses a save that leaves a concept, an asked year or an identity field with neither.

Marks in the tables:
- **★** — Sangam has no column yet. Save it in `unplaced` as `{field, value, evidence, source_url, page}`,
  using the field name given. It still appears in the brief. One you looked for and did not find is a gap
  with its section's concept and the ★ name as `field`: `{concept: "org_identity", field: "parent_or_network", reason: "not_stated", …}`.
- **⚙** — filled by code from what you save. You do not pull it.

## Two things to confirm first

- **It is the right organisation.** Namesakes are common; confirm against its own materials before
  anything else.
- **Where it actually works.** Registered in one state and working mainly in another is common; check its
  own materials, not a prior list's assumption.

## The brief at a glance

| Section | Fields |
|---|---|
| 1. Identity | legal name, other names, kind, legal form, registration date, registered office (state, district, address★), website, own description, staff count and what was counted, network or parent★ |
| 2. Registrations | 12A, 80G, FCRA, PAN, Darpan, CIN, CSR-1, registration no.: number or application ref, status, valid from / until, how checked, evidence tier |
| 3. Where it works | state → districts, role (registered / operates / funds), note, programme★, source |
| 4. Programmes | theme → programme → phase → project: kind, description, status, start / end, places★, metrics (value, target, unit, period, stage, method, place), tags with their note, documents |
| 5. Money in | per funder per FY: amount, project, dates, status, evidence tier, link to funder⚙; per FY: income, programme / other spend, foreign contribution and unspent, audited |
| 6. People | public contacts and role mailboxes; count of non-public ones⚙ |
| 7. Documents | title, type, period, summary, original link, archived copy⚙, pages used, facts drawn⚙ |
| 8. Themes | themes / sub-themes, populations, lenses, SDGs⚙, each with its note |

## 1. Identity — `org_identity`

| Field | Saved as | How |
|---|---|---|
| legal name | `org_identity.name` | As registered. |
| other names | `org_identity.aliases` | Every spelling any source used, the filings' included. |
| kind | `org_identity.org_kind` | |
| legal form | `org_identity.legal_form` | As printed: "Public Charitable Trust", "Section 8 Company". A Section 8 company: say so — some funders exempt them from 12A/80G. |
| registration date | `org_identity.registration_date` | |
| registered office: state, district | `org_location` with `role` `registered` | |
| registered office: address | ★ `registered_address` | The street address as printed. |
| website | `org_identity.website` | |
| own description | `org_identity.description` | Short, in its own words. |
| staff count, and what was counted | `org_identity.staff_count`, `staff_count_note` | Two pages giving different counts are two findings, each with a note saying what was counted ("45 staff"; "60 including volunteers") — never pick one. Permanent staff is the count we want first. |
| network or parent | ★ `parent_or_network` | Named as printed; never created or merged. |

## 2. Registrations — `org_identifier`, one per registration

| Field | Saved as | How |
|---|---|---|
| which registration | `id_type` | `12a`, `80g`, `fcra`, `pan`, `darpan`, `cin`, `csr1`, `reg_no` (the registration number). |
| number | `id_value` | Never guessed. "PAN Card AAETS7554F" — the line as printed is the evidence. A registration the CSO only claims, with no number, is a finding with `status` `registered`, `id_value` empty, `claimed` — one per registration — plus a gap `{concept: "org_identifier", field: "id_value", …}` naming it. |
| application ref | `application_ref` | A Form 10AB acknowledgement is `applied`, never `registered`: its number here, `id_value` empty. |
| status | `status` | `registered`, `applied`, `provisional`, `expired`, `suspended`, `cancelled`, `surrendered`, `not_available`, `not_found` (a working source was read and does not list it), `check_blocked` (a registry nobody could read — never valid, never `not_found`). A cancellation under appeal is still `cancelled`; the appeal is in `notes`. |
| valid from / until | `valid_from`, `valid_until` | |
| how checked | `check_method` | `document` (the CSO's own), `registry` or `aggregator`. With the FCRA portal unreadable, take the number from the FCRA returns and leave the status `check_blocked`. Darpan: the ID and the blacklist status where a lookup is possible — copying the ID is not checking it. CSR-1: the number, and whether the filing names the certifying professional (in `notes`). |
| evidence tier | `evidence_tier` | `evidenced` only from a certificate, order, return or registry record; "we are 12A and 80G registered" on a web page is `claimed`. |

## 3. Where it works — `org_location`

| Field | Saved as | How |
|---|---|---|
| state → districts | `state`, `district` | A district always travels with its state. Never a district from a city or a programme name. |
| role | `role` | `registered`, `operates`, `funds`. |
| note | `note` | |
| programme | ★ `programme_places` | `{programme, places}`, alongside the `org_location` rows. |
| source | `source_type`, `evidence_tier`, the URL | |

## 4. Programmes — `program`, `metric`

**Programmes are a tree**: theme → programme → phase → project.

| Field | Saved as | How |
|---|---|---|
| each level | `program` with `name`, `kind`, `parent_name` | `parent_name` points one level up. |
| description, status, start / end | `description`, `status`, `start_date`, `end_date` | |
| places | ★ `programme_places`, and an `org_location` per place | |
| metrics | `metric` with `name`, `value`, `target`, `unit`, `period`, `stage`, `method`, `is_self_reported`, `program_name` | A target only when the report states one, on the same metric as its achievement. Each with its year; self-reported is `claimed`. |
| metric place | `metric.state`, `district` | |
| tags with their note | `program.themes` / `populations` / `lenses`, `tag_note` | From its own description, never its name. Or a gap `{concept: "program", field: "themes", reason: "not_stated"}` naming the programme and the source. |
| documents | `document` | Section 7. |

"Reached 12,400 women in 3 districts of Assam since 2009" is a `metric`, three `org_location` rows and a
date.

## 5. Money in — `partner`, `org_financials`

**Per funder per fiscal year — `partner`**, from grant lines in the audited accounts, donors in the FCRA
returns, funders' grantee pages, CSR filings and the staff funder sheets:

| Field | Saved as | How |
|---|---|---|
| funder | `funder_name` | As printed. This CSO is `partner_name`. A funder Sangam does not hold is held for a person, never created. |
| amount | `amount` | As printed, with its unit. `null` means not public, never zero. |
| project | `project_name`, `program_name` | |
| dates | `fiscal_year`, `start_date`, `end_date` | A multi-year grant is ONE finding in the year it started. |
| status | `relationship_status` | |
| evidence tier | `source_type`, `evidence_tier` | |
| link to funder | ⚙ | |

**Per fiscal year — `org_financials`**, from the audited statements, three years where they exist:

| Field | Saved as | How |
|---|---|---|
| income | `total_income` | |
| programme / other spend | `program_spend`, `non_program_spend` | Only where the accounts split it; never derived from the total. |
| total expenditure, surplus or deficit | ★ `expenditure`, `surplus` | As printed, beside the split when both are given. |
| foreign contribution and unspent | `foreign_contribution`, `foreign_unspent` | From the FCRA return. |
| audited | `is_audited` | |
| inconsistencies | `notes` | Quoted verbatim from the audit. |

A year with no accounts read is a gap with that `fiscal_year`. **Adverse findings hide in audited
statements**, not on homepages — a suspended FCRA, a cancelled 12AB, a show-cause notice: read the notes
and credential sections.

## 6. People — `contact`

The board as `office_bearer` contacts — names and roles only; a shared mailbox with `is_role_mailbox`.
Never a personal email or phone. How many contacts are withheld is ⚙.

## 7. Documents — `document`, one per source you used

| Field | Saved as | How |
|---|---|---|
| title, type, period | `title`, `doc_type`, `as_of` | |
| summary | `summary` | Two to four sentences on what the whole document covers. |
| original link | `source_url` | |
| pages used | `page` on each finding citing it | |
| archived copy, facts drawn | ⚙ | |
| policies | `document` with `doc_type` `policy` | Child safeguarding, HR, finance and procurement, grievance, an organogram. An absent one is a gap `{concept: "document", field: "grievance policy", reason: "not_stated", detail: <sources read>}`, never inferred. |
| governance | ★ `governance` | Board size, published bios, conflict-of-interest policy. |
| capacity | ★ `capacity` | Similar work evidenced by MoU or completion certificate, donor concentration. |

**Find the documents behind the work**: for each programme, its evaluation, baseline study and programme
report — published by the CSO, its funders or the evaluator. Read each you can reach and cite pages.

## 8. Themes — `org_identity.themes` / `populations` / `lenses`

Only a focus the organisation states for itself, each with a `tag_note` quoting it. At most three themes,
main work first. SDGs are ⚙, derived from the themes.

## Rules for every value

- **Amounts and years follow your prompt's Money and Fiscal years rules**: an amount as printed with its
  unit (`inr`, `lakh`, `crore`), never converted; a year as `FY2024-25`.
- **Every value carries its exact source, including "not stated".**
- **Source type and tier on everything.** `source_type`: `org_document`, `registry`, `funder`,
  `staff_dataset`, `prior_research`, `aggregator`. `evidence_tier`: `evidenced` only when a document states
  the fact as a record — a certificate, an order, an acknowledgement, audited accounts, a return, a
  registry entry. A sentence on the CSO's website is `org_document` and `claimed`. Never upgrade one to
  the other.
- **A weaker source never replaces a stronger one.** Strongest first: a registry, the CSO's own documents,
  a funder's page, a staff dataset, earlier research, an aggregator. Where two disagree, save both.
- **A blank government search form is not a source.** It renders the same for every organisation.
- **Pull raw.** Field, value, source, type, tier. No verdict, no comparison.

## Where to look, in this order

1. **The CSO's own documents** — on its site: trust deed or registration certificate, PAN card, 12AB/80G
   orders (Forms 10AC/10AD) or a Form 10AB acknowledgement, CSR-1 approval, FCRA certificate and returns
   (FC-4), audited accounts, annual reports, policies.
2. **Registries, where a machine may read them.** Behind a CAPTCHA, a sign-in or a network filter, do not
   try to get past it: the registration is `check_blocked`. Name the registry so staff can check it.
3. **Funders' pages naming the CSO as a grantee**, and CSR filings naming it as the implementing agency.
   Match on name **and** district or state: short names collide.
4. **Staff workbooks, last** — read with `read_source_rows`; the first call closes the web tools. The
   profile sheet is the CSO's own account, so `claimed`; a registration number there is a lead to the
   certificate, not the certificate.
5. **Earlier research and aggregators, as leads only** — every value `claimed`, none replacing the CSO's
   own document. An aggregator listing a registration the CSO's files show only as an application is a
   conflict to report, not a registration.

## Documents to request from the CSO

When no public source confirms a credential, name these in your summary for staff to request:
the registration certificate or trust deed; the PAN card; the 12AB and 80G orders (Forms 10AC/10AD) or
the Form 10AB acknowledgement; the CSR-1 approval; the FCRA certificate and its latest renewal; three
years of audited accounts; three years of FCRA returns; the latest annual report.

## What this skill does not do

No eligibility verdict, no score, no ranking, no comparison, no catalog write, no manual check. It
produces every field of the brief, cited or gapped, and stops.
