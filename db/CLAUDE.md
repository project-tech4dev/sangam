# Data

Facts: `openwiki/architecture/data-and-migrations.md`, `openwiki/workflows/writing-a-migration.md`, `openwiki/architecture/auth-roles-rls.md`. Rules: `docs/ARCHITECTURE.md` §7 and §8.
- Schema changes go only in a new `db/migrations/*.sql`, with the new table's RLS policies.
- To reach Ask a table needs a line in `backend/app/agent/tools/sql/catalog.py`, which is a security decision.
- Add the migration to `docs/CHANGELOG.md`, then run `make wiki-update`.
