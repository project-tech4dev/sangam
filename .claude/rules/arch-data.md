---
paths:
  - "db/**"
  - "seed/**"
  - "backend/app/repositories/**"
  - "backend/app/db/**"
  - "backend/app/agent/tools/sql/catalog.py"
---

# Data

Before changing the schema or SQL, read `docs/ARCHITECTURE.md` §7 (Data) and §8 (Auth, roles and RLS).
Schema changes go only in a new `db/migrations/*.sql`. A new table needs RLS policies, and to reach Ask it must be added to `catalog.py` (a security decision).
Add the migration to `docs/HISTORY.md` and §7 in the same PR.
