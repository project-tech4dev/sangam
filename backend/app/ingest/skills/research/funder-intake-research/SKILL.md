---
name: funder-intake-research
description: Use when the organisation you are researching GIVES money — a company, corporate foundation, trust or grantmaker — and read it first, because it is your contract — every field of the funder brief, section by section, with the concept and field it is saved as; each one ends as a finding or a gap. It also sets the source order (statutory filings, the funder's own publications, recipients' records, staff workbooks last), how to build the programme tree with its money, how to find the impact assessments and reports behind the work, and how to classify spend lines. Raw field-value-source only; no verdicts. Not for an NGO that receives money — that is ngo-credential-research.
---

# What you pull for a funder

Your save is the source of the funder's public brief and of the catalog. **Every field in the tables
below ends as one of two things:**
- a **finding** — the sentence that states it, its URL, and the `page` ("p.33", "pp.33-35",
  "Annexure 4", "CSR page, Programmes tab"); or
- a **gap** — `{concept, field, fiscal_year, reason, detail}`: `not_stated` when a source you read is
  silent (name it), `blocked` when you could not read it (name the page or registry), `not_reached`
  when the run stopped first (name what was left unread).

`save_research` refuses a save that leaves a concept, an asked year or an identity field with neither.

Marks in the tables:
- **★** — Sangam has no column yet. Save it in `unplaced` as `{field, value, evidence, source_url, page}`,
  using the field name given. It still appears in the brief. One you looked for and did not find is a gap
  with its section's concept and the ★ name as `field`: `{concept: "identity", field: "founded", reason: "not_stated", …}`.
- **⚙** — filled by code from what you save. You do not pull it.

## The brief at a glance

| Section | Fields |
|---|---|
| 1. Identity | name, other names, type, parent and its CIN, CIN, Section 135, website, founded and legal form★, registered office★, intake posture (intake mode, funds external, duration, grant band) |
| 2. CSR by year | every statutory figure, impact assessment done |
| 3. Spend lines | per FY per project: name, filed sector → Schedule VII clause⚙, domain / theme, state / district, partner and CSR-1, implementation mode, outlay, amount, project count, ongoing |
| 4. Programme tree | theme → programme → component → phase, with its own figure per component per FY, documents |
| 5. Footprint and priorities | per FY states → districts as printed, by programme; stated priority places with notes |
| 6. Partners | per FY: name as printed, kind, CSR-1, programme, project, amount, dates, status, Sangam link⚙ |
| 7. Reach | metrics: value, target, unit, period, stage, method, place, programme |
| 8. Eligibility and open calls | statutory restatement, own bar, disqualifiers verbatim; document checklist★; each open call's band, deadline, places, rules |
| 9. People | public CSR roles and role mailboxes; count of non-public ones⚙ |
| 10. Documents | title, type, period, summary, original link, archived copy⚙, pages used, facts drawn⚙ |
| 11. Themes | themes / sub-themes, populations, lenses, SDGs⚙, each with its note |

## 1. Identity — `identity`, one finding per source

