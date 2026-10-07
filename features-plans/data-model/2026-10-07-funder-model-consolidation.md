# Funder model consolidation, spend domains, and staff-only CSR sources

Status: proposal for review. It builds on PR #98 (theme taxonomy in `tags`, cross-references in
`tag_links`), which must merge first. Server-side enforcement of "staff only" depends on PR #92.

## Why

A test profile of one funder (a corporate CSR foundation, from MCA filings, its own reports and
an internal CSO sheet) reached about 70% completeness, and showed three things about the model:

1. **Most funder tables are empty and split along lines the data does not follow.** A CSR spend
   line, a footprint and a partner are the same filing line with different columns filled. Three
   tables triple the writers, keys, catalog entries and tests.
2. **Some stored fields are not needed.** Funders do not need CSR-1, PAN or 12A/80G; those are
   recipient credentials. Eligibility is a policy text, better kept verbatim than split into rows.
3. **Spend needs a domain on every line, including what fits no programme theme.** About 4% of
   the test funder's spend was environment and about 19% was relief, sports, admin or unlabelled.
   Some lines also support a theme or sub-theme (about 20% of the test funder's spend), most do not.
4. **Every classification is an inference.** Filing labels rarely match taxonomy words; even a
   close match is a judgement. The model must say what a label rests on and whether a person has
   confirmed it.

## Decisions

| # | Decision |
|---|---|
| D1 | Funders do not store CSR-1, PAN or 12A/80G. A corporate funder keeps its **CIN**. |
| D2 | `funder_identifiers` goes. `funders` gains `cin` and `aliases`. |
| D3 | `funder_eligibility` goes. Eligibility is a `documents` row (`doc_type = 'funder_eligibility'`) holding the guideline text verbatim. |
| D4 | `funder_csr_spend`, `funder_footprints` and `funder_partners` merge into **`funder_activity`**, one row per filing or report line, with a `kind`. |
| D5 | `proposal_templates` and `template_items` go. A template is a `documents` row (`doc_type = 'proposal_template'`). |
| D6 | Two domains join the taxonomy: **Environment** and **Others**, with no themes. Every `funder_activity` line carries one of the five domains, and a theme or sub-theme where the evidence supports one. |
| D7 | Filings attach to the **corporate parent** (the MCA filer); a foundation is its child through `funders.parent_id`. |
| D8 | Three source spreadsheets live in a new private **`staff-sources`** bucket, readable by staff (`users.is_staff`) only, never by org admins. |
| D9 | The `funder-intake-research` skill stays generic: what to pull, from which kinds of source, in which order, including eligibility guidelines. No funder is named in it. |
| D10 | "Draft" labels come off the front-end taxonomy pages. `status` stays in the data. |
| D11 | Every domain and theme on a line is an **inferred label**: it records what it rests on, a short evidence note, and whether a person has confirmed it. |
| D12 | A funder's own programme split ("₹X on programme A this year") is stored **at funder level**, never spread onto filing lines. |
| D13 | Each staff dataset has a **layout profile**. The reader goes through every sheet of every file, whatever its layout, and returns normalised rows in rupees. |

## 1. Taxonomy (on top of #98)

**Data.** In `seed/data/taxonomy/themes.json`, add two domains with an empty theme list:

```json
{"domain": "environment", "label": "Environment", "status": "active",
 "source": "Spend on environmental sustainability, conservation and animal welfare that is not a livelihood programme", "themes": []},
{"domain": "others", "label": "Others", "status": "active",
 "source": "Spend that fits no programme domain: disaster relief, sports, central funds, administration, unlabelled or multi-sector lines", "themes": []}
```

`make taxonomy-seed` then writes `domain-environment` and `domain-others` (kind `domain`, no
links). Copy the file to `frontend/features/taxonomy/data/` (the smoke check diffs the two).

**Code and tests.**
- `catalog.py`: the `tags.domain` note lists five domains.
- `test_taxonomy_seed.py`: `TAG_COUNTS["domain"]` becomes 5.

**Front end.**
- `/resources/taxonomy` renders all five domains. Environment and Others show their one-line
  `source` and no theme cards.
- The section index lists all five.
- Remove every "Draft" mention: the status badges on domain headings, the status tags in "How the
  taxonomy works", and "Health and Education are drafts" wording.

## 2. Funder schema: nine tables to five

| Today | After |
|---|---|
| `funders` | `funders` + `cin`, `aliases` |
| `funder_identifiers` | dropped |
| `funder_eligibility` | dropped → `documents` |
| `funder_csr_spend`, `funder_footprints`, `funder_partners` | `funder_activity` |
| `proposal_templates`, `template_items` | dropped → `documents` |
| `funder_tags`, `funder_locations`, `funder_csr_years` | kept |

### `funders`

```sql
ALTER TABLE funders
  ADD COLUMN cin text UNIQUE,                          -- corporate funders only; trusts have none
  ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';     -- other names it files or is reported under
```

- `parent_id` (0007) already exists. A foundation's `parent_id` is the corporate MCA filer.
- The 0019 posture columns (`intake_mode`, `funds_external`, `typical_duration_months`,
  `grant_size_min`, `grant_size_max`) stay. They are referenced by no code today, so this spec
  wires them into the catalog entry and the identity writer (§3).
- `profile` keeps only leftovers that have no column.

### `funder_activity`

One row per line of a CSR filing, annual report or partner list.

```sql
CREATE TABLE funder_activity (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('spend', 'footprint', 'partner', 'programme')),
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY\d{4}-\d{2}$'),
  program_id bigint REFERENCES programs(id) ON DELETE SET NULL,
  domain_tag_id bigint REFERENCES tags(id),            -- kind 'domain': one of the five
  theme_tag_id bigint REFERENCES tags(id),             -- kind 'theme' or 'sub_theme'; NULL when the
                                                       -- evidence supports no theme
  classified_by text CHECK (classified_by IN
    ('filed_sector', 'project_name', 'partner', 'report')),
  classification_note text,                            -- the evidence, e.g. "project 'Financial
                                                       -- Literacy & Inclusion'; filed under Education"
  classification_confirmed boolean NOT NULL DEFAULT false,
  csr_sector_id bigint REFERENCES tags(id),            -- Schedule VII, as filed
  state_location_id bigint REFERENCES locations(id),
  location_id bigint REFERENCES locations(id),         -- most specific place below state
  name_as_printed text,                                -- place as the source printed it
  project_name text,
  designation text,
  implementation_mode text CHECK (implementation_mode IN
    ('direct', 'implementing_agency', 'own_trust_or_section8', 'not_stated')),
  partner_name text,
  partner_canonical text,
  partner_org_id bigint REFERENCES orgs(id),
  partner_funder_id bigint REFERENCES funders(id),
  partner_csr1 text,                                   -- the PARTNER's CSR-1, when filed
  partner_kind text CHECK (partner_kind IN ('ngo', 'foundation', 'university', 'research',
    'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
  outlay numeric CHECK (outlay >= 0),
  amount numeric CHECK (amount >= 0),
  project_count integer,
  is_ongoing boolean,
  notes text,
  source_key text,                                     -- source registry key, e.g. 'mca_csr'
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  CHECK (kind <> 'spend' OR amount IS NOT NULL),
  CHECK (kind <> 'footprint' OR location_id IS NOT NULL OR state_location_id IS NOT NULL),
  CHECK (kind <> 'partner' OR partner_name IS NOT NULL),
  CHECK (kind <> 'programme' OR (program_id IS NOT NULL AND amount IS NOT NULL)),
  CHECK (domain_tag_id IS NULL OR classified_by IS NOT NULL),
  UNIQUE NULLS NOT DISTINCT (funder_id, kind, fiscal_year, program_id, csr_sector_id,
    state_location_id, location_id, designation, project_name, partner_name)
);
CREATE INDEX funder_activity_funder_kind_idx ON funder_activity (funder_id, kind, fiscal_year);
CREATE INDEX funder_activity_domain_idx ON funder_activity (domain_tag_id);
CREATE INDEX funder_activity_theme_idx ON funder_activity (theme_tag_id);
CREATE INDEX funder_activity_location_idx ON funder_activity (location_id, fiscal_year);
CREATE INDEX funder_activity_partner_org_idx ON funder_activity (partner_org_id);
```

**Kinds.**

| `kind` | One row is | Typical source |
|---|---|---|
| `spend` | A filing line with an amount | Statutory CSR filing, CSR annexure |
| `footprint` | A place where the work ran in a year | Annual or impact report district lists |
| `partner` | A named partner in a year | Partner lists in reports, filing project names |
| `programme` | **The funder's own figure** for one programme component in a year, e.g. a foundation reporting ₹X on rural livelihoods and ₹Y on skilling. Attached to a `programs` row (`funder_id` set, with `parent_id` for components) | The funder's annual report |

`programme` rows are the funder's totals. They are never summed with `spend` lines and never
spread onto them: spreading would turn an estimate into a per-line classification (D12). Reports
and the agent compare the two side by side instead.

**Classification (D11).** Domains and themes are both inferred.
- `domain_tag_id` is filled on every `spend` and `programme` row. Environment and Others have no
  themes, so their lines carry a domain and no theme.
- `theme_tag_id` is filled at the most specific level the evidence supports:
  - a **sub-theme** when the project name or the named partner points to one;
  - a **theme** when only the broad area is clear;
  - **NULL** when the line gives nothing to go on (e.g. "Sustainable Livelihood", "Education").
- `classified_by` records the basis:
  - `filed_sector`: the funder's Schedule VII sector, used only where it is unambiguous;
  - `project_name`;
  - `partner`: what the named organisation is known for;
  - `report`: the funder's own programme naming.
- `classification_note` holds the evidence in a few words.
- `classification_confirmed` starts false. Vetting sets it.
- Totals by domain or theme can therefore be reported "confirmed" or "including inferred".
- The filed sector itself always stays in `csr_sector_id`.

How the old columns map onto the new table:
- `funder_csr_spend.implementing_agency`, `agency_csr1` and `agency_org_id` become the `partner_*`
  columns.
- `via_agency` becomes `implementation_mode`.
- `funder_csr_spend.district_location_id` and `funder_footprints.location_id` become `location_id`.

### `funder_csr_years`

Kept. It gains `local_area_spent numeric`, which the MCA filing reports and the table lacks.

### `documents`

- New `doc_type` values: `funder_eligibility`, `proposal_template`, `source_dataset`.
- `writer.ensure_document` deduplicates on `(source_url, doc_type)` instead of `source_url`
  alone. A policy page can then be both the archived source document and the funder's
  eligibility document.

### `proposals`

`template_id` loses its FK to `proposal_templates` and gains one to `documents(id)`.

### Migration

One file, numbered after #98's `0030`. Open branches hold `0022`–`0030`, so the number is
reassigned at merge time if they land in a different order. Steps:

1. `ALTER TABLE funders` (`cin`, `aliases`).
2. Copy `funder_identifiers` rows:
   - `id_type = 'name'` → `aliases`
   - `cin` → `funders.cin`
   - `domain` → `funders.website` where empty
   - every other `id_type` is discarded (D1).
3. `CREATE TABLE funder_activity` and copy any rows from the three old tables. They are empty
   locally; check Supabase before running.
4. `ALTER TABLE funder_csr_years ADD local_area_spent`.
5. Repoint `proposals.template_id`.
6. Drop `funder_identifiers`, `funder_eligibility`, `funder_csr_spend`, `funder_footprints`,
   `funder_partners`, `template_items` and `proposal_templates`, in FK order.
7. If #92 has merged, classify `funder_activity` in its grants and RLS migrations: public read,
   like the tables it replaces. #92's migrations fail on an unclassified table.

Before running against Supabase:
- `SELECT count(*)` on each dropped table.
- A backup, per CLAUDE.md (`make migrate ENV=staging` is run deliberately).

## 3. Code that changes

The table below is from an impact map of master; file:line references are kept in the review
thread.

| Area | Change |
|---|---|
| `ingest/expectations.py` | ConceptSpecs `csr_spend`, `footprint`, `partner` and a new `programme_spend` all target `funder_activity` with a fixed `kind`, and `expected_fields()` returns only that concept's columns. Drop `identifier` and `funder_eligibility` concepts. |
| | `identity` gains `cin`, `aliases` and the posture columns. |
| | Fix the "40 tables" text. |
| `ingest/records.py`, `research_records.py` | Drop `FunderRecord.identifiers`, `IdentifierFinding` (funder side) and `FunderEligibilityRecord`. Add `kind` to the activity records. Add an `EligibilityGuideline` finding that becomes a document. |
| `ingest/writer.py` | One `FUNDER_ACTIVITY_KEY` including `kind`. Drop `_write_identifiers` and `write_funder_eligibility`. `write_funder` writes `cin`, `aliases` and posture. `ensure_document` dedupes on `(source_url, doc_type)`. |
| `ingest/promote.py` | `WRITE_ORDER`, `CONCEPT_RECORDS`, `RENAMED` and `_row_identity` follow the new tables. Eligibility promotes to a documents row. |
| `ingest/matcher.py` | The identifier step reads `funders.cin` and the alias step reads `funders.aliases`. Org matching (`org_identifiers`) is untouched. |
| `ingest/brief.py`, `tools/catalog_tools.py` | Dossier sections read `funder_activity` by `kind`. Eligibility reads the latest `funder_eligibility` document. `_held_per_concept` filters by `kind`. |
| `ingest/runner.py`, `geography.py`, `extractor.py` | Table names. |
| `agent/tools/sql/catalog.py` | Add `funder_activity`. Remove the 5 dropped funder tables and `template_items`. Add `funders.cin`, `aliases` and the posture columns. Update table counts and wording everywhere: CLAUDE.md, `docs/SQL_AGENT.md`, `expectations.py`. |
| `repositories/funders.py`, `schemas/funders.py`, `frontend/lib/api/types.ts` | Funder detail drops `identifiers` and adds `cin`. `IdentifierOut` stays for orgs. |
| `seed/seed.py`, `graph_seed.py` | The domain rows seeded into `funder_identifiers` go to `funders.website`. |
| Skills and prompts | `catalog-mapping`, `catalog-write-report`, `funder-scan-for-fundraisers`, `prompts/entity_researcher.md`: table names, the eligibility-as-document rule, and the classification columns. `funder-intake-research`: §4. `ngo-credential-research`: the staff CSO profile sheet as a source (§4). |
| Tests | `test_ingest.py`: the concept and model-vs-table parametrisations, `WRITE_ORDER`, `_row_identity`, `MERGEABLE` and `apart` sets (funder side only), the identifier rejection test. `test_sql_catalog.py`, `test_migration_integrity.py`, `test_sql_integration.py`. |
| Docs | `docs/DATA_PLATFORM.md` and `docs/INGEST.md` table lists. |

## 4. Staff-only sources and the intake skill

### The three sources

| File | What it is | Source registry key |
|---|---|---|
| CSR Analytics report, FY2014-15 to FY2024-25 (one sheet per year) | MCA CSR filings: company-level obligation and spend, plus project lines (sector, state, district, outlay, spend, mode) | `mca_csr` (manual export or licensed mirror) |
| Dataful CSR data subset | MCA CSR project lines for 51 groups, all 11 years | `mca_csr` |
| CSO programmes and current funders | 12 CSOs' funders, projects, years and grant amounts, seen from the receiving side | `ffrh_funder_datasets` (`partner_permission_internal`: CSO consent needed before any public display) |

### Storage

- **A new migration** creates a private bucket, `staff-sources`, guarded like 0020 so local runs
  are a no-op. `storage.split()` learns the bucket.
- **Each file gets a `documents` row:**
  - `doc_type = 'source_dataset'`
  - `is_public = false`, `org_id` and `funder_id` NULL
  - `source_name` = the registry key
  - `storage_path = 'staff-sources/<sha12>-<name>'`
  - no `content_md` and no chunks, so the SQL tool, which runs as the database owner, cannot read
    the contents.
- **Upload:** a one-off staff script now, `scripts/upload_staff_source.py`, using the service key.
  A `require_staff` route can follow once #92 lands.
- **Who can read:**
  - Staff only. Org admins (`org_members.role = 'admin'`) are not staff and cannot read these.
  - Enforced by `readable_document()` (`is_public` false and no org → staff only).
  - After #92: by `documents_read` RLS and staff-only Import, plus a `storage.objects` policy
    limited to `app.is_staff()`.
  - Until #92 merges every caller is the staff dev user, so "staff only" is marked but not
    enforced. Say so in the PR.

### Layout profiles (D13)

The three files are laid out differently, and two of them have more than one shape inside.

| File | Sheets | Layout |
|---|---|---|
| CSR filings subset | 1 | One table, one row per project line, amounts in ₹ crore |
| CSR analytics report | 11, one per fiscal year | One table per sheet, same header. A `State` column appears twice: the company's state, then the project's. Amounts in ₹ crore |
| CSO programmes and funders | 3 | `CSO Profile`: one row per CSO. `CSO Funder Details`: side-by-side blocks, one per CSO, with the CSO name in the top row. `CSO Current funder and Partners`: one section per CSO under a heading, amounts in **₹ lakh** |

Each file gets a layout profile in `backend/app/ingest/data/source_layouts/<name>.json`. It
declares:
- `source_key` and a `filename_pattern`, which together match the profile to its `documents` row;
- for every sheet:
  - its `layout`: `table`, `blocks_by_column` or `sections_by_heading`;
  - its header row;
  - how a block or section is found;
  - a `column_map` from each source column, by position where names repeat, to a normalised
    field: `company`, `funder`, `cso`, `fiscal_year`, `project`, `filed_sector`, `state`,
    `district`, `outlay`, `amount`, `implementation_mode`, `purpose`;
  - its `amount_unit` (`crore` or `lakh`).

A sheet with no profile entry is an error, not a skip. A new sheet in a re-uploaded file fails
loudly instead of being ignored.

### The tool

- **`read_source_rows(match, source_keys=None, fiscal_years=None, limit=500)`** in
  `app/ingest/tools/pipeline_tools.py`.
  - Reads **every staff dataset and every sheet in each**, unless `source_keys` narrows it. Each
    one is read through its layout profile.
  - Returns normalised rows whose `company`, `funder` or `cso` matches `match` or one of the
    funder's `aliases`. Amounts come back in rupees, with the raw value and unit kept beside.
  - Cites every row as `[source:<document_id>#<sheet>:<row>]`, so each fact names its file and
    sheet.
- **It follows the tool conventions:**
  - it never raises, returning `read_source_rows failed: …` instead;
  - every row is cited;
  - it is registered in the Import agent;
  - it is named in its instructions and labelled in `features/ingest/lib/toolLabels.ts`.
- **It adds `openpyxl` to the backend's runtime dependencies.**
- **`DISPATCHABLE` stays unchanged.** Reading a staff-uploaded manual export is manual entry, not
  crawling.

### The skill

Rewrite of `funder-intake-research/SKILL.md`. It stays generic: no funder, file or company is
named in it.

**New section, "Where to look, in this order":**
1. **Statutory CSR filings for the corporate entity** — the MCA filer, which is often the parent
   company, not the foundation:
   - read them with `read_source_rows`, which searches every staff dataset and every sheet;
   - record the filer as the parent funder and the foundation as its child;
   - pull company-level obligation, spend, local-area spend and unspent amounts per year into
     `funder_csr_years`;
   - pull project lines into `funder_activity` (`kind = 'spend'`).
2. **The funder's own publications:**
   - annual reports and impact reports of the foundation;
   - the parent's annual report and its "Annual Report on CSR Activities" annexure;
   - the CSR policy and annual action plan;
   - the CSR impact-assessment report;
   - the business responsibility and sustainability report.

   These give programme components and spend, partner lists by year, district lists, outcomes
   and targets, admin and impact-assessment costs, and unspent transfers.
   Record the funder's own programme split as `kind = 'programme'` rows (D12), not as an
   estimate spread across filing lines.
3. **Recipient-side records** — the internal CSO funder sheet when present, and recipients' own
   annual reports — for grant amounts per partner, which funders rarely publish.

Every fact names the file and sheet, or the page, it came from.

**Eligibility guidelines (field 4, widened).** Look explicitly for:
- the CSR policy's partner-selection and due-diligence clauses;
- "partner with us", "grant guidelines", "how to apply" and FAQ pages;
- proposal or application guidelines;
- the annual action plan;
- any eligibility section in an annual report.

Pull the text **verbatim**, keeping the split the skill already makes: statutory restatement,
the funder's own bar, and disqualifiers.

- The guideline is stored as one `funder_eligibility` document, with its source URL.
- When the eligibility applies through a parent's policy (e.g. a bank policy covering spend
  through its foundation), mark it `claimed` for the child and say whose document it is.
