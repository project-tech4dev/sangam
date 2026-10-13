# Import: every funder programme is saved with its themes, or says why not

## Context
A funder programme's themes are saved only when the researcher happens to tag it. Nothing checks this.
On staging, 53 of 137 funder programmes have no `program_tags` row (84 tagged); CSO side 42 of 55.
Tags already flow end to end when present: `ProgramFinding` (via `Tagged`) → `promote` → `program_tags`,
and open PR #172 copies them into `funder_tags` when the funder has none. So the gap is a missing
**check in Import**, not storage. No rubric (Funder Match) change; the user ruled that out.

## Change: a new pass criterion for the researcher's save
Example the check enforces: Axis "Mission 4 Million" saved with `themes: [climate-adaptation…]` and a
`tag_note` passes; "Ecosystem Action" saved with no themes fails unless the save carries
`Gap(concept="program", field="themes", reason="not_stated", detail="Ecosystem Action: AR 2024-25 p.84 names it, describes no activity")`.

1. **Grader sees it** — `backend/app/ingest/middleware.py::_digest`: add `programs_untagged` (names of
   `program` findings with empty `themes`) and include `field` in each gap.
2. **Grader judges it** — `backend/app/ingest/prompts/research_rubric.md`: criterion 6: every name in
   `programs_untagged` has a gap with concept `program`, field `themes`, naming that programme and the
   source read. Otherwise `needs_revision` (one revision is already allowed; tagging uses pages already read,
   so it stays within "do not ask for more research").
3. **Researcher is told** — `backend/app/ingest/prompts/entity_researcher.md` item 9: tag every programme
   from its description; when the source does not describe the work, record that gap instead.
4. **Coverage shows it** — `backend/app/ingest/coverage.py`: the `program` line's missing text adds
   "N of M programmes have no theme" (from findings, plus the gaps' details), so `coverage_report` and the
   chat report show it.
5. **Funder side of storage** — merge PR #172 (`write_funder_tags_from_programs`) first, or with this;
   nothing else to store.

## Verification
- `pytest -m "not integration"` (fix any test pinning `_digest`'s keys or the rubric text) and `ruff check`.
- `_digest` on Axis's 12 Oct saved payload (from staging, read-only) lists the untagged programmes.
- `coverage.compute` on that row prints the new "N of M programmes have no theme" text.
- Optional, costs money: `make evals TAG=import` and check the funder canary's programmes all carry themes or gaps.
