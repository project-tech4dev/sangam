# Import M2: the brief is the record, and every run merges into it

Second of the stacked PRs in `2026-10-13-import-researcher-contract.md`, on M1's branch.

## Decision (13 Oct 2026)
The record is **the same brief #192 publishes** — `briefs/<slug>.md` in the `source-archive` bucket, the
file the funder page reads. No table and no version files: each save reads it, merges, and writes it back.

## What changes
1. **Each fact carries its data.** The finding's line ends in a hidden block with the typed finding,
   `<!-- fact {"concept":"programme_spend","program_name":"Rural Livelihoods",…} -->`. The page already
   strips comments, so it reads the same; M3 promotes from these blocks.
2. **A save merges into the brief, never replaces it.** `brief.build(rows, unplaced)` reads the current
   brief's blocks, then lays every research row over them, oldest first, keyed by `fact_key`:
   - a fact found again replaces the old one, **unless the old one's source is stronger** (evidence tier,
     then confidence) — a claimed web sentence never displaces an audited figure;
   - a fact no later run found stays. Example: two Axis runs on the same day share one row, so the
     second used to drop the first's 40 findings from the page; the brief now keeps them.
   - a `wrong_entity` row's findings are about another organisation and never enter the brief.
3. **Unplaced facts live here.** M1's `unplaced` (no column) is a section, "Stated, but Sangam has no
   field for it", one line and block per fact, carried forward on every merge. Example: Axis's "up to 90%
   of project cost" as `co_funding_share`.
4. **Each section says what is missing.** Under its findings, the newest run's gaps for that section:
   "Not stated — rfp: no open call on abf.org/csr", "Could not read — …", "Not reached — …". A field gap
   always shows; a whole-concept gap only when no finding fills it.
5. **Every writer goes through `build`**: `save_research`, `publish_brief` and `make client-docs` (which
   also uploads, and would otherwise overwrite the record from rows alone).

Private findings stay out of the brief, as today; M3 reads them from their rows.

## Verification
- `pytest -m "not integration"`, `ruff`, `npm run lint` / `build`.
- Exit: render Axis's three staging rows (129, 144, 150) through `build`, read the blocks back: every
  public finding of all three runs present once, stronger sources kept; `parseBrief` reads the page as
  before.