- "Not stated" still carries the URL of the page read.

**Classification rule for spend lines (D11).** Domains and themes are inferences; say so.
- Classify each line by **project name and named partner**, not by the Schedule VII sector it
  was filed under. Filings misfile often: financial-inclusion work under education or health, an
  NGO under central government funds.
- **Domain, always:**
  - Lines that are relief, sports, administration, unlabelled, or that list several sectors at
    once go to **Others**.
  - Environmental sustainability, conservation and animal welfare that is not a livelihood
    programme goes to **Environment**.
- **Theme, at the most specific level the evidence supports:**
  - a sub-theme when the project or partner points to one;
  - a theme when only the area is clear;
  - none otherwise.

  Never pick a theme to avoid leaving one empty.
- Record `classified_by`, a one-line `classification_note` quoting the evidence, and leave
  `classification_confirmed` false.
- The filed sector is still stored in `csr_sector_id`.

**CSO side.** The staff CSO profile sheet (registration, programmes, geography, leadership) and the
CSO funder sheets also serve CSO research. `ngo-credential-research` names them as a source: read
them through `read_source_rows` with the CSO's name, cite the sheet, and treat them as the
organisation's self-reported record.

**Kept unchanged:** the rules on provenance (URL, fetch date, access state), on `evidenced` vs
`claimed`, and on never citing an aggregator. Recipient-side figures cite the recipient's
document or the internal sheet's document id.

