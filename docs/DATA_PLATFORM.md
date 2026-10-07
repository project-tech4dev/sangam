# The data model we are building

Decision, 2026-09-29. We take the **v3 tables** from
`origin/docs/data-platform-architecture-spec` (`features-plans/data-model/`) and land them as
additive migrations, not as a new baseline.

The v3 write-up proposes wiping and reseeding. We do not need to: the diff is purely additive —
23 tables gain columns, 14 tables are new, **nothing is dropped and no column is removed**. So
`db/init/02_schema.sql` stays at v2 and `db/migrations/` carries everything, which is the rule
CLAUDE.md already states. The 96 documents and the Supabase data survive untouched, and v3's
`02_schema.sql` becomes the reference we derive each migration from rather than a file we copy in.

## Before → after

| | v2, today | v3, what we build |
|---|---|---|
| Tables / views / functions | 30 / 0 / 0 | 44 / 5 / 6 |
| Access control | none in the database; the backend connects as owner and sees everything | RLS on all 44 tables, SELECT policies on 43, and every request runs as the caller |
| Provenance | `source_url`, `source_name`, `fetched_at`, `content_hash`, `extractor_version` | the same plus `as_of` (the period the source describes), `document_id`, `archive_url` — one row = one fact = one source |
| Geography | 13 locations; all 10 districts parented to Assam, 3 of them wrongly | LGD codes, aliases, village level; 112 aspirational districts and 8 North East states as `location_designations` |
| Taxonomy | 40 tags, every one `kind='sector'`, free text | one `tags` tree: 17 SDGs, 24 sectors, 10 population groups, 30 CSR Schedule VII sectors, 221 domain cells; deprecate-and-replace, never delete |
| Funder money | one `funders.profile` jsonb blob | `funder_csr_years` and `funder_activity` — one row per filing or report line, `kind` spend / footprint / partner / programme (0031 merged the three tables this began as) — for Axis alone: 4 CSR years, 58 spend lines, 705 footprints, 114 partner lines, each with its source |
| Impact | `grants.outcomes` jsonb | `metrics` with stage, chain, baseline, comparison and method, plus the `impact_chains` view that shows where a chain stops |
| Credentials | a number in `*_identifiers`, no history | number stays there and can be private; what happened to it goes in `credential_events`; current state reads from `credential_status` |
| Org finances | none | `org_financials`, one row per org per fiscal year |
| Proposals | none | `proposals`; a funder's form is a `documents` row of `doc_type='proposal_template'` (0031) |
| Membership | one dev user, no orgs | `org_members` with `admin`, `member`, `steward` |
| Threads | `thread_id` + `user_id` | plus title, `use_case`, `org_id`, `context`, `visibility` — the left rail's data |

## Which tables change

23 of the 30 existing tables gain columns. **Nothing is dropped and no column is removed**, so
every current query keeps working — verified by diffing the two schema files, not read off the
write-up.

| Table | Gains | What it buys |
|---|---|---|
| `tags` | `domain`, `code`, `level`, `description`, `meta`, `status`, `replaced_by`, `sort_order` | turns a flat 40-row label list into every vocabulary we use — SDGs, sectors, CSR sectors, domain trees — with a lifecycle that deprecates instead of deleting |
| `news_mentions` | `kind`, `platform`, `summary`, `sentiment`, `review_status`, `reviewed_by`, `reviewed_at`, `archive_url` | the Signals tab: social items, a vetting step, and only vetted items going public |
| `threads` | `title`, `use_case`, `org_id`, `context`, `visibility`, `updated_by`, `updated_at` | the left rail — conversations grouped by use case, shareable with the team or with stewards |
| `org_identifiers` | `is_public`, `is_current`, `notes`, `source_name`, `fetched_at`, `as_of`, `document_id`, `archive_url` | a registration number can be on file without being published, and a superseded number stays readable |
| `documents` | `is_public`, `status`, `storage_path`, `uploaded_by`, `is_ai_generated`, `as_of`, `archive_url`, `created_at` | the Doc Vault: private uploads, and a `requested` document that is a row with no content yet |
| `programs` | `parent_id`, `kind`, `is_enabler`, `as_of`, `document_id`, `archive_url` | a funder's theme → programme → phase hierarchy, which is what CSR reports actually publish |
| `funders` | `parent_id`, `registry_status`, `as_of`, `archive_url` | a foundation links to its company, so Axis Bank Foundation inherits Axis Bank Limited |
| `orgs` | `registry_status`, `as_of`, `archive_url` | placeholder / in_vetting / full_profile / hidden drives the Registry chip |
| `locations` | `lgd_code`, `aliases` | districts match across sources despite spelling, and `village` becomes a valid kind |
| `users` | `auth_user_id`, `is_staff` | the link to Supabase Auth, and the staff flag every policy reads |
| `contacts` | `is_public`, `as_of`, `document_id`, `archive_url` | office bearers stay public, other contacts do not |
| `funders` | `cin`, `aliases` (0031) | a corporate funder's CIN and the other names it files under; funder_identifiers is gone |
| `grants`, `rfps` | `as_of`, `document_id`, `archive_url` | provenance only |
| `rfp_matches` | `week_of` | which weekly batch flagged the match |
| `org_tags`, `funder_tags`, `program_tags`, `rfp_tags` | `is_inferred`, `tagged_by`, `note` | separates what a source states from what a person or model inferred |
| `org_locations`, `funder_locations`, `program_locations`, `rfp_locations` | `valid_from`, `valid_to`, `note` + full provenance | a place link is itself a sourced, dated fact. **`funder_locations.role` also gains `priority` and defaults to it** — the 14 seeded rows are stated focus, not actual funding |

