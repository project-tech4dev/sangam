# Taxonomy data — copies, not the source

`themes.json` and `common.json` are copies of `seed/data/taxonomy/`, which is the source of truth
and what `python -m seed.taxonomy_seed` loads into `tags` and `tag_links`. The `/resources/taxonomy`
page reads these copies at build time, because the frontend container mounts only `frontend/`.

Edit the originals, then copy them here and to Import's vocabulary:
`cp seed/data/taxonomy/{themes,common}.json frontend/features/taxonomy/data/` and
`cp seed/data/taxonomy/{themes,common}.json backend/app/ingest/data/`.
`make smoke` fails while the two disagree.

The domain trees (`livelihoods.json`, `education.json`, `health.json`) stay in `features-plans/`
as a parked, optional second layer; the page no longer shows them. Once the page reads the taxonomy
from the API, this folder goes.
