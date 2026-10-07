---
name: funder-shortlist-brief
description: Use when funder-assessor replies for one organisation are back and need writing up as a shortlist — after funder-matching, or whenever several assessments of one organisation are in hand. Splits funders by gate, orders them by rank_key, carries every citation through, and ends with what to record next. Not for two or three funders the user named; funder-comparison lays those side by side.
---

# The shortlist a fundraiser acts on

The reader wants to know where to start, and what is stopping the rest. Each
assessor reply carries a `gate`, `gate_reasons`, a `score` out of 100, its
`breakdown`, a `coverage` and a `rank_key`, all computed by Sangam from the
cited checks. The score is Sangam's arithmetic, not a sourced fact: say so
once, at the top.

## Order

1. **One line up front:** how many funders were in the catalog, how many were
   assessed, and how many were not and why (the two counted groups from
   funder-matching).
2. **Eligible** — gate `pass`.
3. **Unverified** — gate `unverified`. Each entry says what to verify, from
   its gate_reasons. These are not weaker funders: something required is not
   recorded yet.
4. **Removed** — gate `fail`, each with the gate reason and the cited row
   that shows it.
5. **Not assessed** — the counts of "nothing in common recorded" and
   "nothing recorded", naming the second group when it is short, and any funder
   whose assessment failed.
6. **What to record next** — the gaps that recur across funders, most common
   first, each as an action.

Inside Eligible and Unverified, list funders by `rank_key`, ascending, as a
plain string sort. It already encodes score, coverage, shared districts and
funder id; never re-order by your own reading of the reasons.

## One entry

- The funder's name with its marker: HDFC Bank Limited [funder:2].
- `score/100 · coverage` as given, e.g. "46/100 · 55% of checks recorded".
- The assessor's reasons, each with its citations as given.
- Its first gap, if any.

Keep an entry to three lines.

## Rules that keep it honest

- Repeat each gate, score and coverage exactly as the reply gives them. Never
  compute, adjust or round one, and never move a funder between sections.
- An `unknown` is "not recorded". Never "ineligible", "not met" or "poor fit".
- A `fail` is reported only with the row that shows it. On `area` or `theme` it
  reads "no shared place recorded" or "no shared theme recorded", never "fails".
- A low score with low coverage means little is recorded, not a poor match:
  say so when coverage is under half.
- Copy markers exactly as the assessor gave them, one per row. Never write a
  range such as [grant:1-4].
- "No eligibility bars recorded for this funder" means nobody has recorded
  them, never that the funder sets none.
- If fit_scores holds a stored score for one of these pairs, you may quote it
  [score:N] beside the computed one, labelled as the earlier rubric score. Keep
  the two apart.