**Unchanged (7):** `chunks`, `extraction_log`, `rubrics`, `rubric_criteria`, `fit_scores`,
`fit_score_items`, `score_adjustments`. The rubric family stays exactly as it is; scoring logic
lives in the agent code.

### Where `documents.storage_path` points

`storage_path` is a key in Supabase Storage, in one of two private buckets created by
`db/migrations/0020_storage_buckets.sql`:

| Bucket | Holds | Key |
|---|---|---|
| `source-archive` | what research downloaded — public documents, kept so a fact survives its source URL going 404 | fetched as `<sha256(source_url)[:12]>/<sha256(bytes)>-<name>`, renamed by promotion to `funders/<slug>/<year>-<name>` |
| `org-vault` | what an organisation uploads about itself, private by default under DPDP consent | `<org_id>/<uuid4>-<name>` |

Two buckets rather than one per entity because a bucket separates **access rules** and a folder
organises; bucket names are also immutable.

They are keyed differently because of who holds the bytes when the key is minted. An upload
knows its org, so the vault leads with `<org_id>` — an **id, not a slug**, because `_free_slug`
appends a suffix on collision and `org_members` joins on `org_id`. That segment is the eventual
RLS predicate, read as `(storage.foldername(name))[1]::bigint`, which is why the convention is
fixed before the policies exist. The rest is a uuid rather than a content hash: the file goes
browser → Storage through a signed URL, so when the key is made the backend has never seen it,
and a hash there could only be one the client asserted. `content_hash` is measured afterwards,
from the bytes read back to extract the text.

The archive cannot do the same at the moment it writes: `fetch_document` runs during research and
a `funder_id` does not exist until `resolve_funder` runs at promotion. So it has **two keys and a
move between them**.

At fetch it keys on the **URL**, known at both moments, so promotion can find the object again
with no lookup table; and on the **content**, so a funder republishing at the same URL next year
adds a version rather than overwriting the bytes a finding was read from. The content hash in the
key is also what lets promotion fill `documents.content_hash` without re-downloading.

At promotion, `_shelve` renames it to `funders/<slug>/<year>-<publisher's filename>` — browsable,
sorted by year, and keeping the name the funder itself published so a row can be matched to its
source by eye. The leftovers are the point: **an object still under a hash folder is one we
downloaded and no finding ever cited.** `app/ingest/reshelve.py` re-runs the rename if the scheme
changes. Design and milestones: `docs/features/2026-09-30-supabase-storage.md`.

## Which tables are new

14, in four groups.

