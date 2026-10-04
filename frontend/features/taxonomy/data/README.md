# Taxonomy data — copies, not the source

`themes.json` and `common.json` are copies of `features-plans/data-model/seed/data/taxonomy/`,
which is the source of truth. The `/resources/taxonomy` page reads them at build time, because
the frontend container mounts only `frontend/`.

Edit the originals, then copy them here:
`cp features-plans/data-model/seed/data/taxonomy/{themes,common}.json frontend/features/taxonomy/data/`.
`make smoke` fails while the two disagree.

The domain trees (`livelihoods.json`, `education.json`, `health.json`) stay in `features-plans/`
as a parked, optional second layer; the page no longer shows them. When the taxonomy is loaded
into Postgres (`tags` of kind `theme`), the page should read the API and this folder goes.
