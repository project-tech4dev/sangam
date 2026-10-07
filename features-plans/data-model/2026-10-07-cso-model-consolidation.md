# CSO model consolidation, evidence tiers, and registry access

Status: proposal for review, with implementation plans in `plans/`. Companion to
`2026-10-07-funder-model-consolidation.md` (PR #99), which must land first: this spec reuses its
`funder_activity` table, its `read_source_rows` tool and its staff-sources bucket.

## Why

A test profile of one CSO (a public charitable trust in Assam) combined five kinds of source:
- Sangam's Darpan seed;
- an internal CSO workbook;
- company CSR filings naming the CSO as the organisation that carried out the work;
- the CSO's own website documents (trust deed, audited accounts, FCRA returns, annual reports,
  policies);
- two aggregators (Give.do and GuideStar India).

About 80% of a 37-field profile could be collected. Only about 46% fits today's tables. The gaps
are structural:

1. **Collected facts have no column.** Website, description, name variants, staff count,
   registration status (applied vs registered), foreign funds left unspent.
2. **Tables have no writer.**
   - `credential_events` holds 0 rows.
   - `grants` is never written on the CSO side.
   - `program_locations` and `grant_locations` hold 0 rows.
3. **Money is in two places.** A grant to a CSO is a `grants` row, and after #99 also a
   `funder_activity` partner line.
4. **Sources disagree, and nothing records which one to trust.**
   - An aggregator's financial figures differed from the audited accounts.
   - An aggregator listed 12A/80G where the CSO's own files were only Form 10AB *applications*.
   - Board and staff counts differed across the CSO's own pages.
5. **Registries are partly unreachable to automation.**
   - Darpan's directory search and blacklist are behind a CAPTCHA and a login.
   - FCRA's portal is network-filtered even from India.
   - MCA's portals refuse automated access.

   Those checks have to be done by a person, or from the CSO's own documents.

## Decisions

