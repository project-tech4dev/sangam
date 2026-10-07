---
name: funder-shortlist-brief
description: Use when funder-assessor verdicts for one organisation are back and need writing up as a shortlist — after funder-matching, or whenever several assessments of one organisation are in hand. Groups funders by tier, carries every citation through, and ends with what to record next. Not for two or three funders the user named; funder-comparison lays those side by side.
---

# The shortlist a fundraiser acts on

The reader wants to know where to start, and what is stopping the rest. A
tier is Sangam's judgement from the cited rows, not a sourced fact: say so
once, at the top.

## Order

1. **One line up front:** how many funders were in the catalog, how many were
   assessed, and how many were not and why (the two counted groups from
   funder-matching).
2. **Strong**, then **possible**, then **weak** — one short entry per funder.
3. **Not enough recorded** — every assessed funder whose verdict was
   `not_enough_recorded`, by name. They are unknowns, not the bottom of the list.
4. **Not assessed** — the counts of "nothing in common recorded" and
   "nothing recorded", naming the second group when it is short, and any funder
   whose assessment failed.
5. **What to record next** — the gaps that recur across funders, most common
   first, each as an action.

## One entry

- The funder's name with its marker: HDFC Bank Limited [funder:2].
- The assessor's reasons, each with its citations as given.
- Its first gap, if any.

Keep a strong or possible entry to three lines. A weak entry says what made it
weak: no shared place or theme, or which check failed and on what row.

## Rules that keep it honest

- Repeat each tier exactly as the assessor gave it. Never promote or demote one.
- An `unknown` is "not recorded". Never "ineligible", "not met" or "poor fit".
- A `fail` is reported only with the row that shows it. On `area` or `theme` it
  reads "no shared place recorded" or "no shared theme recorded", never "fails".
- Copy markers exactly as the assessor gave them, one per row. Never write a
  range such as [grant:1-4].
- "No eligibility bars recorded for this funder" means nobody has recorded
  them, never that the funder sets none.
- No scores and no ranking within a tier beyond what the reasons show. If the
  user asks for a number, say tiers are what Sangam judges, and why.
- If fit_scores holds a stored score for one of these pairs, you may quote it
  [score:N] beside the tier, labelled as the earlier rubric score. Keep the two apart.
