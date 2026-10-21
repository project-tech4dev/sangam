---
type: workflow
title: Writing and Applying a Migration
description: Step-by-step for adding a schema change in db/migrations/ - file naming, transaction and checksum rules, RLS and grants for new tables, the separate SQL-catalog decision, and applying locally and then to staging after a backup.
tags: [migrations, database, rls, sql-catalog, workflow, staging]
sources:
  - id: openwiki-source-7faba850789bc67a49b79a3f
    resource: repo://backend/app/agent/tools/sql/catalog.py
  - id: openwiki-source-01e57798bc5bab328d91b9b3
    resource: repo://backend/app/agent/tools/sql/executor.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
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
  - id: openwiki-source-e5554658094627ddf1bb9942
    resource: repo://backend/tests/test_cov_db_migrate.py
  - id: openwiki-source-c19bf12e33dd13dd52164b8e
    resource: repo://backend/tests/test_migration_integrity.py
  - id: openwiki-source-5871ea1c2ab913bbd11be84f
    resource: repo://db/CLAUDE.md
  - id: openwiki-source-a63cf999b1937db913f804d5
    resource: repo://db/migrations/0025_table_grants.sql
  - id: openwiki-source-a51b4e8aa8968bfd9e155474
    resource: repo://db/migrations/0027_rls.sql
  - id: openwiki-source-d1c5532960252357e823b43e
    resource: repo://db/migrations/0047_document_links.sql
  - id: openwiki-source-3d121c1ca466c424ca2b4936
    resource: repo://db/migrations/0048_proposal_work.sql
  - id: openwiki-source-d2d39b77b74bd31e2a50555d
    resource: repo://db/migrations/0049_rfp_match_saved.sql
  - id: openwiki-source-2e81fea55b6132d8610d3e6a
    resource: repo://db/migrations/0050_proposal_stage_shift.sql
  - id: openwiki-source-82b4a7ca109f9768db60ccbf
    resource: repo://db/migrations/README.md
  - id: openwiki-source-093cd3e20819d97ab4faddda
    resource: repo://db/scripts/truncate_all.sql
  - id: openwiki-source-b79fbbd921df689b4bbdc82f
    resource: repo://docker-compose.yml
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-10-21T19:40:05.698Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-10-21T19:40:05.698Z
---

# Writing and Applying a Migration

Every schema change after the baseline is a new forward-only SQL file in `db/migrations/`. Nothing applies it for you on a managed database: locally `make up` runs it, but staging is migrated only when someone deliberately runs `make migrate ENV=staging`, after taking a backup. For the table groups and the baseline/migration split see [Data and Migrations](../architecture/data-and-migrations.md); for what the policies mean see [Auth, Roles and RLS](../architecture/auth-roles-rls.md).

## The rules in one place

- **Schema changes go only in `db/migrations/*.sql`.** `db/init/02_schema.sql` is the baseline for a brand-new database and is not edited for later changes ([README](../../db/migrations/README.md), [db/CLAUDE.md](../../db/CLAUDE.md)).
- **A new table needs RLS policies and an explicit grant.** Adding it to the agent's SQL catalog is a separate security decision (see below).
- **Never edit a file once it has been applied anywhere.** Write a new migration instead.
- **Record the change** in `docs/CHANGELOG.md`, then run `make wiki-update` so the generated wiki pages that cite changed sources are refreshed (per `db/CLAUDE.md`). Do not hand-edit generated `openwiki/` pages. The rules themselves live in `docs/ARCHITECTURE.md` §7 (Data) and §8 (Auth, roles and RLS); edit those only if a rule changes, not for an ordinary schema change.

## 1. Create the file

Name it `NNNN_short_name.sql`, taking the next number after the highest in `db/migrations/` (currently `0050_proposal_stage_shift.sql`, so the next file is `0051_…`; re-list the directory before you pick, since another branch may have taken it). Order is plain filename order, because the runner sorts `*.sql` by name. The runner records the *full stem* as the version, so two files may share a prefix without a primary-key clash: `0044_news.sql` and `0044_one_read_policy_and_fk_indexes.sql` both exist. Still, pick the next free number rather than relying on that.

Conventions from the migrations README:

