## What and why

<!-- What changes for a user or a developer, and why. Link the issue or the plan in docs/features/. -->

## How it was checked

<!-- Commands run, screens tried (and at phone width for UI), eval cases. -->

## Checklist

- [ ] Tests for the deterministic code this changes
- [ ] `make wiki-update` if a tool, table, route or flow changed (never hand-edit `openwiki/`)
- [ ] `docs/ARCHITECTURE.md` if a rule changed; a `docs/CHANGELOG.md` line if it ships
- [ ] The design system updated in the same PR if a component, token or recreated screen changed
- [ ] `npm run build` passes if the frontend changed
- [ ] A new migration, not an edit to `db/init/`, for any schema change
