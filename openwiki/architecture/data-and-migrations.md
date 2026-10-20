---
type: architecture concept
title: Data and Migrations
description: How Sangam's Postgres schema is organised by table group (including RFP Watch's rfps tables, server-side proposals and document links), why a baseline plus forward-only migrations (latest 0049) define it, how the SQL catalog drift check gates backend boot, how shared public SQL fragments hide private sources, where documents live in storage buckets, and how provenance columns keep the optional Neo4j graph rebuildable.
tags: [database, postgres, migrations, provenance, storage, neo4j, schema]
sources:
  - id: openwiki-source-ecac68c83347b18f912f2a53
    resource: repo://backend/app/agent/tools/sql_tools.py
  - id: openwiki-source-7faba850789bc67a49b79a3f
    resource: repo://backend/app/agent/tools/sql/catalog.py
  - id: openwiki-source-ca736c25c2a1bb0e95531706
    resource: repo://backend/app/api/routes/documents.py
  - id: openwiki-source-e962a60de608d42004eac41b
    resource: repo://backend/app/api/routes/registry.py
  - id: openwiki-source-bb520e58d272c5fe6ee64d79
    resource: repo://backend/app/api/routes/rfps.py
  - id: openwiki-source-e136029ec7d24feaceb8ce72
    resource: repo://backend/app/core/lifespan.py
  - id: openwiki-source-b52886aad1fc413e4e030f22
    resource: repo://backend/app/core/security.py
  - id: openwiki-source-51ead927cc43f35e220ea627
    resource: repo://backend/app/db/checkpointer.py
  - id: openwiki-source-48da13ff10650a1cb4ac7718
    resource: repo://backend/app/db/migrate.py
  - id: openwiki-source-10e08c1deca7d7728d8240c4
    resource: repo://backend/app/db/pool.py
  - id: openwiki-source-1d8678f87564f9d42020ba27
    resource: repo://backend/app/db/replicate.py
  - id: openwiki-source-005aaff315c996a45f8735d6
    resource: repo://backend/app/ingest/calls/run.py
  - id: openwiki-source-bb6ad31efddf76d28f69f61e
    resource: repo://backend/app/ingest/expectations.py
  - id: openwiki-source-9a78159bc32f1e4e6ca68b3f
    resource: repo://backend/app/ingest/news/run.py
  - id: openwiki-source-f5f9bed243c70c8c32486478
    resource: repo://backend/app/ingest/source_guards.py
  - id: openwiki-source-465a2de3f088ab05c5629202
    resource: repo://backend/app/integrations/graphiti.py
  - id: openwiki-source-bbb88a9dc2dd928de209ddbb
    resource: repo://backend/app/integrations/storage.py
  - id: openwiki-source-0fc683b5c9f0801e9edbf645
    resource: repo://backend/app/matching/run.py
  - id: openwiki-source-697868bd3a418ce8115944eb
    resource: repo://backend/app/repositories/documents.py
  - id: openwiki-source-1157f5d2ae5aa2bccc1057d0
    resource: repo://backend/app/repositories/proposals.py
  - id: openwiki-source-e1e1f5d3920af8337551a6ac
    resource: repo://backend/app/repositories/public_sql.py
  - id: openwiki-source-75dfe6dd359f71f41900608d
    resource: repo://backend/app/repositories/registry.py
  - id: openwiki-source-7883f648138e78c1e5c84c85
    resource: repo://backend/app/repositories/rfps.py
  - id: openwiki-source-8b5590d38dd10784b7da1f6d
    resource: repo://backend/app/schemas/rfps.py
  - id: openwiki-source-c19bf12e33dd13dd52164b8e
    resource: repo://backend/tests/test_migration_integrity.py
  - id: openwiki-source-b9b33576e920a6ec443c1309
    resource: repo://backend/tests/test_sql_catalog.py
  - id: openwiki-source-5871ea1c2ab913bbd11be84f
    resource: repo://db/CLAUDE.md
  - id: openwiki-source-ae9507c4a442eab54c70e7da
    resource: repo://db/init/02_schema.sql
  - id: openwiki-source-5d936c732a0a021ab7221170
    resource: repo://db/migrations/0001_provenance.sql
  - id: openwiki-source-3960d3e6bb146b4c53ddd9e9
    resource: repo://db/migrations/0019_rfp_identity_and_funding_profile.sql
  - id: openwiki-source-dfac4787d4864ec73643d276
    resource: repo://db/migrations/0020_storage_buckets.sql
  - id: openwiki-source-a63cf999b1937db913f804d5
    resource: repo://db/migrations/0025_table_grants.sql
  - id: openwiki-source-a51b4e8aa8968bfd9e155474
    resource: repo://db/migrations/0027_rls.sql
  - id: openwiki-source-4f00b570b8820dd507c244db
    resource: repo://db/migrations/0031_funder_consolidation.sql
  - id: openwiki-source-8a68723db5e310243ef50c5d
    resource: repo://db/migrations/0032_staff_sources_bucket.sql
  - id: openwiki-source-b4e85bafe598be11046fc009
    resource: repo://db/migrations/0033_cso_consolidation.sql
  - id: openwiki-source-dfabaf3b44724986c797abe6
    resource: repo://db/migrations/0034_grants_into_funder_activity.sql
  - id: openwiki-source-bedfa05c67900013e140a5fc
    resource: repo://db/migrations/0041_catalog_writes.sql
  - id: openwiki-source-2939d404ec1a27d9be23ffd5
    resource: repo://db/migrations/0042_funder_matches.sql
  - id: openwiki-source-3a57c4fb7f0662ab72e2805d
    resource: repo://db/migrations/0044_news.sql
  - id: openwiki-source-afa502fc99bdec75aa59f7f1
    resource: repo://db/migrations/0044_one_read_policy_and_fk_indexes.sql
  - id: openwiki-source-d1c5532960252357e823b43e
    resource: repo://db/migrations/0047_document_links.sql
  - id: openwiki-source-3d121c1ca466c424ca2b4936
    resource: repo://db/migrations/0048_proposal_work.sql
  - id: openwiki-source-d2d39b77b74bd31e2a50555d
    resource: repo://db/migrations/0049_rfp_match_saved.sql
  - id: openwiki-source-82b4a7ca109f9768db60ccbf
    resource: repo://db/migrations/README.md
  - id: openwiki-source-093cd3e20819d97ab4faddda
    resource: repo://db/scripts/truncate_all.sql
  - id: openwiki-source-e8e61d605125cac4d909755e
    resource: repo://docs/ARCHITECTURE.md
  - id: openwiki-source-88fdf568b0f25b1d21f041da
    resource: repo://docs/CHANGELOG.md
  - id: openwiki-source-3625960871aaf9afc169d0c3
    resource: repo://docs/DATA_PLATFORM.md
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
  - id: openwiki-source-60b751726aee2d4aae078a12
    resource: repo://seed/graph_seed.py
