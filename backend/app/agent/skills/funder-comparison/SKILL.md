---
name: funder-comparison
description: Use when the user names the funders to judge for one organisation — "how does KABIL fit HDFC?", "compare SBI Foundation and Tata Trusts for Goonj", "why is HDFC unverified for KABIL?". One named funder gets its checks explained; two or more get a side-by-side table. No narrowing step. To find funders the user has not named, use funder-matching instead.
---

# Named funders, judged and laid side by side

## 1. Resolve the ids

Find the organisation and each named funder by name. If a name could mean two
funders, ask which. A company and its foundation are different funders:
never merge Axis Bank Limited with Axis Bank Foundation.

## 2. Judge the organisation once

Launch org-readiness for the organisation, alone in its own message, and wait
for it. Reuse it instead if it already ran for this organisation earlier in
this conversation and nothing has been imported for it since.

## 3. Assess every named funder

Launch one funder-assessor per funder with the task tool, all in one message
when your instructions allow that many. Each description names both sides
with their ids. If a task fails, report that funder as "not assessed" with
the error, and never judge it yourself.

## 4a. One funder: explain it

- The gate first, with its gate_reasons, then the score out of 100 with its
  breakdown and coverage, then the assessor's reasons with their citations.
- Then every check, grouped as fit and eligibility: met, fail, or not
  recorded, each with its note and citations.
- Then the gaps, as actions, in the assessor's order.

## 4b. Two or more: one table

| check | HDFC Bank Limited [funder:2] | Funder B [funder:N] |
|---|---|---|
| gate | unverified | pass |
| score (coverage) | 46 (0.55) | 38 (0.70) |
| area | met, state — Assam [org:9] [funder:2] | not recorded |
| reg_12a | met [org:9] | met [org:9] |

- Rows are the check codes either assessment returned. Fit rows come first,
  then eligibility, with the gate and score on top.
- A check one assessment returned and the other did not, because it does not
  apply to that funder, reads "does not apply" — not "not recorded".
- Under the table: where to start, in one or two sentences, from the gates, scores
  and the first gap of each. A funder whose gate is `pass` comes before one
  that is `unverified`, whatever the scores.

## Rules that keep it honest

- Repeat each gate, score, coverage and outcome exactly as the reply gives
  them. Never compute, adjust or round one yourself.
- An `unknown` is "not recorded". Never "ineligible", "not met" or "poor fit".
- A gate `fail` rests on a cited row; name that row. `unverified` means
  something required is not recorded yet, never that the organisation lacks it.
- The score is Sangam's own arithmetic over the cited checks, with no source
  of its own; say so once.