| Field | Saved as | How |
|---|---|---|
| name | `identity.name` | As the strongest source writes it. Name the exact body that **receives applications**: many companies route CSR through a foundation, and the policy names the foundation. |
| other names | `identity.aliases` | Every spelling it files or trades under, the filings' included. |
| type | `identity.funder_type` | `corporate_csr`, `corporate_foundation`, `private_foundation`, `family_trust`, `family_trust_network`, `other`. |
| parent, and the parent's CIN | `identity.parent_name`; the CIN in the evidence | The Section 135 filer is often the parent. Never merge them; never put the parent's CIN on the foundation. |
| CIN | `identity.cin` | A company only; a trust has none. Never guessed. |
| Section 135 | `identity.section_135_bound` | |
| website | `identity.website` | |
| founded | ★ `founded` | The year, as printed. |
| legal form | ★ `legal_form` | As printed: "Public Charitable Trust", "Section 8 Company". |
| registered office | ★ `registered_office` | Address, state, district. |
| intake mode | `identity.intake_mode` | `open`, `rolling`, `invitation_only`, `rfp_only`, `closed`, `unknown`, as it says so. "No stated route" is a real finding — never infer one from a contact-us page. |
| intake route, and whether it is live | ★ `intake_route` | Portal URL, email address or RFP process; the date you checked, and what you saw: does the portal load, is the form years old, does the page still exist. A readable but stale form is said here, not as an access state. |
| funds external | `identity.funds_external` | `true` for a grantmaker (gives to NGOs), `false` for an implementer (runs the work itself and solicits corporate payers), null when it does not say. Closed or informational only is `intake_mode` `closed`. A "Partner with us" page can mean any of these: quote what decided it. |
| duration | `identity.typical_duration_months` | Hard numbers only. |
| grant band | `identity.grant_size_min`, `grant_size_max` | A rupee figure as printed, with its unit. Nothing published is a gap — never estimate from sector norms. |
| co-funding share | ★ `co_funding_share` | "Covers up to 90% of project cost". |
| live call or historical disclosure | ★ `call_or_disclosure` | Many "CSR information" pages describe money already spent, not an open call: say which. A line naming its implementing agency "TBD" is a live, open slot — flag it here, and save the line as `csr_spend` with no partner. It is not an `rfp` unless it has a title and a deadline. |

Stated focus (themes, populations, lenses) is section 11.

## 2. CSR by year — `csr_year`, one per fiscal year asked

| Field | Saved as |
|---|---|
| Section 135 applicable | `section_135_applicable` |
| average net profit | `average_net_profit` |
| prescribed CSR (2%) | `prescribed_csr` |
| spent on projects | `spent_on_projects` |
| administrative overheads | `admin_overheads` |
| impact-assessment cost | `impact_assessment_cost` |
| total spent | `total_spent` |
| unspent, transferred | `unspent_transferred` |
| excess spent | `excess_spent` |
| local-area spent | `local_area_spent` |
| impact assessment done | `impact_assessment_done` |

- Take the company-level figures **once per company-year**: filing exports repeat them on every project line.
- Obligation, budget, spend, overhead and unspent are not interchangeable.
- A year with no filing read is a gap with that `fiscal_year`.

## 3. Spend lines — `csr_spend`, per fiscal year per project

| Field | Saved as | How |
|---|---|---|
| project name | `project_name` | An aggregate line has none, and a `project_count`. Never divide it. |
| filed sector | `sector` | As filed, whatever your classification says. Its Schedule VII clause is ⚙. |
| domain / theme | `domain`, `theme`, `classified_by`, `classification_note` | See "Classifying a spend line" below. |
| state / district | `state`, `district` | The project's state, not the filer's. A district always travels with its state. |
| partner and CSR-1 | `partner_name`, `partner_csr1` | As printed. |
| implementation mode | `implementation_mode` | Direct or through an agency. |
| outlay, amount | `outlay`, `amount` | As printed, with the unit. |
| project count | `project_count` | Aggregate lines only. |
| ongoing | `is_ongoing` | |
| programme | `program_name` | When the line belongs to a programme in section 4. |

## 4. Programme tree — `program` and `programme_spend`

**Programmes are a tree, and money hangs on the tree.**

| Field | Saved as | How |
|---|---|---|
| each level: theme, programme, component, phase, project | `program` with `name`, `kind`, `parent_name` | `kind` is `theme`, `programme`, `phase` or `project`; `parent_name` points one level up. A theme is the funder's own area heading ("Livelihoods"); a programme sits under it; a component is kind `programme` with its programme as parent. |
| description, status, start / end | `description`, `status`, `start_date`, `end_date` | |
| its own figure per component per FY | `programme_spend` with `program_name`, `fiscal_year`, `amount` | Name the exact component. Never spread across spend lines, never added to them. `classified_by = 'report'`. |
| themes | `program.themes` with `tag_note` | From its own description, never its name. Or a gap `{concept: "program", field: "themes", reason: "not_stated"}` naming the programme and the source. |
| places | `footprint` rows with its `program_name` | Section 5. |
| documents | `document` | Section 10. |

- "SLP – Rural Livelihoods ₹198.29 crore, FY2024-25" is `program` "Rural Livelihoods" under "Sustainable
  Livelihood Programme", **and** its `programme_spend`.
