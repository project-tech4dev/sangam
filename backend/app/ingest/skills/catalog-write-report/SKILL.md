---
name: catalog-write-report
description: Use when a write to the catalog has just happened and the person needs to be told exactly what landed — after promote_research, or after a catalog-writer subagent returns. Says what to report per table and row, how to state what was held back and why, what to do when nothing was written at all, and the claims that are never allowed because they describe rows nobody read back. Not for deciding what to write, and not for comparing research against the catalog before a write — catalog-mapping owns that.
---

# Saying what actually went into the database

The person asked for research and got a write. What they need back is not
"done" — it is which rows now exist that did not before, and what we decided
not to write.

## Report only rows that were read back

`promote_research` reads the catalog after writing and reports what it finds
there. Every number in the report comes from that read. **Never report a row
because a write was attempted and did not error** — a held-back value, a
failed match and a successful insert all look the same from the calling side,
which is exactly why the read-back exists.

If `verified` is false, the dossier was not read back and agreed. Say so in
the same breath as the counts, every time. A number without its read-back is
a claim, not a report.

## What to say

**Per table, the count.** "`funder_csr_years` 3 rows, `funder_csr_spend` 11
rows, `funder_locations` 4 rows." Name the tables. A person tracking what the
catalog knows is tracking tables, and "17 rows written" tells them nothing
about what they can now query.

**Held back, verbatim, each one.** These are not warnings to summarise into
"some values were skipped" — each one is a decision somebody has to make: a
duplicate where the first was kept, a validation failure naming the field, a
place that could not be resolved to a district, a parent company that did not
match. Give the reason as written and name the organisation and field it
concerns.

**Still research.** Concepts with no writer. Say what they are and say that
the facts exist, are published in the entity record, and are not in the
catalog. "Nothing was written" and "nothing was found" are opposite
situations and must never read the same.

**Nothing had nowhere to go, or this many fields did.** If the mapping step
found values that are real, cited and have no column, repeat the count here.
That number is the backlog, and the write report is where a person sees it.

## When nothing was written

Two cases, and they are different:

- **An organisation that receives money.** `orgs` has no writer, so no NGO
  research is ever promoted. Say the research is saved, published and on
  file, and that it stays research until a writer lands — not "failed", not
  "held back", and never silently. This is the expected path, not an error.
- **A funder where everything was held.** Say which gate stopped it — no
  match, a stale schema version, every value a duplicate — and what would
  change it.

## Never

- Never report a count you did not read back out of the database.
- Never fold held-back reasons into a total.
- Never describe an NGO's saved research as "added to the catalog".
- Never say "successfully" without the table names behind it.
