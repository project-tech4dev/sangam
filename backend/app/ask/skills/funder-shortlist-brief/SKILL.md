---
name: funder-shortlist-brief
description: Use when a compare_fit reply for one organisation needs writing up as a shortlist — after funder-matching. Groups funders by tier, keeps compare_fit's order, carries every citation through, and ends with what would raise the scores. Not for two or three funders the user named; funder-comparison lays those side by side.
---

# The shortlist a fundraiser acts on

The reader wants to know who to approach first and why. Every score, tier,
point and status in compare_fit's reply is Sangam's arithmetic under the
match-v2 rubric over the cited rows, with no source of its own: say so once,
at the top.

## Order

1. **One line up front:** the funders checked, how many were scored, and how
   many were not, from the reply's first two lines.
2. **Strong fits** (tier strong), then **Medium fits** (tier medium), in the
   reply's order. Never re-order by your own reading. Past the first ten,
   strong and medium fits come as one-line entries: write those as one line too.
3. **Weak fits** (tier weak): one line each, the score and its first `!` card
   line, as the reply's one-line entries give them.
4. **Not scored:** "nothing in common recorded" as a count, naming them when
   short; then the funders with nothing recorded, said as unknown, never as a
   poor fit.
5. **Not judged:** the criteria on the `unknown across` line that were unknown
   for most funders, once, e.g. "funding size: none of these funders publishes
   a grant range".
6. **What would raise the scores:** the `to raise the score:` actions that
   recur across the strong and medium fits, most points first.

## One entry (strong and medium)

- The funder with its marker, its type, and `score/100 · tier`, plus "judged on
  66 of 90 points" when some criteria were unknown.
- Its card lines as given: ✓ for a fit, ! for a gap.
- The criteria that earned or lost the most, each with its points and cites,
  e.g. "Geography 12/15 — Assam is one of its states [org:9] [funder:7]".
- Its first `to raise the score:` action.

Keep an entry to five lines.

## Rules that keep it honest

- Repeat each score, tier, points and status exactly as compare_fit gives them.
  Never compute, adjust or round one, and never move a funder between tiers.
- An `unknown` criterion is "not recorded" and was left out of the score.
  Never "ineligible", "not met" or "poor fit".
- A `fail` on theme or geography reads "no shared theme recorded" or "no shared
  place recorded". A relationship `fail` means none is recorded, never that
  the funder refused.
- A claimed credential counts and says who claims it, as in the note.
- A funder's own bar listed under `not_judged` is a criterion a person has to
  read: name it, never decide it.
- Copy markers exactly as compare_fit gave them, one per row. Never write a
  range such as [activity:1-4].
- If fit_scores holds a stored score for one of these pairs, you may quote it
  [score:N] beside the computed one, labelled as the earlier rubric score. Keep
  the two apart.
