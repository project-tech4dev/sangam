---
name: funder-comparison
description: Use when the user names the funders to judge for one organisation — "how does KABIL fit HDFC?", "compare SBI Foundation and Tata Trusts for Goonj", "why is HDFC unverified for KABIL?". One named funder gets its checks explained; two or more get a side-by-side table. No narrowing step. To find funders the user has not named, use funder-matching instead.
---

# Named funders, judged and laid side by side

## 1. Resolve the ids

Find the organisation and each named funder by name. If a name could mean two
funders, ask which. A company and its foundation are different funders:
never merge Axis Bank Limited with Axis Bank Foundation.

## 2. Call compare_fit once

`compare_fit(org_id, [funder_id, ...])` with every named funder in one call.
It judges exactly those, even one with nothing in common, and returns them in
`assessed` sorted by rank_key, with the organisation's own checks once in
`readiness`. If it returns "compare_fit failed", report the error and never
judge the funders yourself.

## 4a. One funder: explain it

- The gate first, with its gate_reasons, then the score out of 100 with its
  breakdown and coverage, then the reasons with their citations.
- Then every check — the funder's own `checks`, then `readiness` — met, fail,
  or not recorded, each with its note and citations. A `funder_bar` is the
  funder's own criterion, awaiting review: name it, never decide it.
- Then the gaps, as actions, in the order given.

## 4b. Two or more: one table

| check | HDFC Bank Limited [funder:2] | Funder B [funder:N] |
|---|---|---|
| gate | unverified | pass |
| score (coverage) | 46 (0.55) | 38 (0.70) |
| area | met, state — Assam [org:9] [funder:2] | not recorded |
| reg_12a | met [org:9] | met [org:9] |

- Rows are the funder checks first, with the gate and score on top. The
  `readiness` checks are the same for every funder: list them once under the
  table, not as columns.
- A funder_bar one funder recorded and the other did not reads "none
  recorded" for the second.
- Under the table: where to start, in one or two sentences, from the gates, scores
  and the first gap of each. A funder whose gate is `pass` comes before one
  that is `unverified`, whatever the scores.

## Rules that keep it honest

- Repeat each gate, score, coverage and outcome exactly as compare_fit gives
  them. Never compute, adjust or round one yourself.
- An `unknown` is "not recorded". Never "ineligible", "not met" or "poor fit".
- A gate `fail` rests on a cited row; name that row. `unverified` means
  something required is not recorded yet, never that the organisation lacks it.
- The score is Sangam's own arithmetic over the cited checks, with no source
  of its own; say so once.
