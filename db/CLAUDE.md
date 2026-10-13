# Data

How this works today is `docs/ARCHITECTURE.md` §7 (data) and §8 (auth, roles and RLS).
- Schema changes go only in a new `db/migrations/*.sql`.
- A new table needs RLS policies. To reach Ask it needs a line in `backend/app/agent/tools/sql/catalog.py`, which is a security decision.
- Add the migration to `docs/CHANGELOG.md` and §7 in the same PR.
