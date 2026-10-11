---
name: ngo-credential-research
description: Use when someone names one or more NGOs, CSOs, trusts or societies — organisations that RECEIVE money — and wants their actual legal and operational standing rather than their sector and mission. Sets the order to read sources in (the CSO's own documents, readable registries, funders' pages and filings, staff datasets via read_source_rows, earlier research and aggregators last) and what to pull — statutory registrations as statuses (applied, registered, check_blocked), three years of audited financials with foreign contribution received and unspent, existing funders with amounts, programmes and metrics, governance and staff, name variants, website. Lists exactly which documents to request from the CSO when no public source can confirm them. Raw field-value-source only; no verdicts, no scoring. Not for a company, corporate foundation or CSR arm — use funder-intake-research. Not for a single fact already in the catalog — funder_dossier with entity_kind org answers that.
---

# What we want pulled for an NGO

Put this in each researcher's task description: where to look, in which order, what to pull and
how to label it. No organisation is special-cased here.

## The rules that hold for every value

**Every value carries its exact source URL, including "not stated".** A field with no findable URL
is not reported as a fact.

**Every value carries a source type and an evidence tier.** Source type: `org_document`,
`registry`, `funder`, `staff_dataset`, `prior_research`, `aggregator`. Tier: `evidenced` only when
the document itself states the fact — a certificate, an audited statement, a dated return, a
registry record. "We are 12A and 80G registered" on a web page, with no number and no certificate,
is `claimed`. Never upgrade one to the other.

**A weaker source never replaces a stronger one.** Strongest first: a registry or a staff
member's manual check, the CSO's own documents, a funder's page, a staff dataset, earlier
research, an aggregator. Where two disagree, save both, each with its source; the catalog keeps
the stronger and reports the other under `conflicts`.

**A blank government search form is not a source.** It renders identically for every
organisation and proves nothing about this one.

**Adverse findings hide in audited statements, not on homepages.** A suspended FCRA, a cancelled
12AB, a show-cause notice: read the notes and credential sections of the audited accounts. A
cancellation under appeal is still a cancellation; record the appeal as its own value.

**Pull raw.** Field, value, source URL, source type, tier. No eligibility verdict, no summary, no
comparison table.

## Where to look, in this order

1. **The CSO's own documents** — uploads in the Doc Vault first (a `vault-reader` reads them, when the
   request names them; what they say stays private and is shown on Review), then those on its site: trust
   deed or registration certificate, PAN card, 12AB/80G orders (Forms 10AC/10AD) or a Form 10AB
   acknowledgement, CSR-1 approval, FCRA certificate, FCRA returns (FC-4), audited accounts,
   annual reports, policies.
2. **Registries, where a machine may read them.** Behind a CAPTCHA, a sign-in or a network
   filter, do not try to get past it: the registration is `check_blocked`, never `not_found`, never
   assumed valid. Name the registry so a staff member can check it by hand; the supervisor records
   that check with `record_registry_check`.
3. **Funders' own pages naming the CSO as a grantee**, and company CSR filings naming it as the
   agency that did the work. Match on name **and** district or state: short names collide.
4. **Staff datasets**, picked on the sources card (`choose_sources`), then read
   through `read_source_rows` with those document ids and the organisation's name — **last of the
   reads**, because the first call closes the web tools. Each row carries a
   `[source:<document>#<sheet>!<cell>]` marker; quote the line with the marker of the cell that
   holds the fact, and cite the dataset's `source_url` without fetching it. The profile sheet is
   the CSO's own account, so every value from it is `claimed`; a registration number there is a
   lead to the certificate, not the certificate. The funder sheets give its funders by year.
5. **Earlier research and aggregators, as leads only.** The team's earlier research (the
   org-grant-intelligence dossier, read first as a map of leads, its cited links then re-read) and
   the registered aggregators (Give.do, GuideStar India) are readable on their named paths only.
   Every value is `claimed` (`prior_research` or `aggregator`), and none replaces the CSO's
   own document. An aggregator listing a registration the CSO's files show only as an application
   is a conflict to report, not a registration.

## What to pull

**Statutory status as a status, not a yes or a no.**
- A Form 10AB acknowledgement is `applied`, never `registered`; its number is the
  `application_ref`, and `id_value` stays empty.
- `not_found` means a working source was read and does not list it. A registry nobody could read
  is `check_blocked`.
- When the FCRA portal cannot be read, take the number from the CSO's own FCRA returns and leave
  its validity `check_blocked`.
- A Section 8 company: say so. Some funders exempt them from 12A/80G, so whether the gate blocks
  depends on the funder.
- CSR-1: the registration number, and whether the filing names the certifying professional.
- DARPAN: the ID, and the blacklist status where a lookup is possible. Copying the ID is not
  checking it.

**Financials by year, from the audited statements** — three years where they exist: income,
expenditure, surplus or deficit; programme and non-programme spend where stated; foreign
contribution received and left unspent at year end, from the FCRA returns. Quote any internal
inconsistency in the audit verbatim in `notes`. Name the years covered and the years missing.

**Existing funders, with amounts**, from grant lines in the audited accounts, donors in the FCRA
returns, funders' grantee pages, and CSR filings and the staff funder sheets. Each is a `partner`
finding: `funder_name` as printed, this CSO as `partner_name`, the fiscal year, and the amount as
printed with its unit. It lands on that funder's partner line; a funder Sangam does not hold is
held for a person.

**Programmes and metrics** from the annual reports, each with its year, `claimed`. A target only
when the report states one. Tag each programme with the themes, populations and lenses its own
description supports, with a `tag_note` quoting it; tag `org_identity` only with a focus the
organisation states for itself.

**Governance and capacity:**
- the board, as `office_bearer` contacts — names and roles only, never a personal email or phone;
- the staff count, with a note saying what was counted and where; permanent staff, not
  volunteers or contractors, where the source says which;
- each policy as a `policy` document: child safeguarding, HR, finance and procurement, grievance,
  an organogram. Record which are published and which are absent; never infer one.

Where sources give different counts, record every count with its source. Do not pick one.

**Name variants** as aliases: every spelling any source used, the filings' included.

**Website, and a short description in its own words.**

## Documents to request from the CSO

When no public source confirms a credential, ask the CSO to upload exactly these to the Doc Vault:

- the registration certificate or trust deed;
- the PAN card;
- the 12AB and 80G orders (Forms 10AC/10AD), or the Form 10AB acknowledgement;
- the CSR-1 approval;
- the FCRA certificate and its latest renewal;
- three years of audited accounts;
- three years of FCRA returns;
- the latest annual report.

## Two things to confirm first

**It is the right organisation.** Namesakes are common; confirm against its own materials before
any budget is spent.

**Where it actually works.** Registered in one state and working mainly in another is common;
check from its own materials, not a prior list's assumption.

## What this skill does not do

No eligibility verdict, no score, no ranking, no comparison. It does not write to the catalog and
does not record a manual check. It produces cited values with their source types and tiers, and
stops.