- One logical change per file.
- **Additive by default**: `ADD COLUMN`, new tables, backfills. A destructive change (`DROP`, type narrowing, `NOT NULL` on an existing column) needs a comment in the file explaining the data situation that makes it safe. `0031_funder_consolidation` and `0034_grants_into_funder_activity` are the precedents for table-dropping migrations: they copy every row to its new home first.
- The whole file runs inside a single transaction, so write it so that a failure at any statement leaves nothing half-applied. Avoid statements that cannot run in a transaction.
- `org_identifiers` is granted by column (since 0033). A new column on it is unreadable by `anon`/`authenticated` until you add `GRANT SELECT (col) ON org_identifiers TO anon, authenticated`.

## 2. RLS and grants for a new table

Two layers decide whether a role can read a table, and a new table must satisfy both:

1. **Grant.** `0025_table_grants.sql` revoked everything from `anon` and `authenticated` and also revoked *default privileges* for tables and sequences created later. A table created afterwards is therefore closed until your migration grants it. Add `GRANT SELECT ON <table> TO anon, authenticated` for public data, `TO authenticated` only for signed-in data, or nothing for staff/infrastructure tables. Writes the API makes as the caller need explicit `GRANT INSERT/UPDATE` (and `GRANT USAGE` on the sequence); import and research write as the owner.
2. **Policy.** `0027_rls.sql` enabled RLS on every table that existed at that time with a loop, so later tables do not inherit it. Each new table needs `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and at least one policy, wrapping `app.*` calls as `(SELECT app.is_staff())` so Postgres evaluates them once per query. With RLS on and no policy a role reads nothing.

`0047_document_links.sql` is a compact worked example: it creates the table with indexes on its foreign keys, enables RLS, grants `SELECT` to `anon, authenticated`, adds a `document_links_read` policy that is only as visible as the parent `documents` row (via `EXISTS`), and attaches the `log_catalog_write` trigger so Import's undo covers it. Staff-only tables (`promotions`, `catalog_writes` in `0041`) use `FOR SELECT USING ((SELECT app.is_staff()))` with no grant to the public roles.

`0048_proposal_work.sql` is the recent example for changing an *existing* table. It adds two `NOT NULL DEFAULT '{}'::jsonb` columns (`work`, `summary`) to `proposals`, so existing rows backfill without a rewrite step; it tightens who may write with `ALTER POLICY` on `proposals_insert`, `proposals_update` and `documents_insert` rather than dropping and recreating them; and it ends with a `DO $$` guard, repeating `0027`'s, that raises an exception if any table readable by `anon` or `authenticated` has no read policy. Because the whole file is one transaction, that guard aborts and rolls back the entire migration if a policy is missing. Note that `proposals` is in the catalog's `KNOWN_EXCLUDED` list, so adding columns to it needed no `catalog.py` change.

`0049_rfp_match_saved.sql` is the smallest kind of schema change: an RFP Watch org may now *save* a call, so it widens the `status` CHECK on `rfp_matches` to `('flagged', 'saved', 'reviewed', 'dismissed')`. A CHECK cannot be altered in place, so one `ALTER TABLE` drops `rfp_matches_status_check` and adds it back with the new list. It needed no grant or policy work because the table already has `GRANT UPDATE … TO authenticated` (0025) and the `rfp_matches_update` policy (0027), which the PATCH `/api/rfps/{id}/matches/{org_id}` route uses; the catalog's `status` column lists the same four values in `values=(…)`, so a value-list change like this is also a `catalog.py` edit.

`0050_proposal_stage_shift.sql`, the latest, is a pure data migration with no DDL: a wizard step was inserted as step 3, so one `UPDATE proposals` adds 1 to `work.stage` (and to the copy in `summary.stage`, when present) for every row at stage 3 or later. It relies on the runner's once-only guarantee, since running it twice would shift the stages twice; that is another reason never to re-run or hand-apply a recorded file.

Choose the policy by the kind of table: public rows, a child that follows its org or funder, signed-in-only, or staff-only. The existing rules in `0027` are the patterns to copy.

### Which connection will read it

The migration runner opens its own connection from `DATABASE_URL`, and the shared pool connects with the same owner credentials, so neither is subject to the grants and policies you write. Whether your policy is ever exercised depends on how the code reads the table (`backend/app/db/pool.py`):

- **`PoolDep` (routers) is a `CallerPool`.** Each connection is one transaction that first runs one `SELECT set_config(...)` that sets `role`, `request.jwt.claims` and `statement_timeout` (default `db_statement_timeout_ms`, 15000 ms), so the rest of the transaction runs as `anon` or `authenticated` with the token's claims (`anon` and empty claims when the request has no user). All three settings are `SET LOCAL`, so they end with the transaction, and the connection returns to the pool as the owner. A route that reads or writes your new table therefore needs the grant *and* the policy, or it fails or returns no rows. A slow migration-added query also hits that timeout, so index foreign keys.
- **`OwnerPoolDep` is the owner pool**, the plain shared pool. Identity code (who the caller is, `users` and `threads` rows) takes it, as do staff or Import routes and a few routes that need a read the caller could not make. It ignores RLS, so a missing policy will not show up there. Tests keep a real database by overriding `get_pool`.
- **Ask Sangam's SQL tool also runs as the caller.** `ask_access` sets the `agent_caller` context variable per `/agent` request, and the executor calls `set_caller` inside a read-only transaction; with no caller set it runs as `anon`. Import keeps the owner, since it writes the catalog.

This is why the policy matters even for a table you only plan to read from the agent: catalogued rows are filtered by RLS and grants for whoever is asking.

## 3. Decide separately about the SQL catalog

`backend/app/agent/tools/sql/catalog.py` is the allowlist of tables and columns the agent's SQL tool may read. **Adding a table or column there is a security decision, not a mechanical follow-up to the migration.** The tool queries as the caller, so grants and RLS apply, but the catalog also decides what the model is told exists and how it is cited. Tables holding private per-org data (`proposals`, `funder_matches`, `vault_research`) stay in `KNOWN_EXCLUDED` regardless. A new table:

- stays invisible to the agent by default;
- is only logged at INFO at boot as "not readable by the SQL tool and not declared as excluded" until someone either adds it to `_TABLES` or lists it in `KNOWN_EXCLUDED` (where private, per-org, chat-history and infrastructure tables live, each with a reason).

If you do add it, supply a `Table` with a one-line description, primary key, columns, foreign keys and `defects` describing known data problems. `_self_check()` runs at import and rejects a catalogued table with no columns or primary key, or foreign keys pointing at tables or columns not in the catalog.

### Drift fails the boot

`verify_against_db()` compares the catalog with `information_schema.columns` and with column privileges. In the backend lifespan (`app/core/lifespan.py`), any problem it returns makes `_verify_sql_catalog` log "SQL catalog drift" and raise `RuntimeError`, so the app does not start. It reports a problem when a catalogued table is missing, when a catalogued column is missing, or when a catalogued column cannot be read by a role: `authenticated` must be able to `SELECT` every catalogued column (the chat runs as the caller, so one denied column fails with 42501 for everyone), and `anon` may be shut out of a whole table (as with `rfp_matches`) but not out of part of one, because that breaks `SELECT *`. The check is otherwise one-directional:

| Situation | Effect |
| --- | --- |
| Catalog lists a table/column the DB lacks (code deployed before the migration, or a column renamed/dropped in a migration but left in the catalog) | Backend refuses to boot |
| A catalogued column is not `SELECT`-able by `authenticated`, or by `anon` on a table it reads only in part (for example a new column on a column-granted table such as `org_identifiers` with no `GRANT SELECT (col)`) | Backend refuses to boot |
| DB has extra tables not in the catalog or `KNOWN_EXCLUDED` | INFO log only |
| DB has extra columns on a catalogued table | Not checked |

Consequences for ordering: a migration that adds a table does not break the running backend, but a catalog edit shipped before the migration reaches a database does. Conversely, **dropping or renaming a catalogued column or table requires updating `catalog.py` in the same change**, and the migration must be applied before the new backend boots. This is also why `make up` migrates the bundled Postgres *before* starting the backend: several catalogued tables exist only through migrations, so a clean checkout would otherwise fail at boot.

## 4. Tests and docs to update

- `backend/tests/test_sql_catalog.py` checks catalog contents (readability of excluded tables and withheld columns, `SELECT *` expansion, citation kinds, defect wording). If you changed `catalog.py`, update or extend it, and run it.
- `backend/tests/test_migration_integrity.py` is an integration test against the live compose Postgres (`localhost:5433`, or `TEST_DATABASE_URL`); it is skipped when the database is unreachable. It asserts preserved row counts and seeded content (documents, `graph_ingest_log`, specific org/funder ids, funder activity, contacts). If a migration legitimately changes such data it will need adjusting; it is not a general schema test and does not verify RLS or grants.
- `backend/tests/test_cov_db_migrate.py` covers the runner itself: a fake connection for apply order, drift, `--status`, a failing file stopping the run, and a missing `DATABASE_URL` or directory, plus an integration test in a throwaway Postgres schema that runs the runner twice. Touch it only if you change `migrate.py`.
- Check any code that selects the changed columns (repositories, routes, seeds). Seeds that write new columns depend on the migration (`seed.taxonomy_seed` needs `0002_taxonomy.sql`), which is why local `make seed` runs `migrate` first.
- `docs/CHANGELOG.md`, then `make wiki-update`. Touch `docs/ARCHITECTURE.md` §7/§8 only when the change alters a rule rather than a fact.

## 5. Apply locally

```bash
make migrate-status   # list applied (=), drifted (!) and pending (+) files
make migrate          # apply pending migrations
```

Both targets run `python -m app.db.migrate` in a one-off backend container (`docker compose run --rm --no-deps backend`), reading `DATABASE_URL` from the compose environment. What the runner (`backend/app/db/migrate.py`) does:

1. Creates `schema_migrations (version, checksum, applied_at)` if missing.
2. Lists `*.sql` in `MIGRATIONS_DIR` (default `/srv/db/migrations`, the mounted `db/migrations`) in sorted order.
3. For each file already recorded, compares a SHA-256 checksum prefix. A mismatch prints `! <version> - DRIFT: file changed after it was applied`. This is a warning, not a failure, and the file is skipped.
4. Runs each pending file in its own transaction together with the `INSERT INTO schema_migrations`. On any error it rolls back that file, prints `x <version> FAILED`, and stops: later files are not attempted. Earlier files stay applied.
5. `--status` (via `make migrate-status`) only reports; it never writes migrations, though it does create the ledger table if absent.
6. Only when the SQL step returned 0 (all applied, or nothing pending, or status), `main()` then migrates LangGraph's checkpointer tables with `PostgresSaver.setup()` and prints `checkpointer at v<N>`. With `--status` it only reads `checkpoint_migrations` and reports `up to date` or `pending`. A failed SQL file therefore also skips the checkpointer step. This lives in the runner, not at boot, so a langgraph upgrade migrates once and on purpose: the backend's `open_checkpointer` does no DDL and raises `RuntimeError` ("…run make migrate") if the database is not at `CHECKPOINT_VERSION`.

Fix a failed migration by correcting the file (it was never recorded, so editing it is safe) and re-running. If you see DRIFT, someone edited an applied file: restore it and put the change in a new migration.

`make db-clean` (which runs `db/scripts/truncate_all.sql`) empties every public table except `schema_migrations`, so it keeps the schema and the ledger and never causes migrations to replay; it then restores the local dev user. A new table needs nothing added to that script.

After applying, run `make up` (or restart the backend) and confirm it boots; a "SQL catalog drift" error means the catalog and database disagree. Run `cd backend && pytest tests/test_sql_catalog.py`, plus `tests/test_migration_integrity.py` with compose Postgres up.

## 6. Apply to staging

`ENV=staging` points tooling at the managed database through the `STAGING_DB_*` block in `.env`; it deploys nothing (see [Environments](../operations/environments.md)). Migrating it is deliberately a separate, explicit step: `make up` and `make seed` skip it for staging because a shared instance can be many migrations behind, which is a back-it-up-first operation.

1. **Back up first.** `make db-backup` is local-only and refuses other `ENV` values. For staging use the provider's snapshots (the Makefile says so) and confirm one exists.
2. Check the target: `make db-url ENV=staging` prints the resolved connection string, including the password, so do not paste it anywhere.
3. `make migrate-status ENV=staging` to see what is pending and whether any file shows DRIFT.
4. `make migrate ENV=staging`.
5. Deploy the backend code that matches the schema; see [Deploying by Hand](deploying-by-hand.md). Migrate first when the new code or catalog needs the new schema, because the backend will not boot with a catalog that lists missing tables or columns. The reverse hazard exists for destructive migrations: old code still reading a dropped column breaks until the new code is live, so keep changes additive where you can.

`make db-init-remote` and `make db-push-remote` are different tools: they build or copy a whole database into an *empty* managed instance and are not part of ordinary schema changes.

## Checklist

- [ ] New `db/migrations/NNNN_name.sql`, one logical change, additive or justified in a comment
- [ ] New tables: `ENABLE ROW LEVEL SECURITY`, policy, explicit `GRANT`, FK indexes
- [ ] New `org_identifiers` columns: column-level `GRANT SELECT`
- [ ] Catalog decision made (`_TABLES` entry or `KNOWN_EXCLUDED`) and `catalog.py` consistent with the schema
- [ ] `make migrate-status`, `make migrate` locally, backend boots
- [ ] Tests run; `docs/CHANGELOG.md` updated and `make wiki-update` run
- [ ] Staging: backup taken, `make migrate ENV=staging`, then deploy
