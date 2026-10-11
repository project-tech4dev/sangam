# Funder Match v2: theme compares the taxonomy

**match-v1** judged theme on NGO Darpan `sector` tags (plus `csr_sector` and the 0036 crosswalk).
Those 40 tags never reached the `/resources/taxonomy` page, carry near-duplicates ("education" and
"Education & Literacy"), and no org, programme or call pointed at them. **match-v2** compares the
taxonomy the page shows. Only the theme criterion and the rubric version change.

## What each side's themes are

- **Org**: its `org_tags` and every programme's `program_tags`, of kind `domain`, `theme`,
  `sub_theme` or `csr_sector`.
- **Funder**: its `funder_tags`, plus the `domain_tag_id`, `theme_tag_id` and `csr_sector_id` of
  every `funder_activity` line. A classified spend line says what the funder funds.
- Each tag brings its ancestors (sub-theme → theme → domain) and a sub-theme brings the Schedule VII
  clauses `tag_links` gives it. So an org tagged *Institution building* meets a funder tagged
  *Economic empowerment of SHGs*, and meets a CSR filing under clause iii.
- A theme reaches every clause its sub-themes do, so a theme-level tag still meets a clause-only funder.
- **Others never counts as a shared area.** Relief, administration and unlabelled spend are filed
  there, so a side whose only theme is the Others domain is "not recorded", not a mismatch.
- `sector` tags are left in the database and never read.

## Points

The finest grain both sides share scores (`rubric.THEME`):

| Shared | Points | Status |
|---|---|---|
| a theme or sub-theme | 25 | met |
| a Schedule VII clause only | 15 | partial |
| a domain only | 10 | partial |

A clause alone is partial on purpose: clause ii is all of education and livelihoods. A funder whose
only themes are its filed clauses therefore never meets theme until its spend lines carry a theme.

The programme rule is unchanged: when no programme carries the shared grain the points are capped at
`THEME_NO_PROGRAMME` (15), with the action to raise them. Lenses are not scored in v2.

## Also in this change

- Environment and Others gain themes (added 2026-10-11), so a spend line in either
  domain may carry a theme; `NO_THEMES` and its check in `research_records.py` are gone.
- Five population groups added: people living with HIV, transgender persons, survivors of violence
  and trafficking, children in need of care and protection, people displaced by conflict or disaster.

Saved runs carry their `rubric_version`; v1 runs stay as they were, and a new run is v2.