| # | Decision |
|---|---|
| C1 | `orgs` gains `website`, `description`, `aliases text[]`, `staff_count` and `staff_count_note`. |
| C2 | `credential_events` folds into `org_identifiers`: a registration's **status** lives on the identifier row. `credential_events` is dropped. |
| C3 | `org_identifiers` gets a surrogate key, so a registration can be recorded before it has a number (e.g. a 12A application with only an acknowledgement number). |
| C4 | `grants` is retired. A grant to a CSO is a `funder_activity` row (`kind = 'partner'`, `partner_org_id` set), as defined in #99. Its dates, status and outcomes move with it. |
| C5 | `program_locations` and `grant_locations` are dropped (0 rows, no writer). |
| C6 | `org_financials` gains `foreign_unspent`. Audit anomalies go verbatim in its existing `notes`. |
| C7 | Every CSO fact Import writes carries a **source type** and an **evidence tier** (D below). A weaker source never overwrites a stronger one; disagreements are kept as recorded conflicts. |
| C8 | Two aggregators join the source registry under a new access rule, **`manual_aggregator`**: low volume, staff-initiated, robots.txt and login walls respected, values always `claimed`. |
| C9 | Registry checks a machine cannot make are recorded as **manual checks**: a staff member checks, uploads the evidence, and the status is stored with that document. |
| C10 | Credentials no public registry can confirm (12AB/80G orders, CSR-1 approval, FCRA renewal) are **requested from the CSO** through the Doc Vault. The skill lists exactly which documents to ask for. |
| C11 | The CSO-matching step (`resolve_org`) gains an alias step, mirroring funders (#99). |
| C12 | `ngo-credential-research` is rewritten. It stays generic: no CSO, funder or person is named in it. |
| C14 | The team's earlier research repo, **org-grant-intelligence** (public, GitHub), is a source for CSOs and funders alike. Its dossiers are read first. Their cited links are **re-fetched** so facts can be evidenced from the primary source. A dossier fact that cannot be re-read is stored as `prior_research`, always `claimed`. |
| C13 | Built **subagent-driven**, like #99: a fresh implementer and a fresh reviewer per task, then a whole-branch review. |

## 1. Evidence tiers (C7)

Two columns on every CSO table Import writes:
- `orgs`
- `org_identifiers`
- `org_financials`
- `org_locations`
- `contacts`
- `programs` (CSO-owned)
- `metrics`

```sql
source_type text CHECK (source_type IN
  ('registry', 'org_document', 'funder', 'staff_dataset', 'manual_check', 'prior_research',
   'aggregator', 'seed')),
evidence text CHECK (evidence IN ('evidenced', 'claimed'))
```

**Precedence**, strongest first: `registry` = `manual_check` > `org_document` > `funder` >
`staff_dataset` > `prior_research` > `aggregator` > `seed`.
- A value from a weaker source **never overwrites** a value from a stronger one.
- A value from a stronger source replaces a weaker one.
- `aggregator` values are always `evidence = 'claimed'`.
- `org_document` is `evidenced` only when the document itself states the fact (a certificate, an
  audited statement, a dated return). A sentence on a web page is `claimed`, as the skill already
  rules.

**Conflicts.** When a weaker or equal source disagrees with a stored value, the writer keeps the
stored value and the promotion report lists the disagreement under `conflicts`, with both values
and both sources. The research record (`entity_research`) keeps every value as found. Nothing
silently picks a winner between equals.

The test case's own disagreements, each recorded as a conflict, not resolved:
- trustee counts (8 / 6 / 5);
- aggregator income vs the audited figure;
- 12A/80G "listed" by an aggregator vs "applied" in the CSO's own files.

## 2. Schema

### `orgs`

```sql
ALTER TABLE orgs
  ADD COLUMN website text,
  ADD COLUMN description text,
  ADD COLUMN aliases text[] NOT NULL DEFAULT '{}',
  ADD COLUMN staff_count integer CHECK (staff_count >= 0),
  ADD COLUMN staff_count_note text,             -- e.g. "20+ full-time professionals (team page)"
  ADD COLUMN source_type text, ADD COLUMN evidence text;
```

### `org_identifiers` (absorbs `credential_events`)

```sql
ALTER TABLE org_identifiers DROP CONSTRAINT org_identifiers_pkey;
ALTER TABLE org_identifiers
  ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ALTER COLUMN id_value DROP NOT NULL,
  ADD COLUMN status text NOT NULL DEFAULT 'registered' CHECK (status IN
    ('applied', 'provisional', 'registered', 'expired', 'suspended', 'cancelled',
     'surrendered', 'not_available', 'not_found', 'check_blocked')),
  ADD COLUMN valid_from date,
  ADD COLUMN valid_until date,
  ADD COLUMN checked_at timestamptz,
  ADD COLUMN checked_by uuid REFERENCES users(id),
  ADD COLUMN check_method text CHECK (check_method IN
    ('document', 'registry', 'manual_check', 'aggregator')),
  ADD COLUMN evidence_document_id bigint REFERENCES documents(id),
  ADD COLUMN application_ref text,               -- e.g. a Form 10AB acknowledgement number
  ADD COLUMN source_type text, ADD COLUMN evidence text;
CREATE UNIQUE INDEX org_identifiers_value_uq ON org_identifiers (id_type, id_value)
  WHERE id_value IS NOT NULL;
CREATE UNIQUE INDEX org_identifiers_open_uq ON org_identifiers (org_id, id_type)
  WHERE id_value IS NULL;
```

**What each status means:**

| Status | Meaning |
|---|---|
| `applied` | An application exists, e.g. a Form 10AB acknowledgement. Not a registration. |
| `check_blocked` | Somebody tried and the registry could not be read. It never means "valid". |
| `not_found` | Somebody read a working source and it did not list the registration. |

**Migration of `credential_events`.** Copy the latest verified event per (org, credential) onto
the matching identifier row's `status` and `valid_until`, then drop the table. It holds 0 rows
locally; check Supabase before running. Funder rows are discarded: funders no longer store
credentials (#99, D1).

### `org_financials`

```sql
ALTER TABLE org_financials
  ADD COLUMN foreign_unspent numeric,             -- FC unutilised at year end (FCRA return)
  ADD COLUMN source_type text, ADD COLUMN evidence text;
```

### `grants` → `funder_activity` (C4)

Each `grants` row becomes one `funder_activity` row:

| `funder_activity` column | Value from the grant |
|---|---|
| `kind` | `'partner'` |
| `funder_id` | `funder_id` |
| `partner_org_id` | `org_id` |
| `partner_name` | the CSO's name |
| `program_id` | `program_id` |
| `project_name` | `title` |
| `amount` | `amount` |
| `fiscal_year` | the fiscal year of `start_date`; `notes` records the full date range |
| `notes` | status (active / concluded / unconfirmed / dormant), dates and `outcomes` as text |
| `source_url` and the rest of the provenance | as on the grant |
| `is_public` | true |

`funder_activity` gains two nullable columns so nothing is lost:

```sql
ALTER TABLE funder_activity
  ADD COLUMN start_date date, ADD COLUMN end_date date,
  ADD COLUMN relationship_status text CHECK (relationship_status IN
    ('active', 'concluded', 'unconfirmed', 'dormant'));
```

**Re-pointing the tables that referenced `grants`:**
- `proposals.grant_id` → `proposals.awarded_activity_id` (FK `funder_activity`).
- `metrics.grant_id` → `metrics.activity_id` (FK `funder_activity`).
- `news_mentions.grant_id` → `news_mentions.activity_id`.
- `grant_locations` is dropped.

**API and front end:**
- `/api/grants` becomes a compatibility view over `funder_activity` partner rows, returning the
  same JSON shape, so the Registry's "Known funders" tab and the smoke check keep working.
- The seed's `grants.json` loads through the same mapping.

### Dropped

`credential_events`, `grants`, `grant_locations`, `program_locations`. All are empty or migrated
above.

### `documents`

New `doc_type` values:
- `trust_deed`
- `registration_certificate`
- `exemption_order` (12AB/80G: Forms 10AC/10AD)
- `exemption_application` (Form 10AB acknowledgement)
- `csr1_approval`
- `fcra_certificate`
- `fcra_return`
- `audit_report`
- `annual_report`
- `policy`
- `manual_check_evidence` (a screenshot or archive of a registry check)

### Migration

One file, numbered after #99's migrations. It runs in this order:
1. Add the columns.
2. Re-key `org_identifiers`.
3. Copy `credential_events`, then copy `grants` into `funder_activity`.
4. Re-point the foreign keys.
5. Drop the four tables.
6. Classify the new and changed tables under #92's grants and RLS. `org_identifiers` keeps its
   `is_public` rule; `funder_activity` keeps #99's.

Before running against Supabase:
- `SELECT count(*)` on each dropped table.
- A backup.

## 3. Code that changes

| Area | Change |
|---|---|
| `ingest/expectations.py`, `records.py`, `research_records.py` | `org_identity` gains `website`, `description`, `aliases`, `staff_count` and its note. `org_identifier` gains `status`, `valid_from`, `valid_until`, `application_ref` and `check_method`. `org_financials` gains `foreign_unspent`. Every org finding carries `source_type` and `evidence`. |
| `ingest/writer.py` | One precedence check, `_may_overwrite(stored, incoming)`, used by every org writer. Conflicts are returned to the caller. `write_org` stops being fill-empty-only and follows precedence instead. |
| `ingest/promote.py` | Promotion reports `conflicts` alongside `held`. Grant findings write `funder_activity` partner rows. |
| `ingest/matcher.py` | `resolve_org` adds an alias step (`orgs.aliases`) between exact name and trigram. Name normalisation folds "North East" / "Northeast" and strips "The", brackets and punctuation. |
| `ingest/tools/` | New staff-only tool `record_registry_check(org, id_type, status, evidence_document_id, note)`, which writes a manual check. It never raises, cites the evidence document, is registered, named in the instructions and labelled in `toolLabels.ts`. |
| `ingest/data/sources/ngos.json` | Adds `give_do` and `guidestar_india` with `access_rule: "manual_aggregator"` and a basis that names the allowed paths: Give.do's public `/discover/` pages, never `/api/`; GuideStar's public search API, nothing behind sign-in. `manual_aggregator` is added to the access-rule enum. `DISPATCHABLE` is unchanged: aggregators are read by the researcher's fetch tools, one CSO at a time, never by an adapter. |
| `agent/tools/sql/catalog.py` | New columns. Drop the 4 tables. `funder_activity`'s grant columns. A defect note: aggregator values are `claimed` and are never presented as fact. |
| `repositories/`, `schemas/`, routes | Org detail returns `website`, `description`, `aliases`, `staff_count`, identifier `status` and `valid_until`. `/api/grants` reads the compatibility view. |
| Frontend registry | The Diligence tab shows identifier **status** (Registered · Applied · Check blocked · Not found) instead of labelling every identifier "Verified". It also shows the website. |
| Seed | `seed.py` writes `source_type = 'seed'`. `grants.json` loads into `funder_activity`. |
| Tests, docs | Model-vs-table parametrisations. Matcher alias tests. Precedence and conflict tests. The migration integration test. `docs/DATA_PLATFORM.md`, `docs/INGEST.md`, `docs/SKILLS.md`. |

## 4. The skill: `ngo-credential-research` (C12)

The rewrite stays generic. It keeps the existing rules unchanged: a source URL on every value,
including "not stated"; `evidenced` vs `claimed`; pull raw values, no verdicts.

**Where to look, in order:**
1. **The CSO's own documents:**
   - trust deed or registration certificate;
   - PAN card;
   - 12AB/80G orders (Forms 10AC/10AD), or a Form 10AB acknowledgement;
   - CSR-1 approval;
   - FCRA certificate;
   - FCRA returns (FC-4);
   - audited accounts;
   - annual reports;
   - policies.

   Uploaded ones in the Doc Vault come first, then those on the CSO's site.
2. **Registries where a machine may read them.** Where one is behind a CAPTCHA, a login or a
   network filter, do not try to get past it. Record `check_blocked` and ask staff for a manual
   check (C9).
3. **Funders' own pages naming the CSO as a grantee**, and company CSR filings naming it as the
   organisation that carried out the work. Read those through `read_source_rows`, matching on
   name **and** district or state: short names collide.
4. **Staff datasets** (the internal CSO workbook) through `read_source_rows`.
5. **Prior research** (C14): the org-grant-intelligence dossier. In practice it is read *first*,
   as a map of leads, because its cited links feed steps 1–4. Its own values rank here.
6. **Aggregators** under `manual_aggregator`, last: corroboration and gap-filling only, always
   `claimed`.

**What to pull, and what is new:**
- **Statutory status as a status, not a yes/no.**
  - A Form 10AB acknowledgement is `applied`, never `registered`.
  - A registry that cannot be read is `check_blocked`, never assumed valid.
  - When the FCRA portal is unreachable, take the registration number from the CSO's own FCRA
    returns and leave validity `check_blocked`.
- **Financials by year from the audited statements:**
  - income, expenditure and surplus or deficit;
  - programme vs non-programme spend where stated;
  - foreign contribution received and unspent, from the FCRA returns.

  Quote any internal inconsistency in the audit verbatim in `notes`.
- **Existing funders, with amounts, from four places:**
  - grant lines in the audited accounts;
  - donors in FCRA returns;
  - funders' grantee pages;
  - company CSR filings and staff datasets.

  Each becomes a partner finding on the funder's side (`funder_activity`, `kind = 'partner'`)
  with its amount in rupees and its year.
- **Programmes and metrics** from annual reports, with year, marked `claimed`. Targets only when
  stated.
- **Governance and capacity:**
  - board as `office_bearer` contacts;
  - staff count with its note;
  - the policy list as `policy` documents.

  Conflicting counts are all recorded, each with its source.
- **Name variants** as aliases: every spelling seen in a source.
- **Website, description, social links.**

**Documents to request from the CSO** (C10), listed in the skill so the agent can ask
specifically:
- registration certificate or trust deed;
- PAN;
- 12AB and 80G orders;
- CSR-1 approval;
- FCRA certificate and its latest renewal;
- three years of audited accounts;
- three years of FCRA returns;
- the latest annual report.

**Staff dataset note.** In the internal CSO workbook, a funder block whose rows name the CSO itself
as a funder is mislabelled, most likely another CSO's table. The layout profile (#99, plan (c))
gains a check that holds such a block for staff instead of attributing it. The sheet should also
be fixed at the source.

## 4a. Prior research: the org-grant-intelligence repo (C14)

**What it holds:** https://github.com/project-tech4dev/org-grant-intelligence (public). Sangam's
seed data was copied from it at commit `414cd69`.
- **`ngos/<cso>/`:** markdown dossiers for 12 CSOs. They hold profile tables (PAN, registration,
  FCRA, CSR-1, board, contacts), summaries of annual reports by year, programmes, and the links
  each fact came from.
- **`Funder/<funder>/`:** dossiers for 16 funders, with profile, programmes, annual-report and PDF
  summaries, and links.
- **`hand-vetting/`:** fact-checked profiles and funder–CSO fit rubrics.
- **`ngos/darpan/*.json`:** Darpan extracts. These are already seeded.
- **`deep-agent-app/downloads/`:** about 45 proposal-template and guideline PDFs, named by funder
  type, plus a few RFPs.

**How it is used:**
1. **Read first.** The researcher reads the entity's dossier (`raw.githubusercontent.com`, pinned
   to a commit) before anything else. It saves the dossier's facts as findings with
   `source_type = 'prior_research'`, `evidence = 'claimed'`, citing the dossier file and its
   commit.
2. **Re-fetch the links.** Every link a dossier cites is a lead. The researcher re-reads the
   primary ones under their own access rules: the entity's own site, funder pages, registries.
   It saves what it finds with that source's type and evidence, which then outranks the dossier
   value under the precedence rule. Aggregator links a dossier cites (Give.do, GuideStar, and
   similar) are re-read only under `manual_aggregator`.
3. **Where a dossier and a primary source disagree,** the primary source wins and the disagreement
   is reported under `conflicts`. Dossiers can be out of date. The test CSO's dossier, for
   example, lists 80G as granted, while the CSO's own files show an application.
4. **Proposal templates and RFPs** in `downloads/` become `documents` rows (`proposal_template`)
   where a named funder publishes them. The rest stay as generic references and are not tied to
   any funder.

**Registry.** The existing `hand_vetting_sheets` entry is widened, or replaced by
`org_grant_intelligence`, covering the whole repository. Access rule: `internal_research`, the
team's own work, readable. Basis: facts carry the dossier's cited source; re-verify before
treating as evidenced. The fetch tool allows `raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/<commit>/…`.

**Writing back.** Not in scope. Sangam does not push to the repo. The repo is a frozen input
pinned to a commit; newer research lives in Sangam.

## 5. Order, execution, testing

**Order.**
1. #98.
2. #99's (a), (b), (c).
3. This spec as three PRs:
   - (d) CSO schema, evidence tiers, matcher aliases;
   - (e) grants → `funder_activity`;
   - (f) sources, manual checks, skill.

**Execution (C13).** `superpowers:subagent-driven-development` with the plans in `plans/`: a
fresh implementer per task, a fresh reviewer per task, and a whole-branch review.

**Acceptance run.** Re-profile the test CSO end to end through Import. Then check:
- identifiers carry statuses: PAN `registered`, 12A and 80G `applied`, FCRA validity
  `check_blocked`;
- three years of `org_financials`, including `foreign_unspent`;
- funder partner lines with amounts from every source;
- aliases resolve every spelling in the filings;
- the aggregator's financial figure is stored nowhere it would overwrite the audited one, and
  appears under `conflicts`;
- the profile scores at least 75% stored, against about 46% before.

## Out of scope

- Automating any check behind a CAPTCHA, a login or a network filter.
- Bulk aggregator crawling. Aggregators are read one CSO at a time, on a staff request.
- A staff vetting screen. Manual checks go through the Import chat tool for now.
- Linking `news_mentions` to CSOs. That is a separate signals piece of work.
