# Import M3: promote from the brief, and drop nothing

Third of the stacked PRs in `2026-10-13-import-researcher-contract.md`, on M2's branch.

## What changes

### 1. Promotion reads the brief
Every caller of `promote()` gets its row from `catalog_tools._research_rows`, so that is the one cut:
the newest row's findings become **the brief's facts plus that row's private findings** (staff
datasets and Doc Vault files, which the brief never holds). The plan preview, the review card, coverage
and the save all read the same record.
- No brief yet (first save before it is published, or Storage off locally): the row's findings, as today.
- Storage failed: the save refuses and says so, rather than promoting less than the record holds.
- A fact with no `concept` (a pre-typed run) is left out with a reason line.

Example: Axis's newest row (#150) holds 10 findings; promotion now reads the brief's 300.

### 2. Every fact ends in a state, written back into the brief
`promote()` reports a state per fact, keyed by `brief.fact_key`: written (with its row where the writer
returns one: a programme, a document or the entity itself, e.g. `[funder:29]`), confirms (already held), conflicts (Sangam holds another value), waiting (a person
answers), held (with the reason). After a save commits, the brief is republished with each fact's
state as a line under it, and a closing section lists every fact not in Sangam and why.

### 3. Fixes
| Fix | Example |
|---|---|
| A close match needs the same distinctive name and the same numbers | "Keystone Foundation" is no longer asked about against "Anudip Foundation"; "Mission 2 Million" not against "Mission 1 Million (2011-2018)" |
| A programme name matches without its parenthetical or `ABBR - ` prefix | "Mission 2 Million (2019-2025)" and "Mission 2 Million" are one row; spend "SLP - Rural Livelihoods" lands on "Rural Livelihoods" |
| A spend line naming no programme becomes a `component` under its parent | "SLP - Ecosystem Action", with no such programme, is created under "Sustainable Livelihood Programme" (SLP) |
| A programme's dependents wait for it | a phase whose parent was held is held too; a metric naming a programme not written is held, never written with a NULL link |
| Programmes are written parents first | "Rural Livelihoods" (programme) waits for "Sustainable Livelihood Programme" (programme) |
| Every spelling becomes an alias | a funder matched by name or number keeps the research's spelling |
| The matcher tries a name without its parenthetical, the parenthetical itself, and the website domain | "Knowledge and Advocacy for Better Livelihoods (KABIL)" finds KABIL |
| A re-run targets the entity its earlier save resolved to | Axis's next save writes to [funder:29] without matching again |
| Partner lines link when the NGO arrives | promoting an NGO links every unlinked partner line that names it |

### 4. One additive migration, `0046_import_columns.sql`
Each column gets a finding field, a writer and a catalog entry. Adding a column to the catalog is a
security decision: all are public facts about an organisation, from its own documents or filings.
| Column | Fed by |
|---|---|
| `funders.legal_form`, `founded_year`, `registered_address` | `identity.legal_form`, `founded_year`, `registered_address` |
| `funders.registered_location_id` | `stated_geography` with role `registered`, as for an NGO |
| `orgs.registered_address` | `org_identity.registered_address` |
| `orgs.parent_id` | `org_identity.parent_name`, linked only when it resolves; never created |
| `org_locations.program_id` | `org_location.program_name` |
| `funder_activity.source_type`, `evidence` | a partner line's tier, which travelled in `notes` |
| `'component'` in `programs.kind` | fix 3 |

The skills' ★ marks for these fields become their new finding fields.

## Known limits
- A fact read from the brief is stamped with the newest run's `fetched_at`; its block does not carry one.
- Staging has not taken 0046, so the staging dry run covers sections 1–3; section 4 was checked on a local
  database. Run `make migrate ENV=staging` before this deploys: `write_funder` reads the new columns.
- An `org_location` naming a programme Sangam does not hold is written without `program_id`, not held:
  the place is a fact on its own.

## Verification
- `pytest -m "not integration"`, `ruff`; `make migrate` on a local database.
- Exit: a dry-run promote of Axis and KABIL from their briefs (no model calls) leaves every fact in a
  state; the nine SLP spend lines and Mission 2/4 Million are planned; no programme-naming fact is
  planned with a NULL programme.
