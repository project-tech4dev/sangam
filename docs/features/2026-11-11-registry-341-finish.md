# Finish #341: the Registry's last slow spots

One PR, four small changes, each against one of #341's "Done when" boxes. The bigger
one-query Registry page stays a separate PR.

| # | Change | Where | Done-when box |
|---|---|---|---|
| 1 | `research_counts` joins on equalities (resolved id, or slug while unresolved) instead of one `CASE … OR`, with indexes on `resolved_org_id` and `resolved_funder_id` | `repositories/registry.py`, `db/migrations/0057_entity_research_resolved_indexes.sql` | no per-row rescans |
| 2 | `loading.tsx` for the Registry and both profile pages, from existing classes (no new tokens, so no design-system change) | `frontend/app/registry/**/loading.tsx` | a click shows something at once |
| 3 | `resolve_principal` reuses a user's row for 60 s instead of reading `users` on every request | `core/security.py` | (small item 5) |
| 4 | Time `/api/registry`'s work at 2,000 entities on local Postgres and record it | PR body, CHANGELOG | under 300 ms warm |

Not doing: a shared cache for signed-in visitors (#341 step 4). The page differs per caller (RLS and
staff-only research counts), so caching it needs the research split out first; it is not a Done-when box.

Example for 1: a funder researched twice under its slug before Import resolved it, then once after.
Before, Postgres compared every `entity_research` row against every entity on the page; now the
resolved run is found through `resolved_funder_id`'s index and the two earlier runs through the
`(slug, researched_on)` unique index. All three runs are still counted.

Tests: an integration test pins the three ways a run is counted (resolved, unresolved by slug,
`wrong_entity` never) for an org and a funder; a unit test pins the user cache's hit, expiry and key.
