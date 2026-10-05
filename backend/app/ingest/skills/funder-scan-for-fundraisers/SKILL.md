---
name: funder-scan-for-fundraisers
description: Use when several funders have been researched and a fundraiser at an Indian CSO needs them side by side to decide where to spend the next month — which ones are reachable, which are open now, which fit. Produces the comparison across funders, not the research behind it. What to pull for each funder is funder-intake-research; the record for one funder on its own is entity-record. Not for a single fact about a funder already in the catalog; funder_dossier answers that in one call.
---

# The comparison a fundraiser acts on

The reader has a month and a list. They are not reading to learn about
funders; they are deciding which two or three to approach. The comparison
earns its place only if it ends with them knowing where to start.

The fields come from `funder-intake-research` and the per-funder record from
`entity-record`. This skill is only the table across them, and the judgement
rules that make it honest.

## The table

One row per funder, in this order: **reachable now** (intake route, live or
not, checked when) · **open call and deadline** · **grant size band** ·
**co-funding share** · **who it funds** — external NGOs, or mainly its own
programmes · **sectors** · **districts** · **hard disqualifiers** · **latest
annual CSR spend with its financial year**.

Reachability leads because an unreachable funder with a perfect sector match
is worth less than a reachable one with an adequate match, and a list sorted
by spend hides that.

## Rules that keep it honest

**Never merge a company with its foundation.** Axis Bank Limited and Axis
Bank Foundation are two rows and a link. Company-level and foundation-level
spending stay apart.

**Every figure carries its financial year.** A spend with no year is not a
comparable number.

**"Funds external NGOs" is two facts, reported side by side, never
averaged** — what the funder says, and how many of its recorded projects
actually ran through an implementing agency.

**Do not estimate.** No inferred grant size, no estimated spend. If a range
comes from examples, say so and show the examples. An announced project
value, an actual grant amount and a whole programme's budget are three
different numbers.

**A stated priority geography is not a footprint.** Where a funder says it
cares and where its money went are separate columns when both are known.

**Describe the best-fit NGO profile; never score it.** A number invented here
is a judgement wearing a citation, and the funder's own criteria decide fit.

## Three things never conflated in a cell

- **not disclosed** — the funder did not publish it
- **found, not storable** — they published it and no column exists for it
- **not recorded** — nobody has looked yet

Writing "not disclosed" over a field we simply cannot store misrepresents the
funder. Say which of the three the cell means.

Two columns moved out of the middle category and the cells have to move with
them. **Hard disqualifiers** and the **eligibility bar** are now stored, in
`funder_eligibility`, split by `kind` — so an empty cell there means *not
recorded* or *not disclosed*, never *found, not storable*. Read them from the
dossier rather than from the research prose, and keep `kind` visible: a bar
that only restates the statutory minimum is not a bar the funder chose, and a
fundraiser comparing two funders needs to see which is which.

**Open call and deadline come from `rfps`, and an empty section is "not
recorded".** A funder we have never checked for calls and a funder with no
open call look identical in the catalog, and only the first is a reason to go
looking.
