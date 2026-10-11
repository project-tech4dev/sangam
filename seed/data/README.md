# Seed data provenance

Vendored from the `org-grant-intelligence` repo @ commit `414cd69` on 2026-09-21.

- `darpan/*.json` — from `ngos/darpan/`, scraped from ngodarpan.gov.in (8 NGOs, core-cohort-2026)
- `gdelt/*.csv` — from `gdelt-monitoring/data/` (GDELT news articles; filename = query topic)
- `rubrics/*.json` — hand-transcribed from `hand-vetting/Funder_NGO_Fit_Rubric_KABIL.md` (v1),
  `hand-vetting/Funder_NGO_Fit_Rubric_KABIL_v2.md` (v2),
  `ngos/KABIL/KABIL_Funder_Fit_Scores_v1.md` (v1 scores + override log),
  and `hand-vetting/KABIL_Funders.md` (funder metadata)

## geography/

From the Local Government Directory (lgdirectory.gov.in), via the daily archive at
https://ramseraph.github.io/opendata/lgd/ — `states.31May2026.csv` and `districts.31May2026.csv`.

- `lgd_states.csv` — the 36 states and union territories, with names as `app/ingest/geography.py` spells them
- `lgd_districts.csv` — 784 districts, names upper-cased as `locations` stores them
- `district_aliases.csv` — other names sources use (renames, long forms), each with why

To refresh: take a newer pair from the archive, regenerate the two CSVs, add any renamed district's old name to the aliases, and run `make locations-seed`.