- Numbered missions are separate programmes: Mission 1 Million, Mission 2 Million and Mission 4 Million
  are three, each with its own dates.

## 5. Footprint and priorities — `footprint`, `stated_geography`

| Field | Saved as | How |
|---|---|---|
| where the work ran, per FY, by programme | `footprint` with `state`, `district`, `fiscal_year`, `program_name`, `name_as_printed` | Districts, blocks or work centres exactly as listed — a state alone is not an answer when finer is published. "Barpeta and Kamrup districts of Assam" is two rows. Never a district from a city. |
| where it says it prioritises | `stated_geography` with `state`, `district`, `note` | A priority is not a footprint. |

A finer list behind a login is a `blocked` gap that says so, not a state-level answer.

## 6. Partners — `partner`, per fiscal year

| Field | Saved as | How |
|---|---|---|
| name as printed | `partner_name` | And `partner_canonical` when a source gives the full legal name. |
| kind | `partner_kind` | `ngo`, `foundation`, `university`, `research`, `government`, `armed_forces`, `hospital`, `network`, `company`, `other`. |
| CSR-1 | `partner_csr1` | |
| programme, project | `program_name`, `project_name` | |
| amount | `amount`, `outlay` | As printed, with the unit. `null` means not public, never zero. |
| dates | `start_date`, `end_date` | |
| status | `relationship_status` | `active`, `concluded` ("Closed", "Completed"), `unconfirmed`, `dormant`. |

- A multi-year grant is ONE finding in the fiscal year it started, with both dates and its whole amount.
- A range of years from a staff sheet ("2021–2024", "2022-2025 (Closed)") is one finding on its **first**
  fiscal year, `start_date` and `end_date` at the range's fiscal-year bounds (`2021–2024` is FY2021-22,
  2021-04-01 to 2024-03-31), **no amount** — the amount stays in the quoted evidence, because it covers
  the whole range.
- No closing year ("Post 2022", "Ongoing"): no finding; name it in your summary.
- A named partner is not proof that money changed hands; say what the source shows.

## 7. Reach — `metric`

| Field | Saved as |
|---|---|
| name, value, target, unit | `name`, `value`, `target`, `unit` |
| period, stage, method | `period`, `stage`, `method` |
| self-reported | `is_self_reported` |
| place | `state`, `district` |
| programme | `program_name` |

A target only when the source states one, on the same metric as its achievement. "23,686 villages across
15 states" is a `metric` (23686, villages) **and**, where the states are named, `footprint` rows. A count
with no names is the metric alone.

## 8. Eligibility and open calls — `eligibility_guideline`, `rfp`

