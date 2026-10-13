---
paths:
  - "backend/app/ingest/**"
  - "backend/app/api/routes/ingest.py"
  - "frontend/features/ingest/**"
  - "frontend/app/(agent)/import/**"
  - "frontend/features/registry/brief/**"
---

# Sangam Import / Scout

Before changing this code, read `docs/ARCHITECTURE.md` §4 (Sangam Import / Scout). It covers the agents and their tools, one turn end to end, the brief as the record, `promote()`, the writer and matcher, middleware, skills and access.
Where `docs/INGEST.md` disagrees with §4, §4 is right. If a change alters any fact in §4, update §4 in the same PR.