generated: { by: "openwiki/0.7.2", at: "2026-10-19T19:22:00.060Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-10-19T19:22:00.060Z
---

# Data and Migrations

Postgres is Sangam's system of record. Everything researched, imported, scored or saved ends up as rows there, and every other store is either derived from it (the Neo4j graph) or holds bytes that rows point at (Supabase Storage). This page covers the shape of the schema, how it changes, what stops the backend from booting against a mismatched schema, and how provenance ties facts back to sources.

Related pages: [Auth, roles and RLS](auth-roles-rls.md) (the policies and grants those migrations create), [RFP Watch](rfp-watch.md) (the feature that owns the `rfps` table group), [Proposal Copilot](proposal-copilot.md) (the feature that owns `proposals.work`), [Ask Sangam](ask-sangam.md) (the SQL tool whose catalog is checked at boot), [Sangam Import / Scout](sangam-import-scout.md) (the main writer of catalog rows and documents), and the how-to [Writing a migration](../workflows/writing-a-migration.md).

## Baseline plus forward-only migrations

There are two places SQL lives, and they have different jobs.

| Location | Role | When it runs |
|---|---|---|
| `db/init/01_extensions.sql`, `02_schema.sql`, `03_dev_user.sql` | The **baseline** (the "v2" schema): `pgvector` and `pg_trgm` extensions, the original ~30 tables, and the seeded dev user | Automatically on first boot of the bundled Postgres container, or once by hand with `make db-init-remote` against an empty managed database |
| `db/migrations/NNNN_name.sql` | Every schema change **after** the baseline | Only when someone runs `make migrate` |

The baseline is deliberately not rewritten as a "migration 0000", so a fresh install is one fast `CREATE TABLE` pass instead of a replay of history ([migrations README](../../db/migrations/README.md)). `02_schema.sql` still describes the v2 world (for example `grants`, `funder_identifiers`, `news_mentions`); the current table set exists only after the migrations are applied. The planning history of that decision, including why additive migrations were chosen over a wipe-and-reseed, is in `docs/DATA_PLATFORM.md`.

**Rule: schema changes go only in a new `db/migrations/*.sql` file** (`db/CLAUDE.md`). A new table also needs RLS policies, and reaching Ask needs an entry in `backend/app/agent/tools/sql/catalog.py`, which is a security decision, not a convenience.

### The runner

`backend/app/db/migrate.py` is a small forward-only runner, invoked as `make migrate` and `make migrate-status` (`python -m app.db.migrate [--status]` inside the backend container, reading `DATABASE_URL` and `MIGRATIONS_DIR`, default `/srv/db/migrations`, which compose mounts from `./db`).

- It creates a `schema_migrations(version, checksum, applied_at)` ledger if missing, then walks `*.sql` files in sorted **filename** order.
- A file's `version` is its stem; the checksum is the first 16 hex chars of a SHA-256 of its text.
- Each pending file runs in **its own transaction** together with its ledger insert. On any error the file is rolled back, the failure is printed to stderr, and the run stops: nothing later is attempted.
- If a recorded version's checksum differs from the file on disk, the runner prints `DRIFT: file changed after it was applied` but continues and does not fail. The convention is therefore: never edit an applied file, write a new one.
- `--status` lists applied, drifted and pending files without writing anything.

### Migrations are not automatic

Nothing applies migrations behind your back, with one local exception. `make up` runs `make migrate ENV=local` first, but only when `ENV=local` and the bundled `postgres` service exists, because the backend cannot boot against an unmigrated database (see the boot check below). `make seed` likewise depends on `migrate` locally. Against a managed database (`ENV=staging`) migrating is an explicit, separate decision, normally after a backup; `make up ENV=staging` only prints a reminder.

### Two files numbered `0044`

The directory holds 50 `.sql` files (the latest is `0049_rfp_match_saved.sql`) and **two are numbered `0044`**: `0044_news.sql` (the Media & Signals tables) and `0044_one_read_policy_and_fk_indexes.sql` (folds duplicate `users`/`org_members` read policies and adds three FK indexes). Both landed in parallel branches; staging had already applied `0044_news`, and because the runner keys on the full file name (not the number), both were kept rather than renumbered. Order between them is alphabetical (`0044_news` before `0044_one_read…`). Do not "fix" this by renaming either file, as that would make the runner treat the renamed file as new and re-run it. `0045_drop_news_mentions.sql`, `0046_import_columns.sql`, `0047_document_links.sql`, `0048_proposal_work.sql` and `0049_rfp_match_saved.sql` follow.

### Conventions worth knowing

- One logical change per file; additive by default. A destructive change (`DROP`, type narrowing, new `NOT NULL`) should carry a comment explaining why the data makes it safe. Migrations that did drop tables copied rows first: `0031` consolidated nine funder tables into five (into `funders`, `funder_activity`, `documents`), `0033` folded `credential_events` into `org_identifiers.status`, and `0034` retired `grants` into `funder_activity` partner lines.
- `org_identifiers` is granted **by column** (`0033`), so a new column there needs an explicit `GRANT SELECT (col) … TO anon, authenticated` to be readable.
- Storage-related migrations are guarded: `0020` and `0032` skip bucket creation when there is no `storage` schema (the local Postgres container is not Supabase), recording themselves as applied so the ledgers still match.
- A migration that adds a table also needs it listed in `docs/CHANGELOG.md` and `docs/ARCHITECTURE.md` §7 in the same PR.
- `make db-clean` (`db/scripts/truncate_all.sql`) truncates every public table with `RESTART IDENTITY CASCADE` but keeps `schema_migrations` (dropping it would make `make migrate` replay everything), then re-inserts the local dev user and marks it staff, because every local request resolves to it; `app.db.replicate` copies one database's rows into another with an **identical** schema (see below).

## Table groups

The model is grouped by what the tables mean; the exact column lists live in the migrations and in the SQL catalog.

```mermaid
erDiagram
    orgs ||--o{ org_identifiers : "registrations"
    orgs ||--o{ programs : "runs"
    funders ||--o{ programs : "flagship"
    funders ||--o{ funder_activity : "spend footprint partner programme"
    orgs ||--o{ funder_activity : "partner_org_id"
    documents ||--o{ funder_activity : "document_id evidence"
    documents ||--o{ chunks : "text and embeddings"
    documents ||--o{ document_links : "backs"
    orgs ||--o{ proposals : "writes"
    funders ||--o{ proposals : "applied to"
    orgs ||--o{ org_members : "who may see"
    users ||--o{ org_members : "role"
    users ||--o{ threads : "owns"
    tags ||--o{ tag_links : "taxonomy"
    locations ||--o{ funder_activity : "state and district"
```

Caption: a simplified slice of the entity relationships; every fact table also carries source columns that point back at `documents`.

| Group | Tables (as of the latest migration) |
|---|---|
| CSOs | `orgs`, `org_identifiers` (carries a status, validity dates and an evidence tier), `org_locations`, `org_tags`, `org_financials`, `metrics`, `programs`, `program_tags`, `contacts` |
| Funders | `funders`, `funder_activity` (one row per filing line, `kind` = spend / footprint / partner / programme; a grant is a partner line), `funder_csr_years`, `funder_locations`, `funder_tags` |
| Taxonomy and geography | `tags` (every vocabulary by `kind`), `tag_links`, `locations` (LGD codes), `location_designations` |
| Documents | `documents` (`doc_type` is free text, with reserved and proposal-related values described below), `chunks` (pgvector embeddings plus a generated `tsvector`), `document_links`, `extraction_log` |
| Import | `entity_research`, `vault_research`, `ingest_runs`, `ingest_run_items`, `resolution_queue`, `ingest_source_proposals`, `promotions`, `catalog_writes` |
| Scores | `rubrics`, `rubric_criteria`, `fit_scores`, `fit_score_items`, `score_adjustments`, `reference_figures` |
| RFPs | `rfps` (a funder's call, with `status` open / closed / removed, `deadline`, amount range and provenance), `rfp_tags` and `rfp_locations` (link tables), and `rfp_matches` (one row per org and call; `status` is `flagged`, `saved`, `reviewed` or `dismissed`, widened to include `saved` by `0049`) |
| Match | `funder_matches`, `funder_match_details` (saved runs, private to an org) |
| Proposals | `proposals` (an org's proposal to one funder; `work` and `summary` jsonb added in `0048`); a funder's form is a `documents` row of type `proposal_template`, since `0031` dropped `proposal_templates` and `template_items` and re-pointed `proposals.template_id` at `documents` |
| News | `news_stories`, `news_links`, `news_link_scores`, `news_story_entities`, `news_story_locations`, `news_story_tags`, `news_watch` (from `0044_news`; `news_mentions` was dropped in `0045`) |
| Access | `users`, `org_members`, `threads` |
| Infrastructure | `schema_migrations`, `graph_ingest_log`, and LangGraph's `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` |

A few notes on specific groups:

- **RFPs and `rfp_matches` (`0049`).** The `rfps` tables belong to [RFP Watch](rfp-watch.md). `rfps` rows are written by `make calls-pull` and Import, never by a caller, and are unique on `(funder_id, title, deadline)` (`0019`). `rfp_matches` is org-private: `0027` gives it a read policy for the org's people and staff and an update policy for `app.my_writable_org_ids()` (members and admins, never stewards) or staff, and `0025` grants `authenticated` only `UPDATE`, no insert and no delete. `0049_rfp_match_saved.sql` is a one-statement migration: it drops `rfp_matches_status_check` and re-adds it with `saved` in the allowed set (the baseline allowed only `flagged`, `reviewed` and `dismissed`). It is the whole schema change behind the Save button, and needs no new policy or grant because the existing update policy already covers the column. Rows must exist before anyone acts, since callers can only update: `repositories/rfps.py` `flag_matches` inserts one row per org with members and per open, unexpired call sharing a domain, with `matched_by = 'rules:domain'` and `week_of`, using `ON CONFLICT DO NOTHING` so a re-run never overwrites an org's choice. `update_match` (behind `PATCH /api/rfps/{id}/matches/{org_id}`) then sets `status` and stamps `matched_by` with the user's id. The `RfpMatchUpdate` schema's `Literal["flagged", "saved", "reviewed", "dismissed"]` mirrors the CHECK constraint, so a new status needs both a migration and a schema edit (and the SQL catalog's `status` `values` for `rfp_matches`). The feed query shows an org its `saved` calls whatever became of the call, and its non-dismissed calls only while the call is open and not past its deadline (computed in `Asia/Kolkata`). Both `rfps` and `rfp_matches` are in the SQL catalog.
- **Import bookkeeping.** `promotions` and `catalog_writes` (`0041`) are the undo log for saving Import research into the catalog. A trigger `app.log_catalog_write()` records old and new row JSON for a fixed list of catalog tables, but only while a save has set `sangam.promotion_id`; nothing else is logged. A newly added table that Import saves into must be given the same trigger, as `0047` does for `document_links`. See [Sangam Import / Scout](sangam-import-scout.md).
- **`resolution_queue`.** Names that identifiers, exact match and trigram similarity could not resolve wait here for a reviewer; a new name is never auto-merged into a registry org without an identifier or exact match.
- **Checkpoint tables** are not in any migration. `open_checkpointer` (`backend/app/db/checkpointer.py`) calls LangGraph's `AsyncPostgresSaver.setup()` on every boot, which issues idempotent DDL. They hold every user's serialized conversation history and are deliberately kept away from the SQL tool and from `app.db.replicate`.
- **`proposals` is a live, server-side table.** `0009_proposals` created it (with `status`, `requested_amount`, `thread_id`, document pointers and so on), and `0048_proposal_work` made it the store for the [Proposal Copilot](proposal-copilot.md): `work jsonb NOT NULL DEFAULT '{}'` holds everything the proposal screen and its agent edit, and `summary jsonb` is what the list shows, recomputed from `work` on every save. `backend/app/repositories/proposals.py` runs as the caller (RLS decides access): `list_proposals` never reads `work`, and every change to `work` goes through `save`, which takes `SELECT … FOR UPDATE` on the row, applies a change function (`app.proposals.work`) and writes `work`, `summary`, title and `updated_at` back in one transaction. The agent side (`org_of`, `load`) uses the owner pool, since chat access and `require_edit` decide who gets there. Each person's chat is a per-user thread `proposal-<id>-<user_id>`. `proposals` is still in the SQL catalog's `KNOWN_EXCLUDED`, because it holds every org's private drafts. Older `0009` columns such as `status`, `template_id` (now a foreign key to `documents`) and `awarded_activity_id` (replacing `grant_id`, `0034`) remain in the schema.
- **Who may write proposals.** `0048` rewrites the `proposals_insert` and `proposals_update` policies to `app.my_match_org_ids()` (the org's admins and stewards, the same set that may save a Funder Match run) or staff; ordinary members still read through the unchanged `proposals_read` and no longer write. The same migration widens `documents_insert` to `app.my_org_ids()` or staff, so a Doc Vault upload is open to every role in the org, and re-runs `0027`'s guard that fails the migration if any readable public table has no read policy. In code, `org_id_for_member(..., write=False)` in `backend/app/repositories/documents.py` is what the vault upload routes pass so stewards are admitted. See [Auth, roles and RLS](auth-roles-rls.md).
- **Proposal-related document types.** `documents.doc_type` is free text, not a CHECK enum. `proposal_template` (a funder's application form, one of `RESERVED_DOC_TYPES` in `backend/app/ingest/expectations.py` that Import research may not write; `funder_form` picks the newest by `fetched_at`) and `proposal_draft` are the two proposal types. `insert_draft` stores a saved proposal version's Word file as a private (`is_public = false`) `proposal_draft` document in the org's Doc Vault, with `is_ai_generated = true`, `source_name = 'Sangam Pitch'` and status `received`. The other reserved values are `funder_eligibility` and `source_dataset`.
- **RLS everywhere.** `0027` enables row-level security on every public table, and later migrations add their tables' policies; the grants and policies are covered in [Auth, roles and RLS](auth-roles-rls.md).

## Connection pools and the runtime view of the schema

`make_pool` (`backend/app/db/checkpointer.py`) builds the single `AsyncConnectionPool` shared by REST, agent tools and the checkpointer; it is opened in the FastAPI lifespan, set as `app.db.pool.pool`, and sized by `DB_POOL_MAX_SIZE` (default 10). It connects as the owner with `min_size=1`, `autocommit=True`, `prepare_threshold=0` and dict rows. The standalone batch jobs (`app/ingest/calls/run.py`, `app/ingest/news/run.py`, `app/matching/run.py`) call `make_pool` themselves with a small explicit `max_size`, so they never touch the server's pool. `backend/app/db/pool.py` exposes the server's pool in three ways, plus a per-turn companion variable:

- `get_pool()` / `OwnerPoolDep` return the raw owner pool. Only identity code (which decides who the caller is and writes `users` and `threads` rows no caller may write), Import, seeds and the proposal agent's `org_of`/`load` helpers take it; unit tests override `get_pool` to keep a real database.
- `CallerPool` (`PoolDep`, built by `get_caller_pool` from the role and claims `AuthMiddleware` put on the request; anon without them) wraps the pool so each connection is one transaction that first runs `set_caller`, a `set_config(..., true)` (`SET LOCAL`) of the Postgres role and `request.jwt.claims`. Both end with the transaction, error included, so the connection returns to the pool as the owner. Routers and repositories such as `proposals.py` take this, so RLS applies without each route asking.
- `agent_caller`, a `ContextVar` holding `(role, claims)` set per `/agent` request, is how Ask Sangam's SQL tools, which run outside any request, query as the caller; unset, their SQL runs as `anon`. `ask_access` (`backend/app/core/security.py`) sets it after the thread-ownership check; Import's agent keeps the owner pool because it writes the catalog.
- `caveats_given`, a second `ContextVar` (a fresh `set()` per `/agent` request, also set by `ask_access`), records which tables' data caveats the SQL tools have already spelled out this turn, so `sql_tools._caveats_for` gives them in full once and then a one-line pointer. Unset, every result gives them in full.

## SQL catalog drift check at boot

Ask Sangam's SQL tool can only read what `backend/app/agent/tools/sql/catalog.py` lists: a hand-curated allowlist of tables and columns. Because that catalog is a security control, the backend compares it with the live database before serving anything.

```mermaid
flowchart TD
    A["lifespan opens pool"] --> B["verify_against_db reads information_schema.columns and column privileges"]
    B --> C{"catalog table or column missing, or not SELECTable by a role"}
    C -- yes --> D["log SQL catalog drift errors and raise RuntimeError, boot fails"]
    C -- no --> E["list live base tables"]
    E --> F{"tables in neither CATALOG nor KNOWN_EXCLUDED"}
    F -- yes --> G["log at INFO, table stays invisible to the SQL tool"]
    F -- no --> H["continue: graph, checkpointer, agents"]
    G --> H
```

Caption: the boot-time catalog gate in `_verify_sql_catalog` (`backend/app/core/lifespan.py`).

Semantics, which matter when you write a migration:

- **Fails boot** when the catalog lists a table that does not exist, or a column the table lacks. So a migration that drops or renames a catalogued table or column must update `catalog.py` in the same change, and an unmigrated database fails fast (this is why `make up` migrates first).
- **Also fails boot on privileges.** Chat queries run as the caller, so `verify_against_db` additionally checks `has_column_privilege`: any catalogued column that `authenticated` cannot `SELECT` is a problem, as is a table `anon` reads only in part (a whole table closed to `anon` is allowed), because that would break `SELECT *`. A migration that narrows grants, such as the column-level grant on `org_identifiers`, can therefore break boot until the catalog matches.
- **Does not fail** for extra live tables or extra live columns. New tables are logged at INFO as "not readable by the SQL tool and not declared as excluded" until someone either adds them to the catalog or to `KNOWN_EXCLUDED`. That means a migration can ship without making the agent see the table; exposing it is a deliberate, separate step.
- The catalog allowlists 37 tables. `KNOWN_EXCLUDED` names the 22 tables deliberately withheld (the four checkpoint tables, `users`, `threads`, `org_members`, `proposals`, Import bookkeeping, `vault_research`, `funder_matches` and `funder_match_details`, the Media pipeline state `news_link_scores` and `news_watch`, `promotions` and `catalog_writes`, `schema_migrations`, `graph_ingest_log`). `backend/tests/test_sql_catalog.py` asserts that the most sensitive of these are not in `TABLE_NAMES` and are declared excluded, and that withheld columns such as `contacts.email` are absent even from the `*` expansion.
- The catalog also validates itself at import (`_self_check`): every table needs columns and a primary key, and foreign keys must target catalogued tables and columns.
- `backend/app/ingest/expectations.py` derives Import's researchable fields from the same catalog, so it stays in sync with the schema without a second list.

## Provenance columns

Every table that holds a scraped or extracted fact carries the same provenance block. The baseline defined `source_url`, `source_name`, `fetched_at`, `content_hash`, `extractor_version`; `0001_provenance` and later migrations add `as_of` (the period the source describes, for example `FY2025-26`), `document_id` (a foreign key to `documents` when the text is stored) and `archive_url` (a web-archive snapshot).

- `source_url` is always set, even for pages never stored; `document_id` is set only when the content is in `documents`, which turns "show me the source" into a join. `as_of` is separate from `fetched_at` because one PDF can be the source for several fiscal years of facts.
- `documents` is the join target; `document_links` (`0047`) records what each document backs (owner, programme, fiscal year, cited pages) and is written by Import's promotion. It is as private as its document via an RLS policy that reads `documents`.
- Tag and location link tables use `is_inferred`, `tagged_by`, `note` and validity dates to separate what a source states from what a person or model inferred.
- Import fills provenance itself from a finding's evidence; researchers are never asked for it (`PROVENANCE` and `TIER` in `expectations.py`). The evidence tier (`source_type`, `evidence`) is paired by a CHECK constraint, and `aggregator` or `prior_research` sources may only be `claimed` (`0046`).
- The SQL tools derive which catalogued tables expose citations from the presence of `source_url`/`source_name`/`fetched_at` (`PROVENANCE_COLUMNS`), so a table that follows the convention gets its sources surfaced without another edit.

### Public read SQL and private sources

Not every reader of these columns is the SQL tool. The public Registry list and profile pages share one set of SQL fragments in `backend/app/repositories/public_sql.py`, used by `registry.py`, `profile_facts.py`, `partner_groups.py` and `news_stories.py`, so the list and the profile say the same thing by construction.

- **Private sources are hidden in SQL.** Staff datasets and the Doc Vault cite a synthetic URL on the reserved domain `sangam.invalid` (`PRIVATE_SOURCE_DOMAIN` in `backend/app/ingest/source_guards.py`). `public_sql.is_private_url` is the SQL twin of Python's `is_private_source`: it extracts the host with a regex and tests it against that domain or a subdomain. `public_url` and `public_name` return `NULL` for such a row (a sheet's title names the sheet), and `public_text` drops a note or quote whole if it mentions the domain. Every URL a public query selects goes through these. The SQL form is deliberately a little stricter than the Python check for a scheme-less `x.sangam.invalid`.
- **Shared predicates.** `OPEN_CALL` (`status = 'open'` and no deadline or one not yet past, using `current_date`), `PUBLIC_STORY` (`visibility = 'public'` and `is_news`), `STORY_CHANNEL` (social versus press by source type) and `story_counts`, `entity_tags` and `entity_sdgs` keep the Registry's filters and counts consistent. The `Asia/Kolkata` date in the RFP feed is a separate computation in `repositories/rfps.py`.
- **Caller pool versus owner pool.** `registry_rows(pool, owner)` reads orgs, funders, places, tags, programmes, partner counts, open calls, CSR years and story counts on the caller pool, so RLS and the `is_public`/`visibility` filters decide which entities appear. Two reads go through the owner pool so the list reads the same for every viewer: which registration types an org has on file (`ON_FILE`: current, registered or provisional, public or not) and `entity_research` counts (staff-only; `GET /api/registry` shows only a run count and latest date and treats a failure there as a hint to drop, not an error). The shared `IDENTIFIERS` query is likewise written for the owner pool: a non-public registration is listed as on file with its number and detail nulled and `number_withheld` set.

## Storage buckets

Documents' bytes live in Supabase Storage, not Postgres; `documents.storage_path` is `<bucket>/<key>` (`storage.qualify`/`split`). `backend/app/integrations/storage.py` is the only module that talks to Storage and uses the service-role key, which bypasses RLS and so stays server-side; the browser only receives short-lived signed URLs.

| Bucket | Created by | Holds | Key shape |
|---|---|---|---|
| `source-archive` | `0020` | Documents Import fetched, plus rendered briefs at `entities/<slug>.md`; 50 MB limit | at fetch `<sha256(url)[:12]>/<sha256(bytes)>-<name>`, after promotion `funders/<slug>/<year>-<name>` |
| `org-vault` | `0020` | What an organisation uploads to its Doc Vault, private by default; 50 MB limit | `<org_id>/<uuid4>-<name>` (the leading `org_id` is what the storage RLS policy reads) |
| `staff-sources` | `0032` | Staff-uploaded workbooks, readable only by staff; 100 MB limit | `<registry key>/<sha256(file name)[:12]>.xlsx` |

Behaviour to rely on:

- **Buckets are global, not per environment.** A local backend with Supabase keys writes into the same cloud buckets as staging or production. Local databases and cloud buckets can therefore disagree about which objects a row refers to.
- **Two keys for the archive.** At fetch time no funder id exists, so the key is derived from the URL and content hash (a republished PDF adds a version rather than overwriting what a finding was read from). At promotion the object is moved to a readable per-entity key (`move`/`catalog_key`); an object still under a hash folder was downloaded but never cited. `app/ingest/reshelve.py` re-runs the rename if the scheme changes.
- **Storage is optional and non-fatal.** With `SUPABASE_URL` or `SUPABASE_SERVICE_KEY` unset every call is a no-op that logs once; helpers return `None`/`False`/empty on any HTTP failure instead of raising, so an outage never aborts research or promotion and callers store a null `storage_path`. The exception is `read`, which raises on Storage errors and returns `None` only for a missing object.
- Uploads are checked against the bucket ceiling before the bytes go out; a duplicate key counts as success (Supabase reports it as HTTP 400 with a 409 body); `split` rejects empty, `.` or `..` path segments and unknown buckets so a stored path cannot be turned into a cross-bucket URL.
- Vault uploads go browser to Storage via `signed_upload_url` (valid two hours), keeping large files off the backend; `content_hash` is computed server-side afterwards from the bytes read back, and `stat` confirms an object landed before a `documents` row claims it.

## Neo4j graph: optional and rebuildable

Postgres is authoritative; Neo4j (via Graphiti, `backend/app/integrations/graphiti.py`) is a derived index. The graph is enabled only when both `NEO4J_URI` and `OPENAI_API_KEY` are set (`graph_status`); otherwise `open_graph` logs the reason and returns `None`, and `graphiti_core` is imported lazily so the app boots without it. The lifespan opens the graph after the catalog check and closes it on shutdown.

`make graph-seed` (`python -m seed.graph_seed`) rebuilds it: it reads funder profiles, two named orgs' registrations, `funder_activity` partner lines and the `score_adjustments` vetting log from Postgres, turns each into a deterministically named Graphiti episode, and ingests them with `add_episode`. Because episode names are deterministic and every episode comes from rows, the graph can always be dropped and recreated from the database. The invariant is that **nothing may live only in the graph**. `graph_ingest_log` is an infrastructure table kept out of the SQL catalog, and `make db-reset` also wipes Neo4j's volume.

## Copying data between databases

`python -m app.db.replicate` (sibling of `migrate.py`) copies contents, not shape: target is `DATABASE_URL`, source is `REPLICATE_SOURCE_URL`. It refuses to run if the two column sets differ ("run the migrations first"), orders tables parents-before-children from foreign keys, and, with `--yes` (otherwise it is a dry run), deletes the target's rows for those tables and binary-`COPY`s the source's rows in a single transaction, then resyncs identity sequences and compares counts. It excludes `schema_migrations` and the checkpoint tables. The source is authoritative and ids are preserved so no foreign key needs remapping.

## Tests that matter

- `backend/tests/test_migration_integrity.py` (marked `integration`, skips when the compose Postgres on port 5433 is unreachable) checks that restored research data survived: at least 96 `documents`, 29 `graph_ingest_log` rows, stable seed-order ids for the first orgs and funders, an advanced `documents` identity sequence, and seeded v2 content. It is a guard on preserved data rather than a schema check.
- `backend/tests/test_sql_catalog.py` guards what the catalog must not expose.
- `backend/tests/test_rls.py` and `test_caller_pool.py` exercise policies and the caller pool against a real database; see [Auth, roles and RLS](auth-roles-rls.md).