## 5. Order, testing, coordination

**Order.**
1. #98 (taxonomy in tags).
2. This spec as three PRs:
   - (a) taxonomy domains and front-end "Draft" removal;
   - (b) migration and code (§2–§3);
   - (c) staff-sources bucket, upload script, `read_source_rows`, skill (§4).
3. #92 enables enforcement.

**Testing.**
- Unit tests for each changed Import path. The parametrised model-vs-table tests are the guard
  that each concept sees only its own columns.
- `test_migration_integrity.py` and `test_sql_integration.py` (integration mark) for the new table
  and the drops.
- Catalog boot check (`verify_against_db`).
- `make smoke`.
- An acceptance run: load one corporate funder's lines from both MCA datasets through
  `read_source_rows` into `funder_activity`. Check:
  - totals per fiscal year equal the filing totals;
  - every line has a domain and a `classified_by`;
  - themes are set only where a note quotes the evidence;
  - `programme` rows are reported beside the filing totals, not summed into them;
  - Others holds what this spec assigns to it.
- Layout-profile unit tests against **synthetic** fixtures that reproduce each layout:
  - repeated column names;
  - side-by-side blocks;
  - headed sections;
  - lakh vs crore.

  The real files are confidential and are never committed. A sheet without a profile must fail
  the test.

**Coordination.**
- The eligibility change reverses part of #89's design, so #89's author reviews (§2, §3).
- Migration numbering is settled with the open branches holding 0022–0030.
- #92's grants and RLS migrations classify `funder_activity` and the new bucket's documents.

## Out of scope

- Bulk-loading all 14,000+ MCA lines. Lines are read per funder, on demand.
- Public display of recipient-side grant amounts; that needs CSO consent.
- A staff upload screen.
