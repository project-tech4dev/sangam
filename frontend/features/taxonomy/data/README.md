# Taxonomy data — copies, not the source

These four files are copies of `features-plans/data-model/seed/data/taxonomy/`, which is the
source of truth. The `/taxonomy` page reads them at build time, because the frontend container
mounts only `frontend/`.

Edit the originals, then copy them here: `cp features-plans/data-model/seed/data/taxonomy/{common,livelihoods,education,health}.json frontend/features/taxonomy/data/`.
`make smoke` fails while the two disagree.

When the taxonomy is loaded into Postgres (the `tags` table, `kind` domain/cell), the page should
read it from the API instead and this folder goes.