| | Table | Holds |
|---|---|---|
| **Who can see what** | `org_members` | a user's role in an org: `admin`, `member`, `steward`. Every private-read policy resolves through it, and deleting a row removes access |
| **Credentials** | `credential_events` | what happened to a registration — registered, renewed, checked, expired, cancelled, `not_available` — dated and sourced, holding **no number**, so history can be public while the number stays private |
| **Org facts** | `org_financials` | income, programme spend, foreign contribution, one row per org per fiscal year — the ₹5 crore eligibility gates read this |
| | `metrics` | impact and reach figures for an org **or** a funder, with `stage`, `chain_key`, `baseline`, `comparison_value` and `method` — a results chain rather than a headline number |
| **Funder money and activity** | `funder_csr_years` | the statutory annual return per year: average net profit, the 2% obligation, spend, unspent transfer, excess |
| | `funder_activity` | one line of a filing, report or partner list per year: `spend` (with outlay, partner and implementation mode), `footprint` (state and place), `partner`, or `programme` (the funder's own split, never summed with spend). Every spend and programme line carries an inferred domain and, where evidenced, a theme, with `classified_by`, a note and `classification_confirmed` |
| **Places** | `grant_locations` | where a grant was actually spent — the difference between where a funder *says* it works and where it did |
| | `location_designations` | aspirational district, North East, and the designations funders prioritise |
| **Proposals** | `documents` (`doc_type='proposal_template'`) | a funder's application form, kept as a document; `proposals.template_id` points at it |
| | `proposals` | an org's proposal, from drafting to awarded, linked to its thread and its draft documents |
| | `reference_figures` | external benchmarks for budgeting — cost per beneficiary, overhead norms, salary ranges |

**Plus 5 views** (`location_paths`, `tag_paths`, `credential_status`, `funder_district_presence`,
`impact_chains`) and **6 functions** — five access helpers in schema `app`, and `check_template()`,
which returns pass / fail / missing / manual per template item.

### One more, which v3 never defined

`resolution_queue` — the architecture spec's name-resolution step (§7.2) ends in a review queue,
and there is no table for it anywhere in the 44. Every extracted org, funder, partner or place
name that fixed identifiers, exact match and trigram similarity could not resolve lands here:
the raw name, its context, the top candidates with scores, and a decision.

It is the table that prevents the failure the Graphiti spike produced — Christian Medical College,
Vellore merged into the registry org Better Life Foundation. The rule it enforces is that a new
name is **never** merged into a registry org automatically unless it matched on an identifier or
exactly; anything else waits for a reviewer. Accepted variants are written back to
`locations.aliases`, `funders.aliases` or `funder_activity.partner_canonical`, and resolving the queue is what
finally fills `funder_activity.partner_org_id`, empty today.

It lands with the name-resolution work, not with the baseline. Everything else the spec adds is a
view or a function — `org_places`, `org_tag_set`, `funder_signal_base` and `entity_edges` are
views; `match_scores(org_id)` and `connections(a, b)` are functions. No other new tables.

## How a fact links back to its source

Every fact table carries the same six columns — this is the block that `0001_provenance` adds
where it is missing, and that each new table is created with:

```sql
source_url text,        -- the page or PDF; we link it, we do not cache it
source_name text,       -- 'axis-bank-csr-report', 'indiacsr', 'give.do'
fetched_at timestamptz, -- when we read it
as_of text,             -- the period the source describes: 'FY2025-26'
document_id bigint REFERENCES documents(id),   -- set when we read it from a content file
archive_url text        -- web archive snapshot, taken when the fact was recorded
```

`documents` is the join target. A funder's report is one row there — owned by the funder, with its
own provenance and `content_hash` — and every fact extracted from it points back with
`document_id`. One document, many facts:

```
funders 'Axis Bank Limited'
   │
   ├── documents  'Axis Bank Annual CSR Report FY2025-26'   (funder_id, doc_type='csr_report',
   │        ▲       source_url=axis.bank.in/…, fetched_at=2026-09-27, as_of='FY2025-26')
   │        │ document_id
   │        ├── funder_activity     footprint · Baksa · FY2025-26
   │        ├── funder_activity     … 705 footprint lines across 3 reports
   │        ├── funder_activity     partner · 'Ayang Trust' · FY2025-26
   │        ├── funder_activity     spend · ₹8 crore · others (sports) · FY2024-25
   │        └── metrics             0.71 million families reached · FY2025-26
   │
   └── funders 'Axis Bank Foundation'  (parent_id → Axis Bank Limited)
```

**Why both `source_url` and `document_id`.** They answer different questions. `source_url` is
always set, including for the many facts read off a page we never stored — a Darpan record, a
news item, `give.do`. `document_id` is set only when the text is in `documents`, and it is what
makes "show me the report this came from" a join rather than a string match. The loader resolves
it by `source_url`, so re-running adds nothing.

**Why `as_of` is separate from `fetched_at`.** The same PDF is the source for three fiscal years
of facts. `fetched_at` is 2026-09-27 for all of them; `as_of` is what distinguishes FY2023-24
from FY2025-26 within one document.

**Two ways a funder fact reaches a funder**, and both are needed:

| | Path | Answers |
|---|---|---|
| The fact's subject | `funder_activity.funder_id → funders.id` | "where did Axis work" |
| The fact's evidence | `funder_activity.document_id → documents.funder_id → funders.id` | "which Axis report says so" |

They are usually the same funder and sometimes are not — a news article about Axis is a
`documents` row owned by Axis, but an SBI RFP naming Axis as a co-funder is not.

## Six fixes, for when the access layer lands

v3's RLS has six problems. None of them blocks the table migrations above — they are the
gate on the phase after it, except #4, which rides with `0007`.

| | Problem | Fix |
|---|---|---|
| 1 | RLS decides which **rows** a role sees; it does not grant access to the table. The baseline's only grant is `USAGE ON SCHEMA app`. | An explicit per-table `GRANT SELECT` to `anon` and `authenticated`, allowlisted — not `ALL TABLES`. |
| 2 | 45 policies, of which exactly one is INSERT. Under run-as-caller every write fails — threads, proposals, news review, score adjustments. | Write the missing policies, or route writes through an owner path and say which, per table. |
| 3 | `contacts_read_auth USING (true)` gives every signed-in user every email and phone. | Column-level grant. The agent catalog stays stricter than the policy. |
| 4 | `fiscal_year` is unvalidated text in five tables. | `CHECK (fiscal_year ~ '^FY\d{4}-\d{2}$')`. |
| 5 | The RLS loop only covers tables that exist when the baseline runs, so the four `checkpoint*` tables, `schema_migrations` and `graph_ingest_log` get none. | Enable RLS on them after `checkpointer.setup()`. |
| 6 | `03_dev_user.sql` does not set `auth_user_id`, which local run-as-caller needs. | One column. |

Two seed fixes ride along: districts parent to their real state (Dimapur is Nagaland, Bishnupur
and Tamenglong are Manipur), and the seven ordered load steps become one idempotent `make seed`.

## Authorization: run every query as the caller

The v3 schema says the backend repeats the RLS rules by hand in each query. We do not — that is a
rule enforced by memory, and it fails the first time someone forgets. Each request instead opens
with `SET LOCAL ROLE authenticated` (or `anon`) and the JWT subject, so the policies apply to REST
and to the agent alike.

Checked against staging rather than assumed: the backend connects as `postgres`, `rolsuper = f`,
and it is already a member of `authenticated` and `anon`. Nothing to provision. This is also what
gives the SQL agent a second line of defence again — checkpoint tables unreadable, `pg_read_file`
denied — which the `sangam_reader` role was going to provide before we dropped it.

## The plan: ten migrations

One file per group, applied in order by `make migrate`. Each is reviewable on its own, each
unblocks something concrete, and each runs in a single transaction.

| File | Changes | Introduces | Unblocks |
|---|---|---|---|
| `0001_provenance.sql` | `as_of`, `document_id`, `archive_url` on orgs, funders, grants, rfps, programs, contacts; full provenance + `is_current` on both `*_identifiers`; `is_inferred`, `tagged_by`, `note` on the four `*_tags`; `valid_from`, `valid_to`, `note` + provenance on the four `*_locations` | — | every later loader can record where its facts came from |
| `0002_taxonomy.sql` | `tags`: `domain`, `code`, `level`, `description`, `meta`, `status`, `replaced_by`, `sort_order`; `kind` CHECK widened to 8 values; domain-required constraint; indexes | — | `python -m seed.taxonomy_seed` — SDGs, sectors, population groups, the livelihoods tree |
| `0003_geography.sql` | `locations`: `lgd_code`, `aliases`, `village` added to the `kind` CHECK, indexes; `funder_locations.role` gains `priority`, defaults to it, and the 14 seeded rows are relabelled | `location_designations`, `grant_locations` | `reference_data.sql` — 112 aspirational districts, 8 North East states — and the `seed.py` geography fix |
| `0004_identity.sql` | `users`: `auth_user_id`, `is_staff`; `orgs`/`funders`: `registry_status` | `org_members` | the whole access layer later; nothing user-visible now |
| `0005_documents_threads.sql` | `documents`: `is_public`, `status`, `storage_path`, `uploaded_by`, `is_ai_generated`, `created_at`, `as_of`, `archive_url`; `threads`: `title`, `use_case`, `org_id`, `context`, `visibility`, `updated_by`, `updated_at` + the shared-needs-org CHECK | — | Doc Vault, and the left rail's conversation grouping |
| `0006_credentials.sql` | `org_identifiers`: `is_public`, `notes` | `credential_events` | the KABIL credential findings, and `credential_status` when views land |
| `0007_funder_activity.sql` | `funders.parent_id`; `programs`: `parent_id`, `kind` (theme/programme/phase/project), `is_enabler`; the `fiscal_year` format CHECK | `funder_csr_years`, `funder_csr_spend`, `funder_footprints`, `funder_partners` | `axis_bank.sql` and `axis_bank_disclosures.sql` — 705 footprints, 114 partner rows, 58 spend rows |
| `0008_org_facts.sql` | — | `org_financials`, `metrics` | `kabil_impact.sql` results chains, and the ₹5 crore eligibility gates |
| `0009_proposals.sql` | — | `proposal_templates`, `template_items`, `proposals`, `reference_figures` | `sbi_foundation_gramseva.sql` — the 59-item template and `check_template()` |
| `0010_signals.sql` | `news_mentions`: `kind`, `platform`, `summary`, `sentiment`, `review_status`, `reviewed_by`, `reviewed_at`, `archive_url`; `rfp_matches.week_of` | — | the Signals review workflow and the weekly RFP batch |

That is all 23 changed tables and all 14 new ones. After `0010`, a fresh `make up` plus
`make migrate` produces the v3 table set from the v2 baseline.

**`0031_funder_consolidation` is the first migration that drops tables.** Nine funder tables became five: `funder_identifiers` → `funders.cin` / `aliases`; `funder_csr_spend`, `funder_footprints`, `funder_partners` → `funder_activity`; `funder_eligibility` and `proposal_templates` / `template_items` → `documents`. Every row with a home is copied; templates with content stop the migration. A `funder_eligibility` document's `is_public` is copied from the funder when written, so hiding a funder later leaves it public until its next promote. Spec: `features-plans/data-model/2026-10-07-funder-model-consolidation.md`.

**Three things make this safe to do one at a time.**

- **Nothing existing breaks.** Every change is an added column, an added table, or a widened
  CHECK. No query in `repositories/`, no route and no frontend call reads a column that moves.
  The one data change is the `funder_locations.role` relabel in `0003`, and nothing filters on
  that literal today.
- **The agent's boot gate does not block a migration.** `verify_against_db()` only fails when the
  catalog lists something the database lacks — extra live tables are logged at INFO and extra
  columns are not checked at all. So `catalog.py` is updated *deliberately*, per slice, when we
  want the agent to see the new tables. It is not forced into the same commit.
- **Each file has a loader behind it.** A migration that lands with no data to put in it is hard
  to review and easy to get subtly wrong. Pairing each with its seed file means every slice is
  provable the day it merges.

**Not in this phase:** the 5 views, the 6 functions, RLS, the table grants and the policies, auth,
and `resolution_queue`. Those are the access layer, and they come next — the six fixes above are
written against them, except the `fiscal_year` CHECK, which rides with `0007`.

One cosmetic consequence worth knowing: `ALTER TABLE ADD COLUMN` appends, so column *order* will
differ from v3's `02_schema.sql`. The tables are equivalent; a `pg_dump` diff against that file
will not be byte-identical.

## Not now

Matching views and `match_scores`, `entity_edges` and `connections()`, the chunking and embedding
pipeline, Graphiti (deferred — the spike answered 0 of 4 benchmark questions as well as SQL and
got 39 of 40 fact expiries wrong), and csr.gov.in.

---

# What a fundraiser asks for, and where each answer lives

The brief the importer is built to answer is a CSO's, not an analyst's: *name two funders and
tell me whether we can apply.* Twenty-eight fields. This is the map from each one to the column
that holds it, because that map is what decides whether research becomes a row or a paragraph —
and it is the first thing here that will go stale.

| # | The brief asks for | Where it lands |
|---|---|---|
| 1 | Organization name | `funders.name` |
| 2 | Parent company / group | `funders.parent_id` — linked only when the parent resolves |
| 3 | CSR entity type | `funders.funder_type` |
| 4 | Official website | `funders.website` |
| 5 | Latest annual CSR spend | `funder_csr_years.total_spent` |
| 6 | Previous 2–3 financial years | `funder_csr_years`, one row per year |
| 7 | Total CSR budget, if disclosed | **`funder_csr_years.notes`** — see below |
| 8 | Key themes / focus sectors | `funder_tags` → `tags(kind='csr_sector')`, `is_inferred` true |
| 9 | Major programmes | `programs`, theme → programme → phase via `parent_id` |
| 10 | Geographic focus | `funder_locations` (stated) and `funder_activity` `kind='footprint'` (actual) |
| 11 | Target beneficiary groups | **no column** — `tags(kind='population')` exists, nothing seeds it |
| 12–13 | Typical / min / max grant size | `funders.grant_size_min` `grant_size_max`; per call, `rfps.amount_min/max` |
| 14 | Typical project duration | `funders.typical_duration_months` |
| 15 | Funds external NGOs? | `funders.funds_external` (stated) vs `funder_activity.implementation_mode` (done) |
| 16 | NGO eligibility criteria | the funder's `funder_eligibility` document, verbatim, under statutory restatement / its own bar / disqualifiers; per call, `rfps.eligibility` |
| 17 | Application process | a `documents` row, `doc_type='proposal_template'` — **no writer yet** |
| 18 | Open / rolling / invitation-only | `funders.intake_mode` |
| 19 | Current or recent RFPs | `rfps` |
| 20 | Application deadlines | `rfps.deadline` |
| 21 | Contact details | `contacts.name` `role` `kind`; `email` only for a shared mailbox |
| 22 | Major implementation partners | `funder_activity` `kind='partner'` |
| 23 | Grants in the last 2 years | **`funder_activity` `kind='partner'`** — `grants` has no writer |
| 24 | Amount per partnership | `funder_activity.amount` + `partner_name` on spend lines |
| 25 | States / districts worked in | `funder_activity.state_location_id` / `location_id` → `locations` |
| 26 | Schedule VII categories | `funder_activity.csr_sector_id` (as filed) → `tags(kind='csr_sector')`; what it was spent on is `domain_tag_id` / `theme_tag_id`, inferred |
| 27 | Annual report / CSR policy links | `documents` |
| 28 | Source links for everything | `source_url` + `source_name` + `fetched_at` on every fact row |

## The three that deliberately have no column

**Total CSR budget (7).** `prescribed_csr` is the statutory 2% obligation. A company that
publishes a budget above it is publishing a *plan*, and plan-versus-spend is the distinction this
whole platform enforces — a column invites the two to be averaged. It stays in `notes` with the
funder's own wording, and the report prints it beside the obligation.

**Beneficiary groups (11).** `tags.kind` allows `'population'` and no vocabulary is seeded.
Letting a researcher's free text become tag rows is the "Building Human Capital becomes
Education" failure, one level down. Until a controlled list exists the wording stays on the row
it describes.

**Application process (17).** A form is a `documents` row of `doc_type='proposal_template'` and has no writer. The URL of the form reaches `rfps.url`; the form's structure does not.

## One answer that is now two columns

**Eligibility (16).** A funder's standing bar and one call's requirements are different
claims, and `rfps.eligibility` could only hold the second — which meant a funder with a
published policy and no open call had nowhere to put the first, and most funders have no
open call. The standing policy is a `funder_eligibility` document per page, the text verbatim under the split `funder-intake-research` field 4 works to
produce: a funder that only restates Rule 4 has set no bar of its own. `rfps.eligibility`
is unchanged and still means "this call asks for it". The same sentence appearing in both
is correct, not a duplicate — and counting across the two double-counts.

## Two answers that are honest rather than complete

**Grants (23).** `grants.org_id` is `NOT NULL`, and promoting a funder's research does not
write the NGOs it names, so a funded organisation we do not already hold cannot be a grant row. Such a relationship is recorded in
`funder_activity` with `kind='partner'`, whose `partner_org_id` is nullable — which is the more careful claim anyway, since a
named partner is not proof that money changed hands. The report says so rather than implying an
empty `grants` table means no grants.

**Funds external NGOs (15).** Two columns, never reconciled. `funders.funds_external` is what the
funder *says*; counting `funder_activity.implementation_mode = 'implementing_agency'` on spend lines is what it *did*. The report prints both —
*"States that it funds external NGOs; 3 of 18 recorded projects ran through an implementing
agency"* — because the gap between them is itself the finding.
