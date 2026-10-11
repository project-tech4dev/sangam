---
name: funder-comparison
description: Use when the user names the funders to judge for one organisation — "how does KABIL fit HDFC?", "compare SBI Foundation and Tata Trusts for Goonj", "why is HDFC only a medium fit for KABIL?". One named funder gets its seven criteria explained; two or more get a side-by-side table. No narrowing step. To find funders the user has not named, use funder-matching instead.
---

# Named funders, scored and laid side by side

## 1. Resolve the ids

Find the organisation and each named funder by name. If a name could mean two
funders, ask which. A company and its foundation are different funders:
never merge Axis Bank Limited with Axis Bank Foundation.

## 2. Call compare_fit once

`compare_fit(org_id, [funder_id, ...])` with every named funder in one call.
It scores exactly those, even one with nothing in common (score null, tier
not_scored), and returns them in `matches`, highest score first. If it
returns "compare_fit failed", report the error and never judge the funders
yourself. If it returns "compare_fit refused", say running a match for this
organisation is for its stewards, admins and Sangam staff, and stop.

## 3a. One funder: explain it

- The score out of 100 and its tier, with "judged on N of M points" when some
  criteria were unknown, then its `summary`.
- Then every criterion in the order given: points/max or "unknown", the note,
  and its cites.
- Then `not_judged`, then `improve` as actions, each with its points.

## 3b. Two or more: one table

| criterion | HDFC Bank Parivartan [funder:7] | SBI Foundation [funder:3] |
|---|---|---|
| score · tier | 73/100 · medium | 40/100 · weak |
| Theme alignment (25) | 25 met [org:9] [funder:7] | 15 partial [org:9] [funder:3] |
| Geography (15) | 12 met — Assam | 6 partial — across India |
| Funding size (10) | unknown | unknown |

- The seven criteria are rows, in the rubric's order, with score and tier on top.
- Under the table: where to start, in one or two sentences, from the scores
  and each funder's first `improve` action.

## Rules that keep it honest

- Repeat each score, tier, points and status exactly as compare_fit gives
  them. Never compute, adjust or round one yourself.
- An `unknown` is "not recorded" and was left out of the score. Never
  "ineligible", "not met" or "poor fit".
- A score is Sangam's own arithmetic under the match-v2 rubric over the cited
  rows, with no source of its own; say so once.
