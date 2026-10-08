# Migrations

Forward-only SQL migrations, applied by `backend/app/db/migrate.py`.

```
make migrate-status     # what would run
make migrate            # apply pending migrations
```

Both commands read `DATABASE_URL` from the compose environment, so they work
unchanged against the bundled Postgres and against a managed one.

## Conventions

- Filename: `NNNN_short_name.sql` (`0001_`, `0002_`, …). Order is filename order.
- One logical change per file. Each file runs inside a single transaction, so a
  failure leaves nothing half-applied and stops the run.
- **Additive by default.** Prefer `ADD COLUMN`, new tables, and backfill
  statements. A destructive change (`DROP`, type narrowing, `NOT NULL` on an
  existing column) needs a note in the file explaining the data situation that
  makes it safe.
- `org_identifiers` is granted by column (0033), so a new column on it needs an explicit
  `GRANT SELECT (col) ON org_identifiers TO anon, authenticated` to be readable.
- Never edit a file after it has been applied anywhere — the runner records a
  checksum and reports drift. Write a new migration instead.

## Relationship to `db/init/`

`db/init/02_schema.sql` is the **baseline** for a brand-new database: it runs
automatically on the bundled container's first boot, or via
`make db-init-remote` for a managed instance. Everything that changes the
schema *after* that baseline belongs here.

The baseline is deliberately not rewritten as migration `0000`, so a fresh
install stays a single fast `CREATE TABLE` pass rather than a replay of every
historical change.