| Field | Saved as | How |
|---|---|---|
| statutory restatement | `eligibility_guideline.statutory_restatement` | Rule 4 of the CSR Policy Rules copied into the policy (12A/80G/CSR-1, three years' track record). Verbatim, one finding per page. |
| own bar | `eligibility_guideline.own_bar` | Anything beyond the statutory minimum, in the funder's words. Kept apart from the restatement: a funder that only restates the law has set no bar of its own. |
| disqualifiers | `eligibility_guideline.disqualifiers` | Thresholds that reject outright: minimum revenue, minimum years running, board size, political or religious bars, donor concentration, employee floors. Rejections, not credentials. |
| none stated | `eligibility_guideline.not_stated` | With the URL of the page read. |
| document checklist | ★ `document_checklist` | Verbatim, item by item. "Lists 32 items" is the right precision; list them. |
| each open call | `rfp` with `title`, `url`, `status`, `deadline` | Only a call with a title and a deadline. A programme page, themes page or past-projects list is not a call. |
| its band | `amount_min`, `amount_max` | As printed, with the unit. |
| its places | `state`, `district` | |
| its rules | `eligibility` | Each rule on its own line. A call's rules are the call's; the same sentence may also be the funder's standing bar, and recording it in both is correct. |

A closed or expired call is still recorded, marked closed.

## 9. People — `contact`

Publicly disclosed CSR roles: `name`, `role`, `kind`; a shared mailbox (`csr@`, `grants@`) with
`is_role_mailbox`. Never an individual's address or a phone number. How many contacts are withheld is ⚙.

## 10. Documents — `document`, one per source you used

| Field | Saved as | How |
|---|---|---|
| title, type, period | `title`, `doc_type`, `as_of` | `as_of` is the period it describes. |
| summary | `summary` | Two to four sentences on the whole document — its programmes, years, figures and places — not only the line you quoted. |
| original link | `source_url` | |
| pages used | `page` on each finding citing it | |
| archived copy, facts drawn | ⚙ | |

**Find the documents behind the work.**
- A company whose average CSR obligation is ₹10 crore or more must commission an impact assessment for
  each project of ₹1 crore or more, annexed to its annual CSR report. Look for every one: in the CSR
  annexure, on the foundation's site, on the implementing partner's site. `impact_assessment_done` true
  with no report found is a gap naming the project.
- For each programme, look for its evaluation, baseline study and programme report.
- Read each one you can reach and cite pages.

## 11. Themes — `identity.themes` / `populations` / `lenses`

The funder's **stated** focus — a CSR policy's focus areas, a foundation's themes page — with a `tag_note`
quoting the page. At most three themes, main work first. What it spent on is the spend lines'
classification, not a tag. SDGs are ⚙, derived from the themes.

## Rules for every value

- **Amounts and years follow your prompt's Money and Fiscal years rules**: an amount as printed with its
  unit (`inr`, `lakh`, `crore`), never converted; a year as `FY2024-25`.
- **Every value carries its exact source, including "not stated".** A URL or a staff workbook's cell
  marker. "Not stated" with a URL means the page was read and was silent; a field you never looked for is
  `not_reached`, not `not_stated`.
- **Never cite an aggregator, a CSR tracker, LinkedIn or news coverage for a fact.** They point you to
  the funder's page; only the funder's domain, a primary document it hosts, a filing or a recipient's own
  record is the source.
- **Pull raw.** Field, value, source. No summary verdict, no comparison, no "strong fit".

## Where to look, in this order

The order is strength of evidence for money. Your STEP 1 confirmation search always comes first, and
**`read_source_rows` is called after every web read** — its first call closes the web tools.

1. **Statutory CSR filings for the corporate entity**, under the filer's registered name, then the
   foundation's. The filer carries the Section 135 obligation.
2. **The funder's own publications** — annual reports and the CSR annexure, CSR policy, annual action
   plan, impact-assessment reports, BRSR, the foundation's programme pages.
3. **Recipient-side records** — partners' annual reports and grantee pages — for amounts per partner,
   which funders rarely publish.
4. **Staff workbooks, last** — the files picked on the sources card, read with `read_source_rows`.
   Their layouts and units are in your prompt ("The staff sheets").

**When a source will not open,** try the Internet Archive copy of the same URL and label it `archived`.
If a primary legal source (mca.gov.in, csr.gov.in, indiacode.nic.in) is unreachable, say so: a statutory
claim corroborated from commentary instead is weaker, and labelled so.

## Access state

A source that will not open is a gap, and its kind matters, because only one licenses an absence:
- **readable** — real text;
- **scanned** — a PDF with no text layer: the content is unread, never report an absence from it;
- **soft-404** — HTTP 200 but boilerplate: treat as not found;
- **archived** — read from web.archive.org because the live site refused: it may be stale.

Say which in the gap's `detail`.

## Classifying a spend line: domain and theme

Every domain and theme on a line is an **inference**.
- Classify by the project name and the named partner, not the Schedule VII sector filed; filings
  misfile often.
- A **domain**, always: livelihoods, health, education, **environment** (sustainability, conservation,
  animal welfare that is not a livelihood programme), **others** (relief, sports, administration,
  unlabelled lines, lines listing several sectors).
- A **theme** only as far as the evidence goes: a sub-theme when the project or partner points to one, a
  theme when only the broad area is clear, none otherwise.
- `classified_by` (`filed_sector` only where unambiguous, `project_name`, `partner`, `report`) and a
  one-line `classification_note` quoting the evidence.

## What this skill does not do

No fit, no score, no ranking, no comparison, no catalog write. It produces every field of the brief,
cited or gapped, and stops.
